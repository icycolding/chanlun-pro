import datetime
import json
import os
import pathlib
import sys
import time
import traceback

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("JAX_PLATFORMS", "cpu")

import pinyin
import pytz
from apscheduler.events import (
    EVENT_ALL,
    EVENT_EXECUTOR_ADDED,
    EVENT_EXECUTOR_REMOVED,
    EVENT_JOB_ADDED,
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_JOB_MODIFIED,
    EVENT_JOB_REMOVED,
    EVENT_JOB_SUBMITTED,
    EVENT_JOBSTORE_ADDED,
    EVENT_JOBSTORE_REMOVED,
)
from apscheduler.executors.tornado import TornadoExecutor
from apscheduler.schedulers.tornado import TornadoScheduler
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file
from flask_login import LoginManager, UserMixin, login_required, login_user
from tzlocal import get_localzone

from chanlun import config, fun
from chanlun.base import Market
from chanlun.cl_utils import (
    cl_data_to_tv_chart,
    del_cl_chart_config,
    kcharts_frequency_h_l_map,
    query_cl_chart_config,
    set_cl_chart_config,
    web_batch_get_cl_datas,
)
from chanlun.config import get_data_path
from chanlun.db import db
from chanlun.exchange import get_exchange
from chanlun.exchange.stocks_bkgn import StocksBKGN
from chanlun.tools.ai_analyse import AIAnalyse
from chanlun.zixuan import ZiXuan

from .alert_tasks import AlertTasks
from .other_tasks import OtherTasks
from .xuangu_tasks import XuanguTasks
from .news_vector_api import register_vector_api_routes
from .smart_news_api import register_smart_news_api
from .asset_news_mapping import build_asset_link_rows
from .a_share_matches_quotes import (
    build_chart_url,
    fetch_tick_snapshots,
    infer_project_chart_target,
    infer_project_quote_target,
    normalize_market_codes,
)
from .a_share_matches_catalog import (
    build_theme_index_history,
    build_theme_index_live,
    get_a_share_match_catalog,
    get_theme_a_share_index,
    get_theme_related_stock_detail,
)
from .a_share_matches_tweets import (
    build_tweet_detail_url,
    build_tweet_detail_payload,
    build_tweet_summaries,
    get_tweets_data_version,
)
from .a_share_stock_analysis import (
    build_stock_analysis_detail_payload,
    build_stock_analysis_summaries,
)
from .a_share_stock_analysis_workspace import sync_workspace_stock_analysis_payload
from .community_sync import sync_community_discussions_for_stock
from .serenity_aistocks import (
    register_serenity_aistocks_routes,
    sync_serenity_aistocks_latest_prices,
)
from .tv_chart_request_mode import (
    apply_lite_chart_config_override,
    is_lite_chart_request,
)
from .tv_history_cache import TTLCache, build_tv_history_cache_key

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
_NEWS_DIR = _PROJECT_ROOT / "news"
if str(_NEWS_DIR) not in sys.path:
    sys.path.append(str(_NEWS_DIR))

from watch_jin10 import sync_jin10_news_once


def _resolve_tv_symbol_stock_info(ex, market: str, code: str):
    """
    TradingView symbol metadata needs to be resilient for markets like FX where
    the incoming code may be `audusd` while exchange metadata stores `FX.AUDUSD`.
    """
    normalized_code = str(code or "").strip()
    if not normalized_code:
        return None

    try:
        stock = ex.stock_info(normalized_code)
        if stock:
            return stock
    except Exception:
        pass

    try:
        all_stocks = ex.all_stocks() or []
    except Exception:
        all_stocks = []

    target_upper = normalized_code.upper()
    target_lower = normalized_code.lower()
    suffix_patterns = {
        target_upper,
        target_lower,
        f"{market.upper()}.{target_upper}",
        f"{market.lower()}.{target_lower}",
    }

    for item in all_stocks:
        item_code = str(item.get("code") or "").strip()
        if not item_code:
            continue
        item_upper = item_code.upper()
        item_lower = item_code.lower()
        if (
            item_upper in suffix_patterns
            or item_lower in suffix_patterns
            or item_upper.endswith(f".{target_upper}")
            or item_lower.endswith(f".{target_lower}")
        ):
            resolved = dict(item)
            resolved.setdefault("code", item_code)
            resolved.setdefault("name", normalized_code.upper())
            return resolved

    return {
        "code": normalized_code.upper(),
        "name": normalized_code.upper(),
        "precision": 10000 if market in ["fx", "currency", "currency_spot"] else 1000,
    }


def _parse_tv_symbol(symbol: str):
    normalized_symbol = str(symbol or "").strip()
    if ":" not in normalized_symbol:
        return None, None
    market, code = normalized_symbol.split(":", 1)
    market = market.strip().lower()
    code = code.strip()
    if not market or not code:
        return None, None
    return market, code


def create_app(test_config=None):
    # 任务对象
    scheduler = TornadoScheduler(timezone=pytz.timezone("Asia/Shanghai"))
    scheduler.add_executor(TornadoExecutor())
    scheduler.my_task_list = {}

    def run_tasks_listener(event):
        state_map = {
            EVENT_EXECUTOR_ADDED: "已添加",
            EVENT_EXECUTOR_REMOVED: "删除调度",
            EVENT_JOBSTORE_ADDED: "已添加",
            EVENT_JOBSTORE_REMOVED: "删除存储",
            EVENT_JOB_ADDED: "已添加",
            EVENT_JOB_REMOVED: "删除作业",
            EVENT_JOB_MODIFIED: "修改作业",
            EVENT_JOB_SUBMITTED: "运行中",
            EVENT_JOB_MAX_INSTANCES: "等待运行",
            EVENT_JOB_EXECUTED: "已完成",
            EVENT_JOB_ERROR: "执行异常",
            EVENT_JOB_MISSED: "未执行",
        }
        if event.code not in state_map.keys():
            return
        if hasattr(event, "job_id"):
            job_id = event.job_id
            if job_id not in scheduler.my_task_list.keys():
                scheduler.my_task_list[job_id] = {
                    "id": job_id,
                    "name": "--",
                    "update_dt": fun.datetime_to_str(datetime.datetime.now()),
                    "next_run_dt": "--",
                    "state": "未知",
                }
            scheduler.my_task_list[job_id]["update_dt"] = fun.datetime_to_str(
                datetime.datetime.now()
            )
            job = scheduler.get_job(event.job_id)
            if job is not None:
                scheduler.my_task_list[job_id]["name"] = job.name
                scheduler.my_task_list[job_id]["next_run_dt"] = fun.datetime_to_str(
                    job.next_run_time
                )
            scheduler.my_task_list[job_id]["state"] = state_map[event.code]
            # print('任务更新', task_list[job_id])
        return

    scheduler.add_listener(run_tasks_listener, EVENT_ALL)
    scheduler.start()

    # 项目中的周期与 tv 的周期对应表
    frequency_maps = {
        "10s": "10S",
        "30s": "30S",
        "1m": "1",
        "2m": "2",
        "3m": "3",
        "5m": "5",
        "10m": "10",
        "15m": "15",
        "30m": "30",
        "60m": "60",
        "120m": "120",
        "3h": "180",
        "4h": "240",
        "d": "1D",
        "2d": "2D",
        "w": "1W",
        "m": "1M",
        "y": "12M",
    }

    resolution_maps = dict(zip(frequency_maps.values(), frequency_maps.keys()))

    # 各个市场支持的时间周期
    market_frequencys = {
        "a": list(get_exchange(Market.A).support_frequencys().keys()),
        "hk": list(get_exchange(Market.HK).support_frequencys().keys()),
        "fx": list(get_exchange(Market.FX).support_frequencys().keys()),
        "us": list(get_exchange(Market.US).support_frequencys().keys()),
        "futures": list(get_exchange(Market.FUTURES).support_frequencys().keys()),
        "ny_futures": list(get_exchange(Market.NY_FUTURES).support_frequencys().keys()),
        "currency": list(get_exchange(Market.CURRENCY).support_frequencys().keys()),
        "currency_spot": list(
            get_exchange(Market.CURRENCY_SPOT).support_frequencys().keys()
        ),
    }

    # 各个交易所默认的标的
    market_default_codes = {
        "a": get_exchange(Market.A).default_code(),
        "hk": get_exchange(Market.HK).default_code(),
        "fx": get_exchange(Market.FX).default_code(),
        "us": get_exchange(Market.US).default_code(),
        "futures": get_exchange(Market.FUTURES).default_code(),
        "ny_futures": get_exchange(Market.NY_FUTURES).default_code(),
        "currency": get_exchange(Market.CURRENCY).default_code(),
        "currency_spot": get_exchange(Market.CURRENCY_SPOT).default_code(),
    }

    # 各个市场的交易时间
    market_session = {
        "a": "24x7",
        "hk": "24x7",
        "fx": "24x7",
        "us": "0400-0931,0930-1631,1600-2001",
        "futures": "24x7",
        "ny_futures": "24x7",
        "currency": "24x7",
        "currency_spot": "24x7",
    }

    # 各个交易所的时区 统一时区
    market_timezone = {
        "a": "Asia/Shanghai",
        "hk": "Asia/Shanghai",
        "fx": "Asia/Shanghai",
        "us": "America/New_York",
        "futures": "Asia/Shanghai",
        "ny_futures": "Asia/Shanghai",
        "currency": str(get_localzone()),
        "currency_spot": str(get_localzone()),
    }

    market_types = {
        "a": "stock",
        "hk": "stock",
        "fx": "stock",
        "us": "stock",
        "futures": "futures",
        "ny_futures": "futures",
        "currency": "crypto",
        "currency_spot": "crypto",
    }

    # 记录请求次数，超过则返回 no_data
    __history_req_counter = {}
    __tv_history_cache = TTLCache(max_entries=96)

    _alert_tasks = AlertTasks(scheduler)
    _alert_tasks.run()

    _xuangu_tasks = XuanguTasks(scheduler)

    _other_tasks = OtherTasks(scheduler)

    __log = fun.get_logger()
    jin10_watch_job_id = "jin10_news_watch"
    jin10_watch_state_path = get_data_path() / "jin10_seen.json"
    serenity_aistocks_price_job_id = "serenity_aistocks_latest_price_sync"
    jin10_watch_status = {
        "interval": 30,
        "max_items": 50,
        "url": "https://www.jin10.com/",
        "state_path": str(jin10_watch_state_path),
        "started_at": None,
        "last_run_at": None,
        "last_inserted": 0,
        "last_skipped": 0,
        "last_vector_synced": 0,
        "last_error": "",
    }
    serenity_aistocks_price_sync_status = {
        "interval_seconds": 180,
        "started_at": None,
        "last_run_at": None,
        "last_success_count": 0,
        "last_unsupported_count": 0,
        "last_error_count": 0,
        "last_total_candidates": 0,
        "last_error": "",
    }

    def _serenity_aistocks_price_sync_snapshot():
        job = scheduler.get_job(serenity_aistocks_price_job_id)
        return {
            "running": job is not None,
            "interval_seconds": serenity_aistocks_price_sync_status["interval_seconds"],
            "started_at": serenity_aistocks_price_sync_status["started_at"],
            "last_run_at": serenity_aistocks_price_sync_status["last_run_at"],
            "last_success_count": serenity_aistocks_price_sync_status["last_success_count"],
            "last_unsupported_count": serenity_aistocks_price_sync_status["last_unsupported_count"],
            "last_error_count": serenity_aistocks_price_sync_status["last_error_count"],
            "last_total_candidates": serenity_aistocks_price_sync_status["last_total_candidates"],
            "last_error": serenity_aistocks_price_sync_status["last_error"],
        }

    def _jin10_watch_snapshot():
        job = scheduler.get_job(jin10_watch_job_id)
        return {
            "running": job is not None,
            "job_id": jin10_watch_job_id,
            "interval": jin10_watch_status["interval"],
            "max_items": jin10_watch_status["max_items"],
            "url": jin10_watch_status["url"],
            "state_path": jin10_watch_status["state_path"],
            "started_at": jin10_watch_status["started_at"],
            "last_run_at": jin10_watch_status["last_run_at"],
            "last_inserted": jin10_watch_status["last_inserted"],
            "last_skipped": jin10_watch_status["last_skipped"],
            "last_vector_synced": jin10_watch_status["last_vector_synced"],
            "last_error": jin10_watch_status["last_error"],
            "next_run_at": fun.datetime_to_str(job.next_run_time)
            if job is not None and job.next_run_time is not None
            else None,
        }

    def _run_jin10_watch_job(url: str, state_path: str, max_items: int):
        run_at = datetime.datetime.now()
        try:
            inserted_count, skipped_count, vector_synced_count = sync_jin10_news_once(
                db=db,
                url=url,
                state_path=pathlib.Path(state_path),
                max_items=max_items,
            )
            jin10_watch_status["last_run_at"] = run_at.isoformat()
            jin10_watch_status["last_inserted"] = inserted_count
            jin10_watch_status["last_skipped"] = skipped_count
            jin10_watch_status["last_vector_synced"] = vector_synced_count
            jin10_watch_status["last_error"] = ""
            __log.info(
                f"金十新闻同步完成 inserted={inserted_count} skipped={skipped_count} "
                f"vector_synced={vector_synced_count}"
            )
        except Exception as e:
            jin10_watch_status["last_run_at"] = run_at.isoformat()
            jin10_watch_status["last_error"] = str(e)
            __log.error(f"金十新闻同步失败: {str(e)}")
            raise

    def _run_serenity_aistocks_price_sync_job():
        run_at = datetime.datetime.now()
        try:
            result = sync_serenity_aistocks_latest_prices(db_instance=db)
            serenity_aistocks_price_sync_status["last_run_at"] = run_at.isoformat()
            serenity_aistocks_price_sync_status["last_success_count"] = int(
                result.get("success_count", 0)
            )
            serenity_aistocks_price_sync_status["last_unsupported_count"] = int(
                result.get("unsupported_count", 0)
            )
            serenity_aistocks_price_sync_status["last_error_count"] = int(
                result.get("error_count", 0)
            )
            serenity_aistocks_price_sync_status["last_total_candidates"] = int(
                result.get("total_candidates", 0)
            )
            serenity_aistocks_price_sync_status["last_error"] = ""
            __log.info(
                "Serenity AI Stocks 价格同步完成 "
                f"success={serenity_aistocks_price_sync_status['last_success_count']} "
                f"unsupported={serenity_aistocks_price_sync_status['last_unsupported_count']} "
                f"errors={serenity_aistocks_price_sync_status['last_error_count']}"
            )
        except Exception as e:
            serenity_aistocks_price_sync_status["last_run_at"] = run_at.isoformat()
            serenity_aistocks_price_sync_status["last_error"] = str(e)
            __log.error(f"Serenity AI Stocks 价格同步失败: {str(e)}")

    def _start_serenity_aistocks_price_sync(interval_seconds: int = 60):
        serenity_aistocks_price_sync_status["interval_seconds"] = interval_seconds
        serenity_aistocks_price_sync_status["started_at"] = datetime.datetime.now().isoformat()
        scheduler.add_job(
            _run_serenity_aistocks_price_sync_job,
            trigger="interval",
            seconds=interval_seconds,
            id=serenity_aistocks_price_job_id,
            name="Serenity AI Stocks 定时价格入库",
            replace_existing=True,
            next_run_time=datetime.datetime.now(),
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(interval_seconds, 30),
        )

    def _start_jin10_watch(interval: int, max_items: int, url: str, state_path: str):
        resolved_state_path = pathlib.Path(state_path).expanduser().resolve()
        resolved_state_path.parent.mkdir(parents=True, exist_ok=True)
        jin10_watch_status["interval"] = interval
        jin10_watch_status["max_items"] = max_items
        jin10_watch_status["url"] = url
        jin10_watch_status["state_path"] = str(resolved_state_path)
        jin10_watch_status["started_at"] = datetime.datetime.now().isoformat()
        scheduler.add_job(
            _run_jin10_watch_job,
            trigger="interval",
            seconds=interval,
            id=jin10_watch_job_id,
            name="金十新闻定时入库",
            kwargs={
                "url": url,
                "state_path": str(resolved_state_path),
                "max_items": max_items,
            },
            replace_existing=True,
            next_run_time=datetime.datetime.now(),
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(interval, 30),
        )

    def _stop_jin10_watch():
        job = scheduler.get_job(jin10_watch_job_id)
        if job is not None:
            scheduler.remove_job(jin10_watch_job_id)
        if jin10_watch_job_id in scheduler.my_task_list:
            del scheduler.my_task_list[jin10_watch_job_id]

    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    if test_config:
        app.config.update(test_config)
    app.logger.addFilter(
        lambda record: "/static/" not in record.getMessage().lower()
    )  # 过滤静态资源请求日志

    # 添加登录验证
    app.secret_key = "cl_pro_secret_key"
    login_manager = LoginManager()  # 实例化登录管理对象
    login_manager.init_app(app)  # 初始化应用
    login_manager.login_view = "login_opt"  # 设置用户登录视图函数 endpoint
    register_serenity_aistocks_routes(
        app, status_provider=_serenity_aistocks_price_sync_snapshot
    )

    class LoginUser(UserMixin):
        def __init__(self) -> None:
            super().__init__()
            self.id = "cl_pro"

    @login_manager.user_loader
    def load_user(user_id):
        return LoginUser()

    @app.route("/login", methods=["GET", "POST"])
    def login_opt():
        # 未设置登录密码，默认直接进行登录
        if config.LOGIN_PWD == "":
            login_user(
                LoginUser(), remember=True, duration=datetime.timedelta(days=365)
            )
            return redirect("/")

        emsg = ""
        if request.method == "POST":
            password = request.form.get("password")
            if password == config.LOGIN_PWD:
                login_user(
                    LoginUser(), remember=True, duration=datetime.timedelta(days=365)
                )
                return redirect("/")
            else:
                emsg = "密码错误"

        return render_template("login.html", emsg=emsg)

    @app.route("/")
    @login_required
    def index_show():
        """
        首页
        """

        return render_template(
            "index.html",
            market_default_codes=market_default_codes,
            market_frequencys=market_frequencys,
            jin10_watch_defaults={
                "interval": jin10_watch_status["interval"],
                "max_items": jin10_watch_status["max_items"],
            },
        )

    @app.route("/market_summary")
    @login_required
    def market_summary():
        """
        市场总结页面
        """
        return render_template("market_summary.html")

    @app.route("/asset_news")
    @login_required
    def asset_news():
        """
        资产新闻页面
        """
        return render_template("asset_news.html")

    @app.route("/a_share_matches")
    @login_required
    def a_share_matches():
        """
        项目推荐股与A股映射表页面
        """
        catalog = get_a_share_match_catalog()
        for theme in catalog.get("themes", []):
            for stock in theme.get("project_stocks", []):
                stock["tweet_detail_url"] = build_tweet_detail_url(
                    symbol=str(stock.get("symbol") or "").strip(),
                    company_name=str(stock.get("company_name") or "").strip(),
                    exchange=str(stock.get("exchange") or "").strip(),
                    market=str(stock.get("market") or "").strip(),
                    display_name=str(stock.get("display_name") or "").strip(),
                )
                chart_target = infer_project_chart_target(
                    symbol=str(stock.get("symbol") or "").strip(),
                    exchange=str(stock.get("exchange") or "").strip(),
                    market_text=str(stock.get("market") or "").strip(),
                    company_name=str(stock.get("company_name") or "").strip(),
                )
                stock["chart_url"] = build_chart_url(
                    chart_target.get("market", ""),
                    chart_target.get("code", ""),
                )
                stock["chart_unavailable_reason"] = str(
                    chart_target.get("unavailable_reason") or ""
                )
                stock["chart_frequency_label"] = "主页图形"
        return render_template("a_share_matches.html", catalog=catalog)

    @app.route("/a_share_matches/theme-stock/<theme_slug>/<code>")
    @login_required
    def a_share_matches_theme_stock_detail(theme_slug, code):
        detail = get_theme_related_stock_detail(theme_slug, code)
        if not detail:
            abort(404)

        return render_template(
            "a_share_match_theme_stock.html",
            theme_title=detail["theme_title"],
            theme_slug=detail["theme_slug"],
            theme_accent=detail["theme_accent"],
            theme_accent_soft=detail["theme_accent_soft"],
            theme_accent_line=detail["theme_accent_line"],
            stock=detail["stock"],
        )

    @app.route("/a_share_matches/project_ticks", methods=["POST"])
    @login_required
    def a_share_matches_project_ticks():
        payload = request.get_json(silent=True) or {}
        items = payload.get("items") or []

        grouped_codes = {}
        code_sources = {}
        unsupported = []

        for item in items:
            symbol = str(item.get("symbol") or "").strip()
            exchange_name = str(item.get("exchange") or "").strip()
            market_name = str(item.get("market") or "").strip()
            company_name = str(item.get("company_name") or "").strip()
            target = infer_project_quote_target(symbol, exchange_name, market_name, company_name)
            if not target:
                unsupported.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange_name,
                        "market": market_name,
                        "reason": "unsupported_market",
                    }
                )
                continue
            market_key = target["market"]
            code = target["code"]
            grouped_codes.setdefault(market_key, [])
            if code not in grouped_codes[market_key]:
                grouped_codes[market_key].append(code)
            code_sources.setdefault((market_key, code), []).append(symbol)

        quotes = []
        for market_key, codes in grouped_codes.items():
            try:
                ex = get_exchange(Market(market_key))
                snapshots = fetch_tick_snapshots(ex, codes)
                for code, snapshot in snapshots.items():
                    snapshot["market"] = market_key
                    snapshot["symbols"] = code_sources.get((market_key, code), [code])
                    quotes.append(snapshot)
                missing_codes = [code for code in codes if code not in snapshots]
                for code in missing_codes:
                    unsupported.append(
                        {
                            "symbol": ",".join(code_sources.get((market_key, code), [code])),
                            "exchange": market_key,
                            "market": market_key,
                            "reason": "quote_unavailable",
                        }
                    )
            except Exception:
                traceback.print_exc()
                for code in codes:
                    unsupported.append(
                        {
                            "symbol": ",".join(code_sources.get((market_key, code), [code])),
                            "exchange": market_key,
                            "market": market_key,
                            "reason": "tick_fetch_failed",
                        }
                    )

        return jsonify({"quotes": quotes, "unsupported": unsupported})

    @app.route("/a_share_matches/theme_index_history", methods=["POST"])
    @login_required
    def a_share_matches_theme_index_history():
        payload = request.get_json(silent=True) or {}
        theme_slug = str(payload.get("theme_slug") or "").strip()
        raw_lookback_days = payload.get("lookback_days")
        reference_date = str(payload.get("reference_date") or "").strip()
        lookback_mode = str(raw_lookback_days or "").strip().lower()
        is_max_range = lookback_mode in {"max", "all"}
        lookback_days = None if is_max_range else max(1, min(500, int(raw_lookback_days or 250)))
        index_meta = get_theme_a_share_index(theme_slug)
        if not index_meta:
            return jsonify(
                {
                    "theme_slug": theme_slug,
                    "title": "",
                    "base_value": 1000.0,
                    "lookback_label": "最长历史" if is_max_range else f"近{int(lookback_days or 250)}日",
                    "is_max_range": is_max_range,
                    "coverage": {"used_constituents": 0, "total_constituents": 0, "date_points": 0},
                    "constituents": [],
                    "series": [],
                    "error": "theme_not_found",
                }
            ), 404

        result = build_theme_index_history(
            theme_slug,
            lookback_days=lookback_days,
            range_mode="max" if is_max_range else "",
            reference_date=reference_date,
        )
        response_payload = {
            **result,
            "lookback_days": "max" if is_max_range else lookback_days,
            "lookback_label": result.get("lookback_label") or ("最长历史" if is_max_range else f"近{int(lookback_days or 250)}日"),
            "is_max_range": bool(result.get("is_max_range") or is_max_range),
            "error": "" if result.get("series") else "history_unavailable",
        }
        return jsonify(response_payload)

    @app.route("/a_share_matches/theme_index_snapshots", methods=["POST"])
    @login_required
    def a_share_matches_theme_index_snapshots():
        payload = request.get_json(silent=True) or {}
        theme_slugs = payload.get("theme_slugs") or []
        snapshots = []
        for theme_slug in theme_slugs:
            normalized_slug = str(theme_slug or "").strip()
            if not normalized_slug:
                continue
            snapshots.append(build_theme_index_live(normalized_slug))
        return jsonify({"snapshots": snapshots})

    @app.route("/a_share_matches/tweet_summaries", methods=["POST"])
    @login_required
    def a_share_matches_tweet_summaries():
        payload = request.get_json(silent=True) or {}
        items = payload.get("items") or []
        return jsonify(
            {
                "summaries": build_tweet_summaries(items),
                "data_version": get_tweets_data_version(),
            }
        )

    @app.route("/a_share_matches/stock_analysis_summaries", methods=["POST"])
    @login_required
    def a_share_matches_stock_analysis_summaries():
        payload = request.get_json(silent=True) or {}
        items = payload.get("items") or []
        return jsonify(
            {
                "summaries": build_stock_analysis_summaries(items),
            }
        )

    @app.route("/a_share_matches/community-sync", methods=["POST"])
    @login_required
    def a_share_matches_community_sync():
        payload = request.get_json(silent=True) or {}
        symbol = str(payload.get("symbol") or "").strip()
        company_name = str(payload.get("company_name") or "").strip()
        limit = int(payload.get("limit") or 20)
        return jsonify(
            sync_community_discussions_for_stock(
                symbol=symbol,
                company_name=company_name,
                limit=max(limit, 1),
            )
        )

    @app.route("/api/workspace/stock-analysis/sync", methods=["POST"])
    @login_required
    def workspace_stock_analysis_sync():
        payload = request.get_json(silent=True) or {}
        return jsonify(sync_workspace_stock_analysis_payload(payload))

    @app.route("/a_share_matches/tweets/<symbol>/data")
    @login_required
    def a_share_matches_tweet_detail_data(symbol):
        company_name = str(request.args.get("company_name") or "").strip()
        exchange_name = str(request.args.get("exchange") or "").strip()
        market_name = str(request.args.get("market") or "").strip()
        display_name = str(request.args.get("display_name") or "").strip()
        return jsonify(
            build_tweet_detail_payload(
                symbol=symbol,
                company_name=company_name,
                exchange=exchange_name,
                market=market_name,
                display_name=display_name,
            )
        )

    @app.route("/a_share_matches/tweets/<symbol>")
    @login_required
    def a_share_matches_tweet_detail(symbol):
        company_name = str(request.args.get("company_name") or "").strip()
        exchange_name = str(request.args.get("exchange") or "").strip()
        market_name = str(request.args.get("market") or "").strip()
        display_name = str(request.args.get("display_name") or "").strip()
        detail_payload = build_tweet_detail_payload(
            symbol=symbol,
            company_name=company_name,
            exchange=exchange_name,
            market=market_name,
            display_name=display_name,
        )
        return render_template(
            "a_share_match_tweets.html",
            symbol=symbol,
            company_name=company_name,
            exchange=exchange_name,
            market=market_name,
            display_name=display_name,
            mention_count=detail_payload["mention_count"],
            latest_mention_at=detail_payload["latest_mention_at"],
            overview_title=detail_payload["overview_title"],
            overview_summary=detail_payload["overview_summary"],
            why_serenity_likes_it=detail_payload["why_serenity_likes_it"],
            industry_chain=detail_payload["industry_chain"],
            stage_view=detail_payload["stage_view"],
            market_cap_view=detail_payload["market_cap_view"],
            timeline_sections=detail_payload["timeline_sections"],
            data_version=detail_payload["data_version"],
            source_scope=detail_payload["source_scope"],
            archive_updated_at=detail_payload["archive_updated_at"],
            latest_archive_at=detail_payload["latest_archive_at"],
            source_status=detail_payload["source_status"],
            coverage_note=detail_payload["coverage_note"],
            tweets=detail_payload["tweets"],
        )

    @app.route("/a_share_matches/stock-analysis/<entity_type>/<identifier>")
    @login_required
    def a_share_matches_stock_analysis_detail(entity_type, identifier):
        display_name = str(request.args.get("display_name") or "").strip()
        company_name = str(request.args.get("company_name") or "").strip()
        exchange_name = str(request.args.get("exchange") or "").strip()
        market_name = str(request.args.get("market") or "").strip()
        numeric_code = str(request.args.get("numeric_code") or "").strip()

        chart_url = ""
        if entity_type == "match":
            chart_url = build_chart_url("a", identifier)
        elif entity_type == "project":
            chart_target = infer_project_chart_target(
                symbol=identifier,
                exchange=exchange_name,
                market_text=market_name,
                company_name=company_name,
            )
            chart_url = build_chart_url(
                chart_target.get("market", ""),
                chart_target.get("code", ""),
            )

        payload = build_stock_analysis_detail_payload(
            entity_type=entity_type,
            identifier=identifier,
            display_name=display_name,
            company_name=company_name,
            exchange=exchange_name,
            market=market_name,
            numeric_code=numeric_code,
            chart_url=chart_url,
        )
        if not payload.get("identifier"):
            abort(404)
        return render_template("a_share_match_stock_analysis.html", analysis=payload)

    @app.route("/ai-chat")
    @login_required
    def ai_chat():
        """
        AGI 对话页面
        """
        return render_template("ai_chat.html")

    @app.route("/tv/config")
    @login_required
    def tv_config():
        """
        配置项
        """
        frequencys = list(
            set(market_frequencys["a"])
            | set(market_frequencys["hk"])
            | set(market_frequencys["fx"])
            | set(market_frequencys["us"])
            | set(market_frequencys["futures"])
            | set(market_frequencys["currency"])
            | set(market_frequencys["currency_spot"])
        )
        supportedResolutions = [v for k, v in frequency_maps.items() if k in frequencys]
        return {
            "supports_search": True,
            "supports_group_request": False,
            "supported_resolutions": supportedResolutions,
            "supports_marks": True,
            "supports_timescale_marks": True,
            "supports_time": False,
            "exchanges": [
                {"value": "a", "name": "沪深", "desc": "沪深A股"},
                {"value": "hk", "name": "港股", "desc": "港股"},
                {"value": "fx", "name": "外汇", "desc": "外汇"},
                {"value": "us", "name": "美股", "desc": "美股"},
                {"value": "futures", "name": "国内期货", "desc": "国内期货"},
                {"value": "ny_futures", "name": "纽约期货", "desc": "纽约期货"},
                {
                    "value": "currency",
                    "name": "数字货币(Futures)",
                    "desc": "数字货币（合约）",
                },
                {
                    "value": "currency_spot",
                    "name": "数字货币(Spot)",
                    "desc": "数字货币（现货）",
                },
            ],
        }

    @app.route("/tv/symbol_info")
    @login_required
    def tv_symbol_info():
        """
        商品集合信息
        supports_search is True 则不会调用这个接口
        """
        group = request.args.get("group")
        ex = get_exchange(Market(group))
        all_symbols = ex.all_stocks()

        info = {
            "symbol": [s["code"] for s in all_symbols],
            "description": [s["name"] for s in all_symbols],
            "exchange-listed": group,
            "exchange-traded": group,
        }
        return info

    @app.route("/api/get_indicator_data", methods=['POST'])
    def get_indicator_data():
        """
        获取指标数据
        """
        # For now, just return some dummy data.
        # We can implement the real data fetching logic later.
        print('start1')
        return {"values": 1}


    @app.route("/tv/symbols")
    @login_required
    def tv_symbols():
        """
        商品解析
        """
        market, code = _parse_tv_symbol(request.args.get("symbol"))
        if market is None or code is None:
            return {"error": "invalid symbol"}, 400
        if market not in market_types:
            return {"error": "unsupported market"}, 404

        ex = get_exchange(Market(market))
        stocks = _resolve_tv_symbol_stock_info(ex, market, code)
        if stocks is None:
            return {"error": "symbol not found"}, 404

        sector = ""
        industry = ""
        if market == "a":
            try:
                gnbk = ex.stock_owner_plate(code)
                sector = " / ".join([_g["name"] for _g in gnbk["GN"]])
                industry = " / ".join([_h["name"] for _h in gnbk["HY"]])
            except Exception:
                pass

        info = {
            "name": stocks["code"],
            "ticker": f"{market}:{stocks['code']}",
            "full_name": f"{market}:{stocks['code']}",
            "description": stocks["name"],
            "exchange": market,
            "type": market_types[market],
            "session": market_session[market],
            "timezone": market_timezone[market],
            "pricescale": (
                stocks["precision"] if "precision" in stocks.keys() else 1000
            ),
            "visible_plots_set": "ohlcv",
            "supported_resolutions": [
                v for k, v in frequency_maps.items() if k in market_frequencys[market]
            ],
            "intraday_multipliers": [
                "1",
                "2",
                "3",
                "5",
                "10",
                "15",
                "20",
                "30",
                "60",
                "120",
                "240",
            ],
            "seconds_multipliers": [
                "1",
                "2",
                "3",
                "5",
                "10",
                "15",
                "20",
                "30",
                "40",
                "50",
                "60",
            ],
            "daily_multipliers": [
                "1",
                "2",
            ],
            "minmov": 1,
            "minmov2": 0,
            "has_intraday": True,
            "has_seconds": True if market in ["futures", "ny_futures"] else False,
            "has_daily": True,
            "has_weekly_and_monthly": True,
            "sector": sector,
            "industry": industry,
        }
        return info

    @app.route("/tv/search")
    @login_required
    def tv_search():
        """
        商品检索
        """
        query = request.args.get("query")
        type = request.args.get("type")
        exchange = request.args.get("exchange")
        limit = request.args.get("limit")

        ex = get_exchange(Market(exchange))
        all_stocks = ex.all_stocks()
        if exchange in ["currency", "currency_spot"]:
            res_stocks = [
                stock for stock in all_stocks if query.lower() in stock["code"].lower()
            ]
        else:
            res_stocks = [
                stock
                for stock in all_stocks
                if query.lower() in stock["code"].lower()
                or query.lower() in stock["name"].lower()
                or query.lower()
                in "".join([pinyin.get_initial(_p)[0] for _p in stock["name"]]).lower()
            ]
        res_stocks = res_stocks[0 : int(limit)]

        infos = []
        for stock in res_stocks:
            infos.append(
                {
                    "symbol": stock["code"],
                    "name": stock["code"],
                    "full_name": f"{exchange}:{stock['code']}",
                    "description": stock["name"],
                    "exchange": exchange,
                    "ticker": f"{exchange}:{stock['code']}",
                    "type": type,
                    "session": market_session[exchange],
                    "timezone": market_timezone[exchange],
                    "supported_resolutions": [
                        v
                        for k, v in frequency_maps.items()
                        if k in market_frequencys[exchange]
                    ],
                }
            )
        print('infos',infos)
        return infos

    @app.route("/tv/history")
    @login_required
    def tv_history():
        """
        K线柱
        """

        symbol = request.args.get("symbol")
        _from = request.args.get("from")
        _to = request.args.get("to")
        resolution = request.args.get("resolution")
        firstDataRequest = request.args.get("firstDataRequest", "false")

        _symbol_res_old_k_time_key = f"{symbol}_{resolution}"

        now_time = time.time()

        s = "ok"
        if int(_from) < 0 and int(_to) < 0:
            s = "no_data"

        if firstDataRequest == "false":
            # 判断在 5 秒内，同一个请求大于 5 次，返回 no_data
            if _symbol_res_old_k_time_key not in __history_req_counter.keys():
                __history_req_counter[_symbol_res_old_k_time_key] = {
                    "counter": 0,
                    "tm": now_time,
                }
            else:
                if __history_req_counter[_symbol_res_old_k_time_key]["counter"] >= 5:
                    __history_req_counter[_symbol_res_old_k_time_key] = {
                        "counter": 0,
                        "tm": now_time,
                    }
                    s = "no_data"
                elif (
                    now_time - __history_req_counter[_symbol_res_old_k_time_key]["tm"]
                    <= 5
                ):
                    __history_req_counter[_symbol_res_old_k_time_key]["counter"] += 1
                    __history_req_counter[_symbol_res_old_k_time_key]["tm"] = now_time
                else:
                    __history_req_counter[_symbol_res_old_k_time_key] = {
                        "counter": 0,
                        "tm": now_time,
                    }

        market = symbol.split(":")[0].lower()
        code = symbol.split(":")[1]

        ex = get_exchange(Market(market))

        # 判断当前是否可交易时间
        if firstDataRequest == "false" and ex.now_trading() is False:
            return {"s": "no_data", "nextTime": int(now_time + (10 * 60))}

        frequency = resolution_maps[resolution]
        lite_chart = is_lite_chart_request(request.args)
        cl_config = query_cl_chart_config(market, code)
        cl_config = apply_lite_chart_config_override(cl_config, lite_chart)
        frequency_low, kchart_to_frequency = kcharts_frequency_h_l_map(
            market, frequency
        )
        cache_key = build_tv_history_cache_key(
            symbol=symbol,
            resolution=resolution,
            config_payload={
                "cl_config": cl_config,
                "frequency_low": frequency_low,
                "kchart_to_frequency": kchart_to_frequency,
            },
        )
        cached_payload = __tv_history_cache.get(cache_key, now=now_time)
        if cached_payload is not None:
            cl_chart_data = cached_payload["cl_chart_data"]
            first_kline_time = int(cached_payload["first_kline_time"])
        elif (
            cl_config["enable_kchart_low_to_high"] == "1"
            and kchart_to_frequency is not None
        ):
            # 如果开启并设置的该级别的低级别数据，获取低级别数据，并在转换成高级图表展示
            # s_time = time.time()
            klines = ex.klines(code, frequency_low)
            # __log.info(f'{code} - {frequency_low} enable low to high get klines time : {time.time() - s_time}')
            # s_time = time.time()
            cd = web_batch_get_cl_datas(
                market, code, {frequency_low: klines}, cl_config
            )[0]
            # __log.info(f'{code} - {frequency_low} enable low to high get cd time : {time.time() - s_time}')
            first_kline_time = fun.datetime_to_int(klines.iloc[0]["date"])
            cl_chart_data = cl_data_to_tv_chart(
                cd, cl_config, to_frequency=kchart_to_frequency
            )
        else:
            kchart_to_frequency = None
            # s_time = time.time()
            klines = ex.klines(code, frequency)
            # __log.info(f'{code} - {frequency} get klines time : {time.time() - s_time}')
            # s_time = time.time()
            cd = web_batch_get_cl_datas(market, code, {frequency: klines}, cl_config)[0]
            # __log.info(f'{code} - {frequency} get cd time : {time.time() - s_time}')
            first_kline_time = fun.datetime_to_int(klines.iloc[0]["date"])
            cl_chart_data = cl_data_to_tv_chart(
                cd, cl_config, to_frequency=kchart_to_frequency
            )
            __tv_history_cache.set(
                cache_key,
                {
                    "cl_chart_data": cl_chart_data,
                    "first_kline_time": first_kline_time,
                },
                ttl_seconds=(10 if ex.now_trading() else 60),
                now=now_time,
            )

        if cached_payload is None and (
            cl_config["enable_kchart_low_to_high"] == "1"
            and kchart_to_frequency is not None
        ):
            __tv_history_cache.set(
                cache_key,
                {
                    "cl_chart_data": cl_chart_data,
                    "first_kline_time": first_kline_time,
                },
                ttl_seconds=(10 if ex.now_trading() else 60),
                now=now_time,
            )

        # 如果图表指定返回的时间太早，直接返回无数据
        if int(_to) < first_kline_time:
            return {"s": "no_data"}

        # 根据 from_time 和 to_time 来获取对应的K线数据
        if firstDataRequest == "false":
            _t = cl_chart_data["t"][-10:]
            _c = cl_chart_data["c"][-10:]
            _o = cl_chart_data["o"][-10:]
            _h = cl_chart_data["h"][-10:]
            _l = cl_chart_data["l"][-10:]
            _v = cl_chart_data["v"][-10:]
            _fxs = cl_chart_data["fxs"][-5:]
            _bis = cl_chart_data["bis"][-5:]
            _xds = cl_chart_data["xds"][-5:]
            _zsds = cl_chart_data["zsds"][-5:]
            _bi_zss = cl_chart_data["bi_zss"][-5:]
            _xd_zss = cl_chart_data["xd_zss"][-5:]
            _zsd_zss = cl_chart_data["zsd_zss"][-5:]
            _bcs = cl_chart_data["bcs"][-5:]
            _mmds = cl_chart_data["mmds"][-5:]
        else:
            _t = cl_chart_data["t"]
            _c = cl_chart_data["c"]
            _o = cl_chart_data["o"]
            _h = cl_chart_data["h"]
            _l = cl_chart_data["l"]
            _v = cl_chart_data["v"]
            _fxs = cl_chart_data["fxs"]
            _bis = cl_chart_data["bis"]
            _xds = cl_chart_data["xds"]
            _zsds = cl_chart_data["zsds"]
            _bi_zss = cl_chart_data["bi_zss"]
            _xd_zss = cl_chart_data["xd_zss"]
            _zsd_zss = cl_chart_data["zsd_zss"]
            _bcs = cl_chart_data["bcs"]
            _mmds = cl_chart_data["mmds"]

        info = {
            "s": s,
            "t": _t,
            "c": _c,
            "o": _o,
            "h": _h,
            "l": _l,
            "v": _v,
            "fxs": _fxs,
            "bis": _bis,
            "xds": _xds,
            "zsds": _zsds,
            "bi_zss": _bi_zss,
            "xd_zss": _xd_zss,
            "zsd_zss": _zsd_zss,
            "bcs": _bcs,
            "mmds": _mmds,
            "update": (
                False if firstDataRequest == "true" else True
            ),  # 是否是后续更新数据
        }
        return info

    @app.route("/tv/timescale_marks")
    @login_required
    def tv_timescale_marks():
        symbol = request.args.get("symbol")
        _from = int(request.args.get("from"))
        _to = int(request.args.get("to"))
        resolution = request.args.get("resolution")
        market = symbol.split(":")[0]
        code = symbol.split(":")[1]

        freq = resolution_maps[resolution]

        order_type_maps = {
            "buy": "买入",
            "sell": "卖出",
            "open_long": "买入开多",
            "open_short": "买入开空",
            "close_long": "卖出平多",
            "close_short": "买入平空",
        }
        marks = []

        # 增加订单的信息
        orders = db.order_query_by_code(market, code)
        for i in range(len(orders)):
            o = orders[i]
            _dt_int = fun.datetime_to_int(o["datetime"])
            if _from <= _dt_int <= _to:
                m = {
                    "id": i,
                    "time": _dt_int,
                    "color": (
                        "red"
                        if o["type"] in ["buy", "open_long", "close_short"]
                        else "green"
                    ),
                    "label": (
                        "B" if o["type"] in ["buy", "open_long", "close_short"] else "S"
                    ),
                    "tooltip": [
                        f"{order_type_maps[o['type']]}[{o['price']}/{o['amount']}]",
                        f"{'' if 'info' not in o else o['info']}",
                    ],
                    "shape": (
                        "earningUp"
                        if o["type"] in ["buy", "open_long", "close_short"]
                        else "earningDown"
                    ),
                }
                marks.append(m)

        # 增加其他自定义信息
        other_marks = db.marks_query(market, code)
        for i in range(len(other_marks)):
            _m = other_marks[i]
            if _m.frequency == "" or _m.frequency == freq:
                if _from <= _m.mark_time <= _to:
                    marks.append(
                        {
                            "id": f"m-{i}",
                            "time": int(_m.mark_time),
                            "color": _m.mark_color,
                            "label": _m.mark_label,
                            "tooltip": _m.mark_tooltip,
                            "shape": _m.mark_shape,
                        }
                    )

        return marks

    @app.route("/tv/marks")
    @login_required
    def tv_marks():
        symbol = request.args.get("symbol")
        _from = int(request.args.get("from"))
        _to = int(request.args.get("to"))
        resolution = request.args.get("resolution")
        market = symbol.split(":")[0]
        code = symbol.split(":")[1]

        freq = resolution_maps[resolution]

        marks = []
        price_marks = db.marks_query_by_price(market, code, start_date=_from)
        for i in range(len(price_marks)):
            _m = price_marks[i]
            if _m.frequency == "" or _m.frequency == freq:
                if _from <= _m.mark_time <= _to:
                    marks.append(
                        {
                            "id": f"m-{i}",
                            "time": int(_m.mark_time),
                            "color": _m.mark_color,
                            "text": _m.mark_text,
                            "label": _m.mark_label,
                            "labelFontColor": _m.mark_label_font_color,
                            "minSize": _m.mark_min_size,
                        }
                    )

        return marks

    @app.route("/tv/del_marks", methods=["POST"])
    @login_required
    def tv_del_marks():
        symbol = request.form["symbol"]
        market = symbol.split(":")[0]
        code = symbol.split(":")[1]

        db.marks_del_all_by_code(market, code)

        return {"status": "ok"}

    @app.route("/tv/time")
    @login_required
    def tv_time():
        """
        服务器时间
        """
        return fun.datetime_to_int(datetime.datetime.now())

    @app.route("/tv/<version>/charts", methods=["GET", "POST", "DELETE"])
    @login_required
    def tv_charts(version):
        """
        图表
        """
        client_id = str(request.args.get("client"))
        user_id = str(request.args.get("user"))

        if request.method == "GET":
            chart_id = request.args.get("chart")
            if chart_id is None:
                # 列出保存的图表列表
                chart_list = db.tv_chart_list("chart", client_id, user_id)
                return {
                    "status": "ok",
                    "data": [
                        {
                            "timestamp": c.timestamp,
                            "symbol": c.symbol,
                            "resolution": c.resolution,
                            "id": c.id,
                            "name": c.name,
                        }
                        for c in chart_list
                    ],
                }
            else:
                # 获取图表信息
                chart = db.tv_chart_get("chart", chart_id, client_id, user_id)
                return {
                    "status": "ok",
                    "data": {
                        "content": chart.content,
                        "timestamp": chart.timestamp,
                        "name": chart.name,
                        "id": chart.id,
                    },
                }
        elif request.method == "DELETE":
            # 删除操作
            chart_id = request.args.get("chart")
            db.tv_chart_del("chart", chart_id, client_id, user_id)
            return {
                "status": "ok",
            }
        else:
            # 更新与保存操作
            name = request.form["name"]
            content = request.form["content"]
            symbol = request.form["symbol"]
            resolution = request.form["resolution"]
            chart_id = request.args.get("chart")

            if chart_id is None:
                # 保存新的图表信息
                id = db.tv_chart_save(
                    "chart", client_id, user_id, name, content, symbol, resolution
                )
                return {
                    "status": "ok",
                    "id": id,
                }
            else:
                # 保存已有的图表信息
                db.tv_chart_update(
                    "chart",
                    chart_id,
                    client_id,
                    user_id,
                    name,
                    content,
                    symbol,
                    resolution,
                )
                return {"status": "ok"}

    @app.route("/tv/<version>/study_templates", methods=["GET", "POST", "DELETE"])
    @login_required
    def tv_study_templates(version):
        """
        图表
        """
        client_id = str(request.args.get("client"))
        user_id = str(request.args.get("user"))

        if request.method == "GET":
            template = request.args.get("template")
            if template is None:
                # 列出保存的图表列表
                template_list = db.tv_chart_list("template", client_id, user_id)
                return {
                    "status": "ok",
                    "data": [{"name": t.name} for t in template_list],
                }
            else:
                # 获取图表信息
                template = db.tv_chart_get_by_name(
                    "template", template, client_id, user_id
                )
                return {
                    "status": "ok",
                    "data": {"name": template.name, "content": template.content},
                }
        elif request.method == "DELETE":
            # 删除操作
            name = request.args.get("template")
            db.tv_chart_del_by_name("template", name, client_id, user_id)
            return {
                "status": "ok",
            }
        else:
            name = request.form["name"]
            content = request.form["content"]

            # 保存图表信息
            db.tv_chart_save("template", client_id, user_id, name, content, "", "")
            return {"status": "ok"}

    @app.route("/tv/<version>/drawings", methods=["GET", "POST"])
    @login_required
    def tv_drawings(version):
        """
        图表绘图保存与加载 TODO TV 库报错，暂时不用
        """
        client_id = str(request.args.get("client"))
        user_id = str(request.args.get("user"))
        chart_id = request.args.get("chart")
        layout_id = request.args.get("layout")

        print(
            f"{request.method} client_id={client_id}, user_id={user_id}, chart_id={chart_id}, layout_id={layout_id}"
        )

        if request.method == "GET":
            return {
                "status": "ok",
                "data": {},
            }
        else:
            # 更新与保存操作
            return {"status": "ok"}

    # 查询配置项
    @app.route("/get_cl_config/<market>/<code>")
    @login_required
    def get_cl_config(market, code: str):
        code = code.replace("__", "/")  # 数字货币特殊处理
        cl_config = query_cl_chart_config(market, code)
        cl_config["market"] = market
        cl_config["code"] = code
        return render_template("options.html", **cl_config)

    # 设置配置项
    @app.route("/set_cl_config", methods=["POST"])
    @login_required
    def set_cl_config():
        market = request.form["market"]
        code = request.form["code"]
        is_del = request.form["is_del"]
        if is_del == "true":
            res = del_cl_chart_config(market, code)
            return {"ok": res}

        keys = [
            "config_use_type",
            # 个人定制配置
            "kline_qk",
            "judge_zs_qs_level",
            # K线配置
            "kline_type",
            # 分型配置
            "fx_qy",
            "fx_qj",
            "fx_bh",
            # 笔配置
            "bi_type",
            "bi_bzh",
            "bi_qj",
            "bi_fx_cgd",
            "bi_split_k_cross_nums",
            "fx_check_k_nums",
            "allow_bi_fx_strict",
            # 线段配置
            "xd_qj",
            "zsd_qj",
            "xd_zs_max_lines_split",
            "xd_allow_bi_pohuai",
            "xd_allow_split_no_highlow",
            "xd_allow_split_zs_kz",
            "xd_allow_split_zs_more_line",
            "xd_allow_split_zs_no_direction",
            # 中枢配置
            "zs_bi_type",
            "zs_xd_type",
            "zs_qj",
            "zs_cd",
            "zs_wzgx",
            # MACD 配置（计算力度背驰）
            "idx_macd_fast",
            "idx_macd_slow",
            "idx_macd_signal",
            # 买卖点计算
            "cl_mmd_cal_qs_1mmd",
            "cl_mmd_cal_not_qs_3mmd_1mmd",
            "cl_mmd_cal_qs_3mmd_1mmd",
            "cl_mmd_cal_qs_not_lh_2mmd",
            "cl_mmd_cal_qs_bc_2mmd",
            "cl_mmd_cal_3mmd_not_lh_bc_2mmd",
            "cl_mmd_cal_1mmd_not_lh_2mmd",
            "cl_mmd_cal_3mmd_xgxd_not_bc_2mmd",
            "cl_mmd_cal_not_in_zs_3mmd",
            "cl_mmd_cal_not_in_zs_gt_9_3mmd",
            # 画图配置
            "enable_kchart_low_to_high",
            "chart_show_fx",
            "chart_show_bi",
            "chart_show_xd",
            "chart_show_zsd",
            "chart_show_qsd",
            "chart_show_bi_zs",
            "chart_show_xd_zs",
            "chart_show_zsd_zs",
            "chart_show_qsd_zs",
            "chart_show_bi_mmd",
            "chart_show_xd_mmd",
            "chart_show_zsd_mmd",
            "chart_show_qsd_mmd",
            "chart_show_bi_bc",
            "chart_show_xd_bc",
            "chart_show_zsd_bc",
            "chart_show_qsd_bc",
        ]
        cl_config = {}
        for _k in keys:
            cl_config[_k] = request.form[_k]
            if _k in ["zs_bi_type", "zs_xd_type"]:
                cl_config[_k] = cl_config[_k].split(",")
            if cl_config[_k] == "":
                cl_config[_k] = "0"
            # print(f"{_k} : {cl_config[_k]}")

        res = set_cl_chart_config(market, code, cl_config)
        return {"ok": res}

    # 股票涨跌幅
    @app.route("/ticks", methods=["POST"])
    @login_required
    def ticks():
        market = request.form["market"]
        codes = request.form["codes"]
        codes = normalize_market_codes(market, json.loads(codes))
        ex = get_exchange(Market(market))
        try:
            snapshots = fetch_tick_snapshots(ex, codes)

            now_trading = ex.now_trading()
            res_ticks = list(snapshots.values())
            return {"now_trading": now_trading, "ticks": res_ticks}
        except Exception:
            traceback.print_exc()
        return {"now_trading": False, "ticks": []}

    # 获取自选组列表
    @app.route("/get_zixuan_groups/<market>")
    @login_required
    def get_zixuan_groups(market):
        zx = ZiXuan(market)
        groups = zx.get_zx_groups()
        return groups

    # 获取自选组的股票
    @app.route("/get_zixuan_stocks/<market>/<group_name>")
    @login_required
    def get_zixuan_stocks(market, group_name):
        zx = ZiXuan(market)
        stock_list = zx.zx_stocks(group_name)
        return {"code": 0, "msg": "", "count": len(stock_list), "data": stock_list}

    @app.route("/get_stock_zixuan/<market>/<code>")
    @login_required
    def get_stock_zixuan(market, code: str):
        code = code.replace("__", "/")  # 数字货币特殊处理
        zx = ZiXuan(market)
        zx_groups = zx.query_code_zx_names(code)
        return zx_groups

    @app.route("/zixuan_group/<market>", methods=["GET"])
    @login_required
    def zixuan_group_view(market):
        zx = ZiXuan(market)
        zx_groups = zx.get_zx_groups()
        return render_template("zixuan.html", market=market, zx_groups=zx_groups)

    @app.route("/opt_zixuan_group/<market>", methods=["POST"])
    @login_required
    def opt_zixuan_group(market):
        """
        操作自选组
        """
        opt = request.form["opt"]
        zx_group = request.form["zx_group"]
        zx = ZiXuan(market)
        if opt == "DEL":
            return {"ok": zx.del_zx_group(zx_group)}
        else:
            return {"ok": zx.add_zx_group(zx_group)}

    @app.route("/zixuan_opt_export", methods=["GET"])
    @login_required
    def opt_zixuan_export():
        """
        导出自选组
        """
        market = request.args.get("market")
        zx_group = request.args.get("zx_group")
        zx = ZiXuan(market)
        stock_list = zx.zx_stocks(zx_group)
        output = ""
        for s in stock_list:
            output += f"{s['code']},{s['name']}\n"
        try:
            down_file = get_data_path() / "zx.txt"
            down_file.write_text(output, encoding="utf-8")
            return send_file(
                down_file, as_attachment=True, download_name=f"zixuan_{zx_group}.txt"
            )
        finally:
            try:
                os.remove(down_file)
            except Exception:
                pass

    @app.route("/zixuan_opt_import", methods=["POST"])
    @login_required
    def opt_zixuan_import():
        """
        导入自选
        """
        market = request.form["market"]
        zx_group = request.form["zx_group"]
        file = request.files["file"]
        import_file = get_data_path() / "zx.txt"
        file.save(import_file)
        zx = ZiXuan(market)
        ex = get_exchange(Market(market))
        import_nums = 0
        market_all_stocks = ex.all_stocks()
        market_all_codes = [s["code"] for s in market_all_stocks]
        with open(import_file, "r", encoding="utf-8") as fp:
            for line in fp.readlines():
                try:
                    import_infos = line.strip().split(",")
                    if len(import_infos) >= 2:
                        code = import_infos[0].strip()
                        name = import_infos[1].strip()
                    else:
                        code = import_infos[0].strip()
                        name = None

                    # 股票代码兼容性处理
                    if market == "a":
                        code = code.replace("SHSE.", "SH.").replace("SZSE.", "SZ.")

                    if code not in market_all_codes:
                        same_codes = [_c for _c in market_all_codes if code in _c]
                        if len(same_codes) == 1:
                            code = same_codes[0]
                        else:
                            continue

                    zx.add_stock(zx_group, code, name)
                    import_nums += 1
                except Exception as e:
                    print(line, e)

        try:
            os.remove(import_file)
        except Exception:
            pass

        return {"ok": True, "msg": f"成功导入 {import_nums} 条记录"}

    # 设置股票的自选组
    @app.route("/set_stock_zixuan", methods=["POST"])
    @login_required
    def set_stock_zixuan():
        market = request.form["market"]
        opt = request.form["opt"]
        group_name = request.form["group_name"]
        code = request.form["code"]
        zx = ZiXuan(market)
        if opt == "DEL":
            res = zx.del_stock(group_name, code)
        elif opt == "ADD":
            res = zx.add_stock(group_name, code, None)
        elif opt == "COLOR":
            color = request.form["color"]
            res = zx.color_stock(group_name, code, color)
        elif opt == "SORT":
            direction = request.form["direction"]
            if direction == "top":
                res = zx.sort_top_stock(group_name, code)
            else:
                res = zx.sort_bottom_stock(group_name, code)
        else:
            res = False

        return {"ok": res}

    # 警报提醒列表
    @app.route("/alert_list/<market>")
    @login_required
    def alert_list(market):
        al = _alert_tasks.task_list(market)
        al = [
            {
                "id": _l.id,
                "market": _l.market,
                "task_name": _l.task_name,
                "zx_group": _l.zx_group,
                "interval_minutes": _l.interval_minutes,
                "frequency": _l.frequency,
                "check_bi_type": _l.check_bi_type,
                "check_bi_beichi": _l.check_bi_beichi,
                "check_bi_mmd": _l.check_bi_mmd,
                "check_xd_type": _l.check_xd_type,
                "check_xd_beichi": _l.check_xd_beichi,
                "check_xd_mmd": _l.check_xd_mmd,
                "check_idx_ma_info": _l.check_idx_ma_info,
                "check_idx_macd_info": _l.check_idx_macd_info,
                "is_send_msg": _l.is_send_msg,
                "is_run": _l.is_run,
            }
            for _l in al
        ]
        return {"code": 0, "msg": "", "count": len(al), "data": al}

    # 警报编辑页面
    @app.route("/alert_edit/<market>/<id>")
    @login_required
    def alert_edit(market, id):
        alert_config = {
            "id": "",
            "market": market,
            "task_name": "",
            "zx_group": "我的关注",
            "interval_minutes": 5,
            "frequency": "5m",
            "check_bi_type": "up,down",
            "check_bi_beichi": "pz,qs",
            "check_bi_mmd": "",
            "check_xd_type": "up,down",
            "check_xd_beichi": "pz,qs",
            "check_xd_mmd": "",
            "check_idx_ma_info_enable": 0,
            "check_idx_ma_info_slow": 10,
            "check_idx_ma_info_fast": 5,
            "check_idx_ma_info_cross_up": 0,
            "check_idx_ma_info_cross_down": 0,
            "check_idx_macd_info_enable": 0,
            "check_idx_macd_info_cross_up": 0,
            "check_idx_macd_info_cross_down": 0,
            "is_send_msg": 1,
            "is_run": 1,
        }
        if id != "0":
            _alert_config = _alert_tasks.alert_get(id)
            if _alert_config is not None:
                check_idx_ma_info = (
                    json.loads(_alert_config.check_idx_ma_info)
                    if _alert_config.check_idx_ma_info
                    else {
                        "enable": 0,
                        "slow": 10,
                        "fast": 5,
                        "cross_up": 0,
                        "cross_down": 0,
                    }
                )
                check_idx_macd_info = (
                    json.loads(_alert_config.check_idx_macd_info)
                    if _alert_config.check_idx_macd_info
                    else {
                        "enable": 0,
                        "cross_up": 0,
                        "cross_down": 0,
                    }
                )
                alert_config = {
                    "id": _alert_config.id,
                    "market": _alert_config.market,
                    "task_name": _alert_config.task_name,
                    "zx_group": _alert_config.zx_group,
                    "interval_minutes": _alert_config.interval_minutes,
                    "frequency": _alert_config.frequency,
                    "check_bi_type": _alert_config.check_bi_type,
                    "check_bi_beichi": _alert_config.check_bi_beichi,
                    "check_bi_mmd": _alert_config.check_bi_mmd,
                    "check_xd_type": _alert_config.check_xd_type,
                    "check_xd_beichi": _alert_config.check_xd_beichi,
                    "check_xd_mmd": _alert_config.check_xd_mmd,
                    "check_idx_ma_info_enable": check_idx_ma_info["enable"],
                    "check_idx_ma_info_slow": check_idx_ma_info["slow"],
                    "check_idx_ma_info_fast": check_idx_ma_info["fast"],
                    "check_idx_ma_info_cross_up": check_idx_ma_info["cross_up"],
                    "check_idx_ma_info_cross_down": check_idx_ma_info["cross_down"],
                    "check_idx_macd_info_enable": check_idx_macd_info["enable"],
                    "check_idx_macd_info_cross_up": check_idx_macd_info["cross_up"],
                    "check_idx_macd_info_cross_down": check_idx_macd_info["cross_down"],
                    "is_send_msg": _alert_config.is_send_msg,
                    "is_run": _alert_config.is_run,
                }

        # 获取自选组
        zx = ZiXuan(market)
        zixuan_groups = zx.zixuan_list

        # 交易所支持周期
        frequencys = get_exchange(Market(market)).support_frequencys()

        return render_template(
            "alert.html",
            zixuan_groups=zixuan_groups,
            frequencys=frequencys,
            **alert_config,
        )

    @app.route("/alert_save", methods=["POST"])
    @login_required
    def alert_save():
        check_idx_ma_infos = json.dumps(
            {
                "enable": (
                    int(request.form["check_idx_ma_info_enable"])
                    if request.form["check_idx_ma_info_enable"]
                    else 0
                ),
                "slow": (
                    int(request.form["check_idx_ma_info_slow"])
                    if request.form["check_idx_ma_info_slow"]
                    else 0
                ),
                "fast": (
                    int(request.form["check_idx_ma_info_fast"])
                    if request.form["check_idx_ma_info_fast"]
                    else 0
                ),
                "cross_up": (
                    int(request.form["check_idx_ma_info_cross_up"])
                    if request.form["check_idx_ma_info_cross_up"]
                    else 0
                ),
                "cross_down": (
                    int(request.form["check_idx_ma_info_cross_down"])
                    if request.form["check_idx_ma_info_cross_down"]
                    else 0
                ),
            }
        )
        check_idx_macd_infos = json.dumps(
            {
                "enable": (
                    int(request.form["check_idx_macd_info_enable"])
                    if request.form["check_idx_macd_info_enable"]
                    else 0
                ),
                "cross_up": (
                    int(request.form["check_idx_macd_info_cross_up"])
                    if request.form["check_idx_macd_info_cross_up"]
                    else 0
                ),
                "cross_down": (
                    int(request.form["check_idx_macd_info_cross_down"])
                    if request.form["check_idx_macd_info_cross_down"]
                    else 0
                ),
            }
        )
        alert_config = {
            "id": request.form["id"],
            "market": request.form["market"],
            "task_name": request.form["task_name"],
            "interval_minutes": int(request.form["interval_minutes"]),
            "zx_group": request.form["zx_group"],
            "frequency": request.form["frequency"],
            "check_bi_type": request.form["check_bi_type"],
            "check_bi_beichi": request.form["check_bi_beichi"],
            "check_bi_mmd": request.form["check_bi_mmd"],
            "check_xd_type": request.form["check_xd_type"],
            "check_xd_beichi": request.form["check_xd_beichi"],
            "check_xd_mmd": request.form["check_xd_mmd"],
            "check_idx_ma_info": check_idx_ma_infos,
            "check_idx_macd_info": check_idx_macd_infos,
            "is_send_msg": int(request.form["is_send_msg"]),
            "is_run": int(request.form["is_run"]),
        }
        _alert_tasks.alert_save(alert_config)
        return {"ok": True}

    @app.route("/alert_del/<id>")
    @login_required
    def alert_del(id):
        res = _alert_tasks.alert_del(id)
        return {"ok": res}

    @app.route("/alert_records/<market>")
    @login_required
    def alert_records(market):
        task_name = request.args.get("task_name")
        records = db.alert_record_query(market, task_name)
        rls = [
            {
                "code": _r.stock_code,
                "name": _r.stock_name,
                "frequency": _r.frequency,
                "line_type": _r.line_type,
                "msg": _r.alert_msg,
                "is_done": _r.bi_is_done,
                "is_td": _r.bi_is_td,
                "task_name": _r.task_name,
                "datetime_str": fun.datetime_to_str(_r.alert_dt),
            }
            for _r in records
        ]
        return {
            "code": 0,
            "msg": "",
            "count": len(rls),
            "data": rls,
        }

    @app.route("/jobs")
    @login_required
    def jobs():
        return render_template("jobs.html", jobs=list(scheduler.my_task_list.values()))

    @app.route("/xuangu/task_list/<market>")
    @login_required
    def xuangu_task_list(market):
        # 获取自选组
        zx = ZiXuan(market)
        zixuan_groups = zx.zixuan_list

        # 交易所支持周期
        frequencys = get_exchange(Market(market)).support_frequencys()

        # 选股配置
        xuangu_task_list = _xuangu_tasks.xuangu_task_config_list()

        # task_memo
        task_infos = {
            _k: {
                "task_memo": _v["task_memo"],
                "frequency_memo": _v["frequency_memo"],
            }
            for _k, _v in xuangu_task_list.items()
        }

        return render_template(
            "xuangu_list.html",
            market=market,
            tasks=xuangu_task_list,
            task_infos=task_infos,
            zixuan_groups=zixuan_groups,
            frequencys=frequencys,
        )

    @app.route("/xuangu/task_add", methods=["POST"])
    @login_required
    def xuangu_task_add():
        market = request.form["market"]
        task_name = request.form["task_name"]
        frequencys = request.form["frequencys"]
        zx_group = request.form["zx_group"]
        opt_type = request.form["opt_type"]

        frequencys = frequencys.split(",")
        opt_type = opt_type.split(",")

        if task_name not in _xuangu_tasks.xuangu_task_config_list().keys():
            return {"ok": False, "msg": "选股任务不存在"}

        allow_freq_num = _xuangu_tasks.xuangu_task_config_list()[task_name][
            "frequency_num"
        ]
        if len(frequencys) != allow_freq_num:
            return {
                "ok": False,
                "msg": f"选股周期错误，该任务可选周期数量 : {allow_freq_num}",
            }

        run_res = _xuangu_tasks.run_xuangu(
            market, task_name, frequencys, opt_type, zx_group
        )

        return {
            "ok": run_res,
            "msg": "选股任务已存在，请在当前任务中查看任务" if run_res is False else "",
        }

    @app.route("/setting", methods=["GET"])
    @login_required
    def setting():
        # 查询配置
        proxy = db.cache_get("req_proxy")
        fs_setting = db.cache_get("fs_keys")
        set_config = {
            "fs_app_id": fs_setting["fs_app_id"] if fs_setting is not None else "",
            "fs_app_secret": (
                fs_setting["fs_app_secret"] if fs_setting is not None else ""
            ),
            "fs_user_id": fs_setting["fs_user_id"] if fs_setting is not None else "",
            "proxy_host": proxy["host"] if proxy is not None else "",
            "proxy_port": proxy["port"] if proxy is not None else "",
        }
        return render_template("setting.html", **set_config)

    @app.route("/setting/save", methods=["POST"])
    @login_required
    def setting_save():
        proxy = {
            "host": request.form["proxy_host"],
            "port": request.form["proxy_port"],
        }
        fs_keys = {
            "fs_app_id": request.form["fs_app_id"],
            "fs_app_secret": request.form["fs_app_secret"],
            "fs_user_id": request.form["fs_user_id"],
        }
        db.cache_set("req_proxy", proxy)
        db.cache_set("fs_keys", fs_keys)

        return {"ok": True}

    @app.route("/ai/analyse", methods=["POST"])
    @login_required
    def ai_analyse():
        market = request.form["market"]
        code = request.form["code"]
        frequency = request.form["frequency"]

        ai_analyse_obj = AIAnalyse(market)
        ai_res = ai_analyse_obj.analyse(code, frequency)

        return ai_res

    @app.route("/ai/analyse_records/<market>", methods=["GET"])
    @login_required
    def ai_analyse_records(market: str = "a"):
        ai_analyse_records = AIAnalyse(market=market).analyse_records(30)
        return {
            "code": 0,
            "msg": "",
            "count": len(ai_analyse_records),
            "data": ai_analyse_records,
        }

    @app.route("/a/bkgn_list", methods=["GET"])
    @login_required
    def a_bkgn_list():
        """
        获取沪深a股市场的板块列表
        """
        stock_bkgn = StocksBKGN()
        bkgn_infos = stock_bkgn.file_bkgns()
        all_hy_names = bkgn_infos["hys"]
        all_gn_names = bkgn_infos["gns"]

        res_bkgn_list = []
        for _hy in all_hy_names:
            res_bkgn_list.append(
                {
                    "type": "hy",
                    "bkgn_name": f"行业:{_hy}",
                    "bkgn_code": _hy,
                }
            )
        for _gn in all_gn_names:
            res_bkgn_list.append(
                {
                    "type": "gn",
                    "bkgn_name": f"概念:{_gn}",
                    "bkgn_code": _gn,
                }
            )
        return {
            "code": 0,
            "msg": "",
            "data": res_bkgn_list,
            "count": len(res_bkgn_list),
        }

    @app.route("/a/bkgn_codes", methods=["POST"])
    @login_required
    def a_bkgn_codes():
        bkgn_type = request.form["bkgn_type"]
        bkgn_code = request.form["bkgn_code"]
        stock_bkgn = StocksBKGN()

        if bkgn_type == "hy":
            codes = stock_bkgn.ths_to_tdx_codes(stock_bkgn.get_codes_by_hy(bkgn_code))
        elif bkgn_type == "gn":
            codes = stock_bkgn.ths_to_tdx_codes(stock_bkgn.get_codes_by_gn(bkgn_code))
        else:
            codes = []

        ex = get_exchange(Market.A)
        stocks = {}
        for _code in codes:
            _stock = ex.stock_info(_code)
            if _stock is not None:
                stocks[_code] = _stock

        return {"code": 0, "msg": "", "data": stocks, "count": len(stocks)}
    from .news_vector_db import NewsVectorDB
    
    def convert_db_news_to_vector_format(db_news) -> dict:
        """
        将关系数据库的新闻记录转换为向量数据库格式
        
        Args:
            db_news: 关系数据库新闻记录 (TableByNews对象)
        
        Returns:
            dict: 向量数据库格式的新闻数据
        """
        return {
            'news_id': str(db_news.news_id) if db_news.news_id else str(db_news.id),
            'title': db_news.title or '',
            'body': db_news.body or '',
            'source': db_news.source or '',
            'published_at': db_news.published_at,
            'language': db_news.language or 'zh',
            'category': db_news.category or '',
            'sentiment_score': float(db_news.sentiment_score or 0.0),
            'importance_score': float(db_news.importance_score or 0.5)
        }
    @app.route("/api/news", methods=["POST"])
    @login_required
    def receive_news():
        """
        接收新闻数据的API接口
        接受POST请求，处理单条或多条新闻数据，并存储到向量数据库
        支持格式：
        1. 单条新闻：{"title": "...", "body": "...", ...}
        2. 多条新闻：[{"title": "...", "body": "..."}, {...}]
        """
        from .news_vector_db import get_vector_db
        
        print('start get post')
        # try:
            # 获取POST请求的JSON数据
        if request.is_json:
            raw_data = request.get_json()
        else:
            # 如果不是JSON格式，尝试从form数据获取
            raw_data = request.form.to_dict()
        
        # 判断是单条数据还是多条数据
        if isinstance(raw_data, list):
            news_data_list = raw_data
        else:
            news_data_list = [raw_data]
        
        # 验证必要字段
        required_fields = ['title', 'body', 'source', 'published_at']
        for i, news_data in enumerate(news_data_list):
            for field in required_fields:
                if field not in news_data:
                    return {
                        "code": 400,
                        "msg": f"第{i+1}条新闻缺少必要字段: {field}",
                        "data": None
                    }
        
        # 批量处理新闻数据
        processed_news = []
        total_success = 0
        total_db_success = 0
        total_vector_success = 0
        
        # 获取向量数据库实例
        vector_db = get_vector_db()
        print('len(news_data_list)', len(news_data_list))

        for i, news_data in enumerate(news_data_list):
            try:
                # 处理发布时间格式 - 统一转换为中国时区
                published_at_str = NewsVectorDB.normalize_datetime(news_data.get('published_at'))
                print(f'第{i+1}条新闻 - 原published_at', news_data.get('published_at'))
                print(f'第{i+1}条新闻 - published_at_str', published_at_str)
                
                # 将标准化后的ISO字符串转换为datetime对象用于数据库存储
                try:
                    published_at = datetime.datetime.fromisoformat(published_at_str)
                except ValueError:
                    # 如果转换失败，使用当前中国时间
                    import pytz
                    china_tz = pytz.timezone('Asia/Shanghai')
                    published_at = datetime.datetime.now(china_tz)
                
                # 构建新闻数据库存储结构
                sentiment_score = news_data.get('sentiment_score', 0)
                importance_score = news_data.get('importance_score', 0)
                
                print(f'第{i+1}条新闻 - published_at', published_at)
                news_db_data = {
                    'news_id': str(news_data.get('id', int(time.time() * 1000) + i)),
                    'story_id': news_data.get('story_id'),
                    'title': news_data.get('title'),
                    'body': news_data.get('body'),
                    'source': news_data.get('source'),
                    'published_at': published_at,
                    'language': news_data.get('language', 'zh'),
                    'category': news_data.get('category'),
                    'tags': news_data.get('tags'),
                    'sentiment_score': sentiment_score,
                    'importance_score': importance_score
                }
                
                # 保存新闻数据到关系数据库
                db_save_success = False
                try:
                    db.news_insert(news_db_data)
                    db.news_asset_links_replace(
                        news_db_data["news_id"],
                        build_asset_link_rows(
                            news_id=news_db_data["news_id"],
                            title=news_db_data["title"],
                            body=news_db_data["body"],
                            product_info=news_data.get("product_info"),
                            product_code=news_data.get("product_code"),
                        ),
                    )
                    __log.info(f"第{i+1}条新闻数据已保存到关系数据库: {news_db_data['title']}")
                    db_save_success = True
                    total_db_success += 1
                except Exception as db_error:
                    __log.error(f"第{i+1}条新闻保存到关系数据库失败: {str(db_error)}")
                
                # 保存新闻数据到向量数据库
                vector_save_success = False
                try:
                    # 添加到向量数据库
                    vector_save_success = vector_db.add_news(news_db_data)
                    
                    if vector_save_success:
                        __log.info(f"第{i+1}条新闻数据已保存到向量数据库: {news_db_data['title']}")
                        total_vector_success += 1
                    else:
                        __log.warning(f"第{i+1}条新闻数据保存到向量数据库失败: {news_db_data['title']}")
                        
                except Exception as vector_error:
                    __log.error(f"第{i+1}条新闻保存到向量数据库时发生异常: {str(vector_error)}")
                
                # 构建返回的新闻项目数据结构
                news_item = {
                    'id': news_db_data['news_id'],
                    'story_id': news_db_data['story_id'],
                    'title': news_db_data['title'],
                    'body': news_db_data['body'],
                    'source': news_db_data['source'],
                    'published_at': published_at.isoformat() if published_at else None,
                    'language': news_db_data['language'],
                    'category': news_db_data['category'],
                    'tags': news_db_data['tags'],
                    'sentiment_score': news_db_data['sentiment_score'],
                    'importance_score': news_db_data['importance_score'],
                    'created_at': datetime.datetime.now().isoformat(),
                    'db_saved': db_save_success,
                    'vector_saved': vector_save_success
                }
                
                processed_news.append(news_item)
                if db_save_success or vector_save_success:
                    total_success += 1
                
                __log.info(f"第{i+1}条新闻处理完成: {news_item['title']}")
                
            except Exception as e:
                __log.error(f"处理第{i+1}条新闻时发生错误: {str(e)}")
                # 继续处理下一条新闻
                continue
        
        # 可以在这里调用新闻分析功能
        # 例如：使用AI增强分析功能对新闻进行分析
        
        return {
            "code": 0,
            "msg": f"批量新闻数据接收完成，共处理{len(news_data_list)}条，成功{total_success}条",
            "data": {
                "received_news": processed_news,
                "processed_at": datetime.datetime.now().isoformat(),
                "summary": {
                    "total_count": len(news_data_list),
                    "success_count": total_success,
                    "relational_db_success": total_db_success,
                    "vector_db_success": total_vector_success
                }
            }
        }
            
        # except Exception as e:
        #     __log.error(f"处理新闻数据时发生错误: {str(e)}")
        #     return {
        #         "code": 500,
        #         "msg": f"处理新闻数据时发生错误: {str(e)}",
        #         "data": None
        #     }

    @app.route("/api/news/jin10_watch", methods=["GET", "POST"])
    @login_required
    def jin10_watch_control():
        if request.method == "GET":
            return {
                "code": 0,
                "msg": "查询成功",
                "data": _jin10_watch_snapshot(),
            }

        try:
            payload = request.get_json(silent=True) or request.form
            action = str(payload.get("action", "start")).strip().lower()
            interval = int(payload.get("interval", jin10_watch_status["interval"]))
            max_items = int(payload.get("max_items", jin10_watch_status["max_items"]))
            url = str(payload.get("url", jin10_watch_status["url"])).strip()
            state_path = str(
                payload.get("state_path", jin10_watch_status["state_path"])
            ).strip()

            if action == "status":
                return {
                    "code": 0,
                    "msg": "查询成功",
                    "data": _jin10_watch_snapshot(),
                }

            if action == "stop":
                _stop_jin10_watch()
                return {
                    "code": 0,
                    "msg": "金十新闻脚本已停止",
                    "data": _jin10_watch_snapshot(),
                }

            if interval < 10:
                return {
                    "code": 400,
                    "msg": "轮询间隔不能小于10秒",
                    "data": _jin10_watch_snapshot(),
                }

            if max_items < 1:
                return {
                    "code": 400,
                    "msg": "每次处理数量必须大于0",
                    "data": _jin10_watch_snapshot(),
                }

            if action == "run_once":
                _run_jin10_watch_job(url=url, state_path=state_path, max_items=max_items)
                return {
                    "code": 0,
                    "msg": "金十新闻已同步一次",
                    "data": _jin10_watch_snapshot(),
                }

            if action == "start":
                _start_jin10_watch(
                    interval=interval,
                    max_items=max_items,
                    url=url,
                    state_path=state_path,
                )
                return {
                    "code": 0,
                    "msg": "金十新闻脚本已启动",
                    "data": _jin10_watch_snapshot(),
                }

            return {
                "code": 400,
                "msg": f"不支持的操作: {action}",
                "data": _jin10_watch_snapshot(),
            }
        except Exception as e:
            jin10_watch_status["last_error"] = str(e)
            __log.error(f"金十新闻脚本控制失败: {str(e)}")
            return {
                "code": 500,
                "msg": f"金十新闻脚本控制失败: {str(e)}",
                "data": _jin10_watch_snapshot(),
            }

    @app.route("/api/news", methods=["GET"])
    @login_required
    def get_news():
        """
        查询新闻数据的API接口
        支持分页和筛选参数
        """
        try:
            # 获取查询参数
            limit = int(request.args.get('limit', 20))
            offset = int(request.args.get('offset', 0))
            source = request.args.get('source')
            category = request.args.get('category')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            # 处理日期参数
            start_datetime = None
            end_datetime = None
            if start_date:
                try:
                    start_datetime = datetime.datetime.fromisoformat(start_date)
                except ValueError:
                    start_datetime = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            if end_date:
                try:
                    end_datetime = datetime.datetime.fromisoformat(end_date)
                except ValueError:
                    end_datetime = datetime.datetime.strptime(end_date, '%Y-%m-%d')
            
            # 查询新闻数据
            news_list = db.news_query(
                limit=limit,
                offset=offset,
                start_date=start_datetime,
                end_date=end_datetime,
                source=source,
                category=category
            )
            
            # 统计总数
            total_count = db.news_count(
                start_date=start_datetime,
                end_date=end_datetime,
                source=source,
                category=category
            )

            # 检查是否需要同步数据到向量数据库
            sync_to_vector = request.args.get('sync_to_vector', 'false').lower() == 'true'
            vector_db = None
            if sync_to_vector:
                from .news_vector_db import get_vector_db

                vector_db = get_vector_db()
            
            # 转换为字典格式
            news_data = []
            synced_count = 0
            
            for news in news_list:
                news_dict = {
                    'id': news.id,
                    'news_id': news.news_id,
                    'story_id': news.story_id,
                    'title': news.title,
                    'body': news.body,
                    'source': news.source,
                    'published_at': news.published_at.isoformat() if news.published_at else None,
                    'language': news.language,
                    'category': news.category,
                    'tags': news.tags,
                    'sentiment_score': news.sentiment_score,
                    'importance_score': news.importance_score,
                    'created_at': news.created_at.isoformat() if news.created_at else None,
                    'updated_at': news.updated_at.isoformat() if news.updated_at else None
                }
                news_data.append(news_dict)
                
                # 如果需要同步到向量数据库
                if sync_to_vector and news.title and news.body:
                    try:
                        vector_format_data = convert_db_news_to_vector_format(news)
                        if vector_db.add_news(vector_format_data):
                            synced_count += 1
                    except Exception as e:
                        print(f"同步新闻到向量数据库失败: {news.news_id}, 错误: {str(e)}")
            
            response_data = {
                "news_list": news_data,
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
            
            # 如果进行了向量数据库同步，添加同步信息
            if sync_to_vector:
                response_data["sync_info"] = {
                    "synced_count": synced_count,
                    "total_processed": len(news_list),
                    "sync_enabled": True
                }
            
            return {
                "code": 0,
                "msg": "查询成功",
                "data": response_data
            }
            
        except Exception as e:
            __log.error(f"查询新闻数据时发生错误: {str(e)}")
            return {
                "code": 500,
                "msg": f"查询新闻数据时发生错误: {str(e)}",
                "data": None
            }

    @app.route("/api/news/search_by_symbol", methods=["GET"])
    @login_required
    def search_news_by_symbol():
        """
        轻量新闻检索接口，仅查询关系型数据库，避免触发向量库初始化。
        """
        try:
            query_text = str(request.args.get("query") or "").strip()
            market = str(request.args.get("market") or "").strip().lower()
            limit = max(1, min(50, int(request.args.get("limit", 20))))
            if not query_text:
                return {
                    "code": 400,
                    "msg": "query 不能为空",
                    "data": {"results": []},
                }, 400

            keywords = [query_text]
            if market:
                keywords.append(market)

            news_list = db.news_search(
                query_text=query_text,
                keywords=keywords,
                limit=limit,
            )
            results = []
            for news in news_list:
                results.append(
                    {
                        "id": news.id,
                        "news_id": news.news_id,
                        "story_id": news.story_id,
                        "title": news.title,
                        "body": news.body,
                        "source": news.source,
                        "published_at": news.published_at.isoformat() if news.published_at else None,
                        "language": news.language,
                        "category": news.category,
                        "tags": news.tags,
                        "sentiment_score": news.sentiment_score,
                        "importance_score": news.importance_score,
                    }
                )

            return {
                "code": 0,
                "msg": "查询成功",
                "data": {"results": results},
            }
        except Exception as e:
            __log.error(f"轻量新闻检索时发生错误: {str(e)}")
            return {
                "code": 500,
                "msg": f"轻量新闻检索时发生错误: {str(e)}",
                "data": {"results": []},
            }
    
    @app.route("/api/news/sync_to_vector", methods=["POST"])
    @login_required
    def sync_news_to_vector():
        """
        批量同步数据库新闻到向量数据库
        支持参数:
        - limit: 每批处理数量，默认100
        - offset: 偏移量，默认0
        - force: 是否强制重新同步已存在的新闻，默认false
        """
        try:
            # 获取参数
            limit = int(request.json.get('limit', 100)) if request.is_json else int(request.form.get('limit', 100))
            offset = int(request.json.get('offset', 0)) if request.is_json else int(request.form.get('offset', 0))
            force = str(request.json.get('force', 'false')).lower() == 'true' if request.is_json else str(request.form.get('force', 'false')).lower() == 'true'
            
            # 获取向量数据库实例
            from .news_vector_db import get_vector_db
            vector_db = get_vector_db()
            
            # 查询数据库中的新闻
            news_list = db.news_query(limit=limit, offset=offset)
            
            if not news_list:
                return {
                    "code": 200,
                    "msg": "没有找到需要同步的新闻",
                    "data": {
                        "synced_count": 0,
                        "total_processed": 0,
                        "skipped_count": 0,
                        "error_count": 0
                    }
                }
            
            # 批量同步
            synced_count = 0
            skipped_count = 0
            error_count = 0
            error_details = []
            
            for news in news_list:
                if not news.title or not news.body:
                    skipped_count += 1
                    continue
                
                try:
                    # 转换数据格式
                    vector_format_data = convert_db_news_to_vector_format(news)
                    
                    # 如果不是强制模式，检查是否已存在
                    if not force:
                        # 这里可以添加检查逻辑，暂时直接尝试添加
                        pass
                    
                    # 添加到向量数据库
                    if vector_db.add_news(vector_format_data):
                        synced_count += 1
                    else:
                        skipped_count += 1
                        
                except Exception as e:
                    error_count += 1
                    error_details.append({
                        "news_id": news.news_id or str(news.id),
                        "title": news.title[:50] + "..." if news.title and len(news.title) > 50 else news.title,
                        "error": str(e)
                    })
            
            return {
                "code": 0,
                "msg": "同步完成",
                "data": {
                    "synced_count": synced_count,
                    "total_processed": len(news_list),
                    "skipped_count": skipped_count,
                    "error_count": error_count,
                    "error_details": error_details[:10] if error_details else [],  # 最多返回10个错误详情
                    "has_more_errors": len(error_details) > 10
                }
            }
            
        except Exception as e:
            __log.error(f"同步新闻到向量数据库时发生错误: {str(e)}")
            return {
                "code": 500,
                "msg": f"同步新闻到向量数据库时发生错误: {str(e)}",
                "data": None
            }

    # 经济数据API路由
    @app.route("/api/economic/data", methods=["POST"])
    def receive_economic_data():
        """
        接收经济数据的API接口
        """
       

        from .economic_data_receiver import receive_economic_data
        return receive_economic_data()
    
    @app.route("/api/economic/data", methods=["GET"])
    @login_required
    def get_economic_data():
        """
        查询经济数据的API接口
        """
        from .economic_data_receiver import get_economic_data
        
        # 获取查询参数
        indicator_name = request.args.get('indicator_name')
        ds_mnemonic = request.args.get('ds_mnemonic')
        year = request.args.get('year')
        if year:
            year = int(year)
        limit = int(request.args.get('limit', 100))
        
        return get_economic_data(indicator_name, ds_mnemonic, year, limit)

    @app.route("/chart")
    def chart():
        """
        生成图表图片
        """
        try:
            import tempfile
            import base64
            from io import BytesIO
            from chanlun.kcharts import render_charts
            from chanlun.tools.ai_analyse import AIAnalyse
            
            # 获取参数
            market = request.args.get('market', 'FE')
            code = request.args.get('code', 'EURUSD')
            frequency = request.args.get('frequency', '5m')
            
            # 构建完整的代码
            full_code = f"{market}.{code}"
            
            # 获取缠论分析数据
            ai_analyse = AIAnalyse(market)
            cl_data = ai_analyse.analyse(full_code, frequency)
            
            if cl_data is None:
                return "无法获取图表数据", 404
            
            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            # 生成图表并保存到临时文件
            config = {
                'to_file': tmp_path,
                'chart_width': '800px',
                'chart_high': '600px',
                'chart_kline_nums': 200
            }
            
            render_charts(f"{full_code} {frequency}", cl_data, config=config)
            
            # 读取生成的HTML文件
            with open(tmp_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # 清理临时文件
            os.unlink(tmp_path)
            
            return html_content, 200, {'Content-Type': 'text/html; charset=utf-8'}
            
        except Exception as e:
            __log.error(f"生成图表时发生错误: {str(e)}")
            return f"生成图表时发生错误: {str(e)}", 500
    
    @app.route("/chart_image")
    def chart_image():
        """
        生成图表的base64图片数据
        """
        try:
            from chanlun.tools.ai_analyse import AIAnalyse
            import json
            
            # 获取参数
            market = request.args.get('market', 'FE')
            code = request.args.get('code', 'EURUSD')
            frequency = request.args.get('frequency', '5m')
            
            # 构建完整的代码
            full_code = f"{market}.{code}"
            
            # 获取缠论分析数据
            ai_analyse = AIAnalyse()
            cl_data = ai_analyse.analyse(full_code, frequency)
            
            if cl_data is None:
                return json.dumps({"error": "无法获取图表数据"}), 404
            
            # 简化的图表数据返回（K线数据）
            klines = cl_data.get_klines()
            chart_data = {
                "symbol": full_code,
                "frequency": frequency,
                "klines": [
                    {
                        "date": k.date.strftime('%Y-%m-%d %H:%M:%S'),
                        "open": k.o,
                        "high": k.h,
                        "low": k.l,
                        "close": k.c,
                        "volume": k.v
                    } for k in klines[-50:]  # 只返回最近50根K线
                ]
            }
            
            return json.dumps(chart_data, ensure_ascii=False), 200, {'Content-Type': 'application/json; charset=utf-8'}
            
        except Exception as e:
            __log.error(f"生成图表数据时发生错误: {str(e)}")
            return json.dumps({"error": f"生成图表数据时发生错误: {str(e)}"}), 500

    # 注册向量数据库API路由
    register_vector_api_routes(app)
    register_smart_news_api(app)

    # 注册个股「分析观点」路由(东财股吧评论 → Claude 分类总结)
    from .serenity_opinions import register_serenity_opinions_routes
    register_serenity_opinions_routes(app)
    
    # 注册 AGI 知识库 API 蓝图
    from .ai_agent.knowledge_api import knowledge_bp
    app.register_blueprint(knowledge_bp)
    
    # 注册 AGI Chat API 蓝图
    from .ai_agent.chat_api import chat_bp
    app.register_blueprint(chat_bp)

    if not app.config.get("TESTING", False):
        _start_serenity_aistocks_price_sync(interval_seconds=180)
        # 金十新闻定时抓取开机自启（仅写入 MySQL cl_news，不加载向量库）
        _start_jin10_watch(
            interval=jin10_watch_status["interval"],
            max_items=jin10_watch_status["max_items"],
            url=jin10_watch_status["url"],
            state_path=str(jin10_watch_state_path),
        )

    return app
