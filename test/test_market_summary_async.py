import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from chanlun import db as chanlun_db
from cl_app import news_vector_api as api
from cl_app import market_data_adapter
from cl_app import theme_reasoning_agent as theme_reasoning
from cl_app import timesfm_service


def test_summary_result_cache_roundtrip(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    payload = {"query": "EURUSD", "days": 7}
    result = {"summary": "缓存总结", "summary_id": 999}
    api._save_summary_result_cache("market_summary", payload, result)

    cached = api._load_summary_result_cache("market_summary", payload)
    assert cached["summary"] == "缓存总结"
    assert cached["summary_id"] == 999
    assert cached["cache_hit"] is True


def test_summary_task_can_restore_from_cache(monkeypatch):
    api._MARKET_SUMMARY_TASKS.clear()
    cache_store = {}

    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    api._set_market_summary_task("task_cached", task_id="task_cached", state="queued", progress=0)
    api._MARKET_SUMMARY_TASKS.clear()

    task = api._get_market_summary_task("task_cached")
    assert task["task_id"] == "task_cached"
    assert task["state"] == "queued"


def test_run_market_summary_task_updates_status(monkeypatch):
    api._MARKET_SUMMARY_TASKS.clear()
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    def fake_generate(payload, progress_callback=None):
        if progress_callback is not None:
            progress_callback("search_news", "正在检索相关新闻", 20)
            progress_callback("summary", "AI 正在生成市场总结", 80)
        return {
            "summary": "测试总结",
            "summary_id": 123,
            "news_count": 8,
            "economic_data_count": 3,
        }

    monkeypatch.setattr(api, "_generate_market_summary_payload", fake_generate)

    api._run_market_summary_task("task_ok", {"query": "EURUSD", "current_market": "fx"})

    task = api._get_market_summary_task("task_ok")
    assert task["state"] == "completed"
    assert task["progress"] == 100
    assert task["summary_id"] == 123
    assert task["result"]["summary"] == "测试总结"


def test_run_market_summary_task_records_failure(monkeypatch):
    api._MARKET_SUMMARY_TASKS.clear()
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    def fake_generate(payload, progress_callback=None):
        raise ValueError("未找到相关新闻")

    monkeypatch.setattr(api, "_generate_market_summary_payload", fake_generate)

    api._run_market_summary_task("task_fail", {"query": "EMPTY", "current_market": "fx"})

    task = api._get_market_summary_task("task_fail")
    assert task["state"] == "failed"
    assert task["error"] == "未找到相关新闻"


def test_run_daily_summary_task_updates_status(monkeypatch):
    api._MARKET_SUMMARY_TASKS.clear()
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    def fake_generate(payload, progress_callback=None):
        if progress_callback is not None:
            progress_callback("search_news", "正在获取近3天新闻", 15)
            progress_callback("summary", "AI 正在生成每日新闻总结", 80)
        return {
            "summary": "每日总结",
            "summary_id": 456,
            "news_count": 18,
            "days": 3,
        }

    monkeypatch.setattr(api, "_generate_daily_summary_payload", fake_generate)

    api._run_daily_summary_task("daily_ok", {"days": 3})

    task = api._get_market_summary_task("daily_ok")
    assert task["task_type"] == "daily_news_summary"
    assert task["state"] == "completed"
    assert task["summary_id"] == 456
    assert task["result"]["summary"] == "每日总结"


def test_generate_daily_summary_payload_uses_cache(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    api._save_summary_result_cache(
        "daily_news_summary",
        {"days": 3},
        {"summary": "缓存日报", "summary_id": 321, "news_count": 12},
    )

    called = {"count": 0}

    def fake_get_news_window(days, limit=5000):
        called["count"] += 1
        return [], "db"

    monkeypatch.setattr(api, "_get_news_window_for_summary", fake_get_news_window)

    result = api._generate_daily_summary_payload({"days": 3})
    assert result["summary"] == "缓存日报"
    assert result["cache_hit"] is True
    assert called["count"] == 0


def test_build_daily_summary_trader_brief_returns_actionable_watchlist():
    result = api._build_daily_summary_trader_brief(
        news_list=[
            {"title": "美联储官员讲话提振美元", "published_at": "2026-04-06 09:00:00", "source": "fx", "importance_score": 0.92},
            {"title": "欧央行通胀表态偏鸽", "published_at": "2026-04-06 08:30:00", "source": "fx", "importance_score": 0.88},
        ],
        analyzed_targets=["EURUSD", "DXY", "XAUUSD"],
        days=1,
    )

    assert result["action"] == "wait"
    assert result["action_label"] == "先筛选，后交易"
    assert result["focus_targets"][0] == "EURUSD"
    assert result["must_watch_news"][0]["title"] == "美联储官员讲话提振美元"


def test_event_topic_definitions_roundtrip(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))

    saved = api._save_event_topic_definitions(
        [
            {
                "id": "fed-speeches",
                "label": "美联储讲话",
                "description": "测试主题",
                "keywords": "美联储, 鲍威尔, FOMC",
                "enabled": True,
            }
        ]
    )

    loaded = api._load_event_topic_definitions()
    assert saved[0]["label"] == "美联储讲话"
    assert loaded[0]["keywords"] == ["美联储", "鲍威尔", "FOMC"]


def test_build_historical_topic_timeline_deduplicates_repeated_news():
    timelines = api._build_historical_topic_timeline(
        events=[
            {
                "event_id": "evt_1",
                "trigger_dt": datetime(2026, 4, 6, 9, 0, 0),
                "direction": "bearish",
                "return_pct": -0.82,
                "abs_return_pct": 0.82,
                "bar_range_pct": 1.12,
                "storyline": "地缘政治",
                "cause_summary": "伊朗相关战争升级引发避险与油价冲击。",
                "event_news_details": [
                    {"title": "伊朗与以色列冲突升级推高油价", "summary": "中东局势升级。", "impact_label": "偏利空", "impact_reason": "避险情绪升温。", "published_at": "2026-04-06T08:58:00", "event_news_score": 11.2},
                    {"title": "伊朗与以色列冲突升级推高油价", "summary": "重复新闻。", "impact_label": "偏利空", "impact_reason": "重复。", "published_at": "2026-04-06T08:59:00", "event_news_score": 10.6},
                ],
            }
        ],
        topic_definitions=[
            {
                "id": "iran-conflict",
                "label": "伊朗战争",
                "description": "测试主题",
                "keywords": ["伊朗", "以色列", "中东"],
                "enabled": True,
            }
        ],
    )

    assert timelines[0]["topic_label"] == "伊朗战争"
    assert timelines[0]["event_count"] == 1
    assert len(timelines[0]["representative_news"]) == 1
    assert "重复报道已自动归并" in timelines[0]["topic_summary"]


def test_detect_price_events_identifies_significant_move():
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    closes = [100.0, 100.1, 100.15, 101.0, 101.3, 101.6, 101.8, 101.9]
    bars = []
    prev_close = closes[0]
    for index, close in enumerate(closes):
        open_price = prev_close if index else close
        bars.append(
            {
                "dt": base_dt + timedelta(minutes=index * 5),
                "open": open_price,
                "close": close,
                "high": max(open_price, close) + 0.1,
                "low": min(open_price, close) - 0.1,
                "volume": 1000 + index,
            }
        )
        prev_close = close

    events = api._detect_price_events(
        price_bars=bars,
        min_return_pct=0.3,
        min_range_pct=0.5,
        atr_multiple=1.0,
        event_window_minutes=5,
        merge_gap_minutes=10,
    )

    assert events
    assert events[0]["direction"] == "bullish"
    assert events[0]["abs_return_pct"] >= 0.3


def test_run_historical_analysis_task_updates_status(monkeypatch):
    api._MARKET_SUMMARY_TASKS.clear()
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(
        api,
        "_generate_historical_analysis_payload",
        lambda payload, progress_callback=None: {
            "summary": "历史分析报告",
            "summary_id": 789,
            "event_count": 3,
            "storyline_count": 2,
        },
    )

    api._run_historical_analysis_task("history_ok", {"current_market": "fx", "current_code": "EURUSD"})

    task = api._get_market_summary_task("history_ok")
    assert task["task_type"] == "historical_analysis"
    assert task["state"] == "completed"
    assert task["summary_id"] == 789


def test_generate_market_summary_payload_uses_module_news_retriever(monkeypatch):
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: True)
    monkeypatch.setattr(api, "_create_optimized_search_query", lambda query, lookup_code: (query, {"name_cn": "欧元美元"}))
    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(stock_info=lambda code: {"name": "欧元美元", "code": code}),
    )
    monkeypatch.setattr(
        api,
        "get_vector_news",
        lambda *args, **kwargs: [
            {
                "id": "n1",
                "document": "欧元兑美元上涨",
                "metadata": {
                    "news_id": "n1",
                    "title": "欧元兑美元上涨",
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                    "source": "jin10",
                    "category": "fx",
                },
                "score": 10.0,
            }
        ],
    )
    monkeypatch.setattr(api, "_get_economic_data_by_product", lambda **kwargs: [])
    monkeypatch.setattr(api, "_generate_ai_market_summary", lambda *args, **kwargs: "测试总结")
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: {
            "available": True,
            "summary": "未来30分钟偏上行",
            "forecast_30m": {"summary": "未来30分钟偏上行"},
            "forecast_120m": {"summary": "未来120分钟偏上行"},
        },
    )
    monkeypatch.setattr(api.db, "market_summary_insert", lambda summary_data: 1)

    result = api._generate_market_summary_payload(
        {"query": "EURUSD", "current_market": "fx", "current_code": "EURUSD", "days": 7}
    )

    assert result["summary"] == "测试总结"
    assert result["summary_id"] == 1
    assert result["news_count"] == 1


def test_generate_market_summary_payload_accepts_dict_summary_result(monkeypatch):
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: True)
    monkeypatch.setattr(api, "_create_optimized_search_query", lambda query, lookup_code: (query, {"name_cn": "欧元美元"}))
    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(stock_info=lambda code: {"name": "欧元美元", "code": code}),
    )
    monkeypatch.setattr(
        api,
        "get_vector_news",
        lambda *args, **kwargs: [
            {
                "id": "n1",
                "document": "欧元兑美元上涨",
                "metadata": {
                    "news_id": "n1",
                    "title": "欧元兑美元上涨",
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                    "source": "jin10",
                    "category": "fx",
                },
                "score": 10.0,
            }
        ],
    )
    monkeypatch.setattr(api, "_get_economic_data_by_product", lambda **kwargs: [])
    monkeypatch.setattr(
        api,
        "_generate_ai_market_summary",
        lambda *args, **kwargs: {
            "summary": "结构化测试总结",
            "risk_assessment": "风险等级: 中",
            "research_verdict": "最终立场: 看多",
            "scenario_route": {"route": "news_catalyst", "label": "新闻催化跟踪"},
            "reflection_memory": {"summary": "过去类似场景需要观察延续性"},
            "quick_research": {"mode": "quick", "summary": "先看新闻催化是否扩散"},
            "deep_research": {"mode": "deep", "summary": "继续调用宏观与技术节点"},
        },
    )
    monkeypatch.setattr(api.db, "market_summary_insert", lambda summary_data: 2)
    monkeypatch.setattr(
        api,
        "_summarize_realtime_price_state",
        lambda *args, **kwargs: {"alert_level": "medium", "status_label": "观察中"},
    )
    monkeypatch.setattr(
        api,
        "_build_cross_asset_watch",
        lambda **kwargs: {"items": [], "summary": "暂无明显跨资产共振"},
    )
    monkeypatch.setattr(
        api,
        "_build_research_scenario_route",
        lambda **kwargs: {"route": "balanced_monitoring", "label": "均衡观察"},
    )
    monkeypatch.setattr(
        api,
        "_build_reflection_memory",
        lambda **kwargs: {"summary": "旧反思"},
    )
    monkeypatch.setattr(
        api,
        "_build_quick_research_snapshot",
        lambda **kwargs: {"mode": "quick", "summary": "旧快评"},
    )
    monkeypatch.setattr(
        api,
        "_build_deep_research_plan",
        lambda **kwargs: {"mode": "deep", "summary": "旧深研"},
    )
    monkeypatch.setattr(
        api,
        "_build_rule_based_risk_brief",
        lambda **kwargs: {"level": "medium", "summary": "规则风险提示"},
    )
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: {
            "available": True,
            "summary": "未来30分钟偏下行",
            "forecast_30m": {"summary": "未来30分钟偏下行"},
            "forecast_120m": {"summary": "未来120分钟偏下行"},
        },
    )

    result = api._generate_market_summary_payload(
        {"query": "EURUSD", "current_market": "fx", "current_code": "EURUSD", "days": 7}
    )

    assert result["summary"] == "结构化测试总结"
    assert result["risk_assessment"] == "风险等级: 中"
    assert result["research_verdict"] == "最终立场: 看多"
    assert result["scenario_route"]["route"] == "news_catalyst"
    assert result["quick_research"]["summary"] == "先看新闻催化是否扩散"
    assert result["deep_research"]["summary"] == "继续调用宏观与技术节点"
    assert result["reflection_memory"]["summary"] == "过去类似场景需要观察延续性"
    assert result["risk_brief"]["summary"] == "规则风险提示"
    assert result["timesfm_forecast"]["forecast_30m"]["summary"] == "未来30分钟偏下行"


def test_generate_historical_analysis_payload_builds_storylines(monkeypatch):
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: True)
    base_dt = datetime(2026, 4, 4, 9, 0, 0)

    klines = []
    prices = [100.0, 100.05, 100.1, 100.95, 101.0, 101.2, 101.35, 101.45, 101.5, 101.55]
    prev_price = prices[0]
    for idx, price in enumerate(prices):
        open_price = prev_price if idx else price
        klines.append(
            SimpleNamespace(
                dt=base_dt + timedelta(minutes=idx * 5),
                o=open_price,
                c=price,
                h=max(open_price, price) + 0.08,
                l=min(open_price, price) - 0.08,
                v=1000 + idx,
            )
        )
        prev_price = price

    monkeypatch.setattr(api.db, "klines_query", lambda **kwargs: klines)
    monkeypatch.setattr(api, "_get_product_info", lambda code: {"name_cn": "欧元美元", "type": "forex", "keywords": ["欧元", "美元"]})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: api._default_event_topic_definitions())
    monkeypatch.setattr(
        api,
        "infer_asset_impact_direction",
        lambda title, body, canonical_asset: {
            "impact_direction": "bearish",
            "direction_score": -0.8,
            "reason": "美元走强压制欧元美元。",
        },
    )
    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(stock_info=lambda code: {"name": "欧元美元", "code": code}),
    )
    monkeypatch.setattr(
        api,
        "_search_news_from_relational_db",
        lambda query, search_terms, start_date, end_date, n_results: [
            {
                "document": "美联储官员讲话后美元走强，欧元回落。",
                "metadata": {
                    "news_id": "hn1",
                    "title": "美联储官员讲话提振美元",
                    "published_at": (start_date + timedelta(minutes=2)).isoformat(),
                    "importance_score": 0.9,
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                },
            }
        ],
    )
    monkeypatch.setattr(api, "_generate_ai_historical_analysis", lambda **kwargs: "历史分析报告")
    monkeypatch.setattr(
        api,
        "_collect_similar_historical_events",
        lambda **kwargs: [
            {
                "published_at": "2026-03-20T10:00:00",
                "storyline": "央行与利率",
                "title": "历史上的美联储鹰派讲话",
                "similarity_score": 4.6,
                "reaction": {
                    "follow_30m_pct": -0.35,
                    "follow_120m_pct": -0.6,
                    "absorption_status": "not_fully_priced",
                },
            }
        ],
    )
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: {
            "available": True,
            "summary": "当前主模式为纯价格，短线偏下行。",
            "trade_plan": {
                "action": "watch_short",
                "action_label": "等待确认",
                "summary": "等待确认：短线偏下行，但先等价格继续确认。",
                "no_trade_reason": "模型优势一般，先观察。",
            },
            "forecast_primary": {"summary": "5分钟偏下行", "direction": "bearish", "continuation_probability": 0.58, "uncertainty_level": "medium", "horizon_label": "5分钟"},
            "forecast_secondary": {"summary": "20分钟偏下行", "direction": "bearish", "continuation_probability": 0.61, "uncertainty_level": "medium", "horizon_label": "20分钟"},
            "forecast_30m": {"summary": "5分钟偏下行"},
            "forecast_120m": {"summary": "20分钟偏下行"},
            "backend_details": {"native_enabled": True, "native_message": "", "xreg_used": False},
        },
    )
    monkeypatch.setattr(api.db, "market_summary_insert", lambda payload: 888)

    result = api._generate_historical_analysis_payload(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "lookback_hours": 24,
            "event_frequency": "5m",
            "min_return_pct": 0.3,
            "min_range_pct": 0.5,
            "atr_multiple": 1.0,
            "event_window_minutes": 5,
            "max_events": 5,
        }
    )

    assert result["summary"] == "历史分析报告"
    assert result["summary_id"] == 888
    assert result["event_count"] >= 1
    assert result["storyline_count"] >= 1
    assert result["events"][0]["top_news_titles"]
    assert result["pricing_summary"]["future_bias"] in {"偏向延续上行", "偏向延续下行", "偏向震荡等待"}
    assert result["storylines"][0]["strength_score"] >= 0
    assert result["similar_events"][0]["storyline"] == "央行与利率"
    assert result["pricing_room"]["estimated_room_pct"] >= 0
    assert result["lookback_label"] == "1天"
    assert result["analysis_window"]["start"]
    assert result["analysis_window"]["end"]
    assert result["events"][0]["cause_summary"]
    assert result["events"][0]["event_news_details"][0]["title"] == "美联储官员讲话提振美元"
    assert result["events"][0]["event_news_details"][0]["impact_label"] == "偏利空"
    assert result["topic_count"] >= 1
    assert result["topic_timeline"][0]["topic_label"] in {"美联储官员讲话", "央行与利率"}
    assert result["trader_decision"]["action_label"] in {"可执行", "等待确认", "轻仓观察", "先不交易"}
    assert result["trader_decision"]["driver"]
    assert result["event_trade_templates"][0]["cause_title"] == "美联储官员讲话提振美元"
    assert "timesfm_forecast" in result
    assert "timesfm_forecast" in result["events"][0]


def test_generate_historical_analysis_payload_falls_back_to_latest_price_bars(monkeypatch):
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: True)
    base_dt = datetime(2026, 4, 4, 9, 0, 0)

    strict_klines = [
        SimpleNamespace(
            dt=base_dt,
            o=100.0,
            c=100.1,
            h=100.15,
            l=99.95,
            v=1000,
        ),
        SimpleNamespace(
            dt=base_dt + timedelta(minutes=5),
            o=100.1,
            c=100.12,
            h=100.18,
            l=100.02,
            v=1001,
        ),
    ]

    fallback_klines = []
    prices = [100.0, 100.05, 100.08, 100.12, 100.95, 101.05, 101.18, 101.26, 101.34, 101.42, 101.5, 101.62]
    prev_price = prices[0]
    for idx, price in enumerate(prices):
        open_price = prev_price if idx else price
        fallback_klines.append(
            SimpleNamespace(
                dt=base_dt - timedelta(minutes=(len(prices) - idx) * 5),
                o=open_price,
                c=price,
                h=max(open_price, price) + 0.08,
                l=min(open_price, price) - 0.08,
                v=2000 + idx,
            )
        )
        prev_price = price

    def fake_klines_query(**kwargs):
        if kwargs.get("start_date") is not None:
            return strict_klines
        return fallback_klines

    monkeypatch.setattr(api.db, "klines_query", fake_klines_query)
    monkeypatch.setattr(api.db, "klines_last_datetime", lambda *args, **kwargs: "2026-04-04 09:55:00")
    monkeypatch.setattr(api, "_get_product_info", lambda code: {"name_cn": "欧元美元", "type": "forex", "keywords": ["欧元", "美元"]})
    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(stock_info=lambda code: {"name": "欧元美元", "code": code}),
    )
    monkeypatch.setattr(
        api,
        "_search_news_from_relational_db",
        lambda query, search_terms, start_date, end_date, n_results: [
            {
                "document": "美元走强引发欧元美元快速波动。",
                "metadata": {
                    "news_id": "fallback_news",
                    "title": "美元走强带动汇率异动",
                    "published_at": (start_date + timedelta(minutes=2)).isoformat(),
                    "importance_score": 0.9,
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                },
            }
        ],
    )
    monkeypatch.setattr(api, "_generate_ai_historical_analysis", lambda **kwargs: "回退后历史分析报告")
    monkeypatch.setattr(api, "_collect_similar_historical_events", lambda **kwargs: [])
    monkeypatch.setattr(api.db, "market_summary_insert", lambda payload: 889)

    result = api._generate_historical_analysis_payload(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "lookback_hours": 24,
            "event_frequency": "5m",
            "min_return_pct": 0.3,
            "min_range_pct": 0.5,
            "atr_multiple": 1.0,
            "event_window_minutes": 5,
            "max_events": 5,
        }
    )

    assert result["summary"] == "回退后历史分析报告"
    assert result["summary_id"] == 889
    assert result["event_count"] >= 1
    assert result["events"][0]["news_count"] >= 1
    assert "timesfm_forecast" in result


def test_load_historical_price_bars_resolves_fx_alias_via_exchange(monkeypatch):
    monkeypatch.setattr(api.db, "klines_query", lambda **kwargs: [])

    exchange_calls = []
    base_dt = datetime(2026, 4, 4, 9, 0, 0)

    class FakeFrame:
        empty = False

        def to_dict(self, orient):
            assert orient == "records"
            return [
                {
                    "date": base_dt + timedelta(minutes=idx * 5),
                    "open": 100.0 + idx * 0.1,
                    "close": 100.05 + idx * 0.1,
                    "high": 100.12 + idx * 0.1,
                    "low": 99.95 + idx * 0.1,
                    "volume": 1000 + idx,
                }
                for idx in range(12)
            ]

    def fake_get_exchange(market):
        return SimpleNamespace(
            klines=lambda code, frequency, start_date=None, end_date=None, args=None: (
                exchange_calls.append((code, frequency, args)) or (FakeFrame() if code == "FX.USDEUR" else None)
            )
        )

    monkeypatch.setattr(api, "get_exchange", fake_get_exchange)

    bars = api._load_historical_price_bars(
        market="fx",
        code="EURUSD",
        frequency="5m",
        lookback_hours=24,
    )

    assert len(bars) == 12
    assert any(call[0] == "FX.USDEUR" for call in exchange_calls)


def test_load_historical_price_bars_throttles_repeated_fallback_logs(monkeypatch):
    monkeypatch.setattr(api.db, "klines_query", lambda **kwargs: [])
    api._PRICE_BAR_FALLBACK_LOG_STATE.clear()

    base_dt = datetime(2026, 4, 4, 9, 0, 0)

    class FakeFrame:
        empty = False

        def to_dict(self, orient):
            assert orient == "records"
            return [
                {
                    "date": base_dt + timedelta(minutes=idx * 5),
                    "open": 100.0 + idx * 0.1,
                    "close": 100.05 + idx * 0.1,
                    "high": 100.12 + idx * 0.1,
                    "low": 99.95 + idx * 0.1,
                    "volume": 1000 + idx,
                }
                for idx in range(12)
            ]

    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(klines=lambda code, frequency, start_date=None, end_date=None, args=None: FakeFrame()),
    )

    log_messages = []
    monkeypatch.setattr(api.logger, "info", lambda message, *args: log_messages.append(message % args))
    monkeypatch.setattr(api.time, "time", lambda: 1000.0)

    first_bars = api._load_historical_price_bars(
        market="fx",
        code="EURUSD",
        frequency="5m",
        lookback_hours=24,
        purpose="实时关注",
    )
    second_bars = api._load_historical_price_bars(
        market="fx",
        code="EURUSD",
        frequency="5m",
        lookback_hours=24,
        purpose="实时关注",
    )

    assert len(first_bars) == 12
    assert len(second_bars) == 12
    assert len(log_messages) == 1
    assert "实时关注价格数据不足" in log_messages[0]
    assert "交易所实时K线" in log_messages[0]


def test_load_historical_price_bars_persists_exchange_data_and_refreshes_stale_series(monkeypatch):
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    stale_bars = [
        SimpleNamespace(
            dt=base_dt - timedelta(days=2) + timedelta(minutes=idx * 5),
            o=100.0 + idx,
            c=100.2 + idx,
            h=100.4 + idx,
            l=99.8 + idx,
            v=1000 + idx,
        )
        for idx in range(12)
    ]
    persisted = {}
    exchange_calls = []

    class FakeFrame:
        empty = False
        columns = ["date", "open", "close", "high", "low", "volume"]

        def copy(self):
            return self

        def rename(self, columns=None):
            return self

        def __getitem__(self, columns):
            return self

        def to_dict(self, orient):
            assert orient == "records"
            return [
                {
                    "date": base_dt + timedelta(minutes=idx * 5),
                    "open": 200.0 + idx * 0.1,
                    "close": 200.2 + idx * 0.1,
                    "high": 200.4 + idx * 0.1,
                    "low": 199.8 + idx * 0.1,
                    "volume": 3000 + idx,
                }
                for idx in range(12)
            ]

    monkeypatch.setattr(api.db, "klines_query", lambda **kwargs: stale_bars)
    monkeypatch.setattr(api.db, "klines_insert", lambda market, code, frequency, klines: persisted.setdefault("rows", klines) or True)
    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(
            klines=lambda code, frequency, start_date=None, end_date=None, args=None: exchange_calls.append((code, frequency)) or FakeFrame()
        ),
    )

    bars = api._load_historical_price_bars(
        market="fx",
        code="EURUSD",
        frequency="5m",
        lookback_hours=24,
        purpose="主题时间性",
    )

    assert len(bars) == 12
    assert bars[-1]["close"] > 200
    assert exchange_calls
    assert "rows" in persisted


def test_summarize_historical_pricing_state_prefers_unpriced_direction():
    summary = api._summarize_historical_pricing_state(
        events=[
            {
                "absorption_status": "not_fully_priced",
                "direction_sign": 1,
                "abs_return_pct": 0.8,
            },
            {
                "absorption_status": "partially_absorbed",
                "direction_sign": 1,
                "abs_return_pct": 0.4,
            },
            {
                "absorption_status": "absorbed",
                "direction_sign": -1,
                "abs_return_pct": 0.2,
            },
        ],
        storylines=[
            {
                "storyline": "央行与利率",
                "direction": "偏利多",
                "strength_score": 5.2,
            }
        ],
    )

    assert summary["future_bias"] == "偏向延续上行"
    assert summary["absorption_counts"]["not_fully_priced"] == 1
    assert summary["strongest_storyline"]["storyline"] == "央行与利率"


def test_collect_similar_historical_events_returns_ranked_samples(monkeypatch):
    base_dt = datetime(2026, 4, 4, 12, 0, 0)
    monkeypatch.setattr(
        api,
        "_search_news_from_relational_db",
        lambda query, search_terms, start_date, end_date, n_results: [
            {
                "document": "美联储鹰派讲话后美元走强。",
                "metadata": {
                    "news_id": "sim1",
                    "title": "美联储鹰派讲话引发美元走强",
                    "published_at": (base_dt - timedelta(days=10)).isoformat(),
                    "importance_score": 0.9,
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                },
            }
        ],
    )
    monkeypatch.setattr(
        api,
        "_estimate_price_reaction_around_time",
        lambda market, code, frequency, anchor_dt: {
            "direction": "bearish",
            "return_pct": -0.22,
            "follow_30m_pct": -0.35,
            "follow_120m_pct": -0.58,
            "absorption_status": "not_fully_priced",
            "absorption_reason": "持续下跌",
        },
    )

    samples = api._collect_similar_historical_events(
        current_market="fx",
        current_code="EURUSD",
        query="欧元美元",
        product_info={"name_cn": "欧元美元", "keywords": ["欧元", "美元"]},
        stock_info={"name": "欧元美元", "code": "EURUSD"},
        storylines=[{"storyline": "央行与利率"}],
        reference_start_dt=base_dt,
        frequency="5m",
        max_samples=3,
    )

    assert samples
    assert samples[0]["storyline"] == "央行与利率"
    assert samples[0]["reaction"]["absorption_status"] == "not_fully_priced"
    assert samples[0]["similarity_score"] > 0


def test_estimate_remaining_pricing_room_uses_similar_samples():
    result = api._estimate_remaining_pricing_room(
        events=[
            {
                "storyline": "央行与利率",
                "absorption_status": "not_fully_priced",
                "follow_30m_pct": 0.25,
                "follow_120m_pct": 0.35,
            },
            {
                "storyline": "央行与利率",
                "absorption_status": "partially_absorbed",
                "follow_30m_pct": 0.18,
                "follow_120m_pct": 0.22,
            },
        ],
        storylines=[
            {
                "storyline": "央行与利率",
                "direction": "偏利多",
                "strength_score": 6.4,
            }
        ],
        similar_events=[
            {
                "storyline": "央行与利率",
                "reaction": {
                    "direction": "bullish",
                    "follow_120m_pct": 0.8,
                },
            },
            {
                "storyline": "央行与利率",
                "reaction": {
                    "direction": "bullish",
                    "follow_120m_pct": 0.6,
                },
            },
        ],
    )

    assert result["storyline"] == "央行与利率"
    assert result["estimated_room_pct"] > 0
    assert result["confidence"] in {"medium", "high"}


def test_derive_storyline_label_respects_asset_template_priority():
    news_items = [
        {
            "document": "中东冲突升级带动避险需求升温，同时美联储加息预期抬头。",
            "metadata": {"title": "中东冲突与美联储加息并行影响市场"},
        }
    ]

    gold_storyline = api._derive_storyline_label(news_items, asset_code="XAU", market="futures")
    eurusd_storyline = api._derive_storyline_label(news_items, asset_code="EURUSD", market="fx")

    assert gold_storyline in {"地缘政治", "风险情绪"}
    assert eurusd_storyline == "央行与利率"


def test_build_historical_storylines_applies_asset_template_weight():
    events = [
        {
            "storyline": "商品供给",
            "direction_sign": 1,
            "abs_return_pct": 0.4,
            "news_count": 2,
            "absorption_status": "not_fully_priced",
            "top_news_titles": ["OPEC 会议释放减产信号"],
        },
        {
            "storyline": "央行与利率",
            "direction_sign": 1,
            "abs_return_pct": 0.45,
            "news_count": 2,
            "absorption_status": "not_fully_priced",
            "top_news_titles": ["美联储官员讲话"],
        },
    ]

    oil_storylines = api._build_historical_storylines(events, asset_code="CL", market="futures")
    fx_storylines = api._build_historical_storylines(events, asset_code="EURUSD", market="fx")

    assert oil_storylines[0]["storyline"] == "商品供给"
    assert fx_storylines[0]["storyline"] == "央行与利率"
    assert oil_storylines[0]["template_weight"] > fx_storylines[0]["template_weight"]


def test_estimate_price_reaction_around_time_uses_symmetric_anchor_windows(monkeypatch):
    anchor_dt = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=12)
    bars = []
    for idx in range(-6, 73):
        dt = anchor_dt + timedelta(minutes=idx * 5)
        base_price = 1.0000
        if idx < 0:
            close_price = base_price + idx * 0.00005
        elif idx <= 12:
            close_price = base_price + idx * 0.0005
        else:
            close_price = base_price + 0.0060 + (idx - 12) * 0.00002
        bars.append(
            {
                "dt": dt,
                "open": close_price - 0.0001,
                "close": close_price,
                "high": close_price + 0.0002,
                "low": close_price - 0.0002,
                "volume": 1000.0,
            }
        )

    monkeypatch.setattr(api, "_load_historical_price_bars", lambda **kwargs: bars)
    monkeypatch.setattr(api.db, "klines_query", lambda **kwargs: [])

    reaction = api._estimate_price_reaction_around_time(
        market="fx",
        code="AUDUSD",
        frequency="5m",
        anchor_dt=anchor_dt,
    )

    assert reaction is not None
    assert reaction["direction"] == "bullish"
    assert reaction["follow_120m_pct"] > reaction["follow_30m_pct"] > 0
    assert reaction["dominant_move_pct"] >= reaction["follow_120m_pct"]
    assert reaction["anchor_delay_minutes"] == 0.0


def test_build_theme_temporal_evidence_reports_extended_followthrough(monkeypatch):
    now_dt = datetime.now().replace(second=0, microsecond=0)
    reactions = iter(
        [
            {
                "direction": "bullish",
                "return_pct": 0.08,
                "follow_30m_pct": 0.35,
                "follow_120m_pct": 0.92,
                "follow_360m_pct": 1.35,
                "dominant_move_pct": 1.42,
                "absorption_status": "not_fully_priced",
                "absorption_reason": "持续上行",
                "anchor_delay_minutes": 0.0,
            },
            {
                "direction": "bullish",
                "return_pct": 0.05,
                "follow_30m_pct": 0.22,
                "follow_120m_pct": 0.64,
                "follow_360m_pct": 0.88,
                "dominant_move_pct": 1.01,
                "absorption_status": "partially_absorbed",
                "absorption_reason": "涨幅部分兑现",
                "anchor_delay_minutes": 5.0,
            },
        ]
    )
    monkeypatch.setattr(api, "_estimate_price_reaction_around_time", lambda **kwargs: next(reactions))

    payload = api._build_theme_temporal_evidence(
        market="fx",
        code="AUDUSD",
        theme_news=[
            {
                "title": "澳洲联储偏鹰",
                "published_at": (now_dt - timedelta(hours=4)).isoformat(),
                "impact_direction": "bullish",
            },
            {
                "title": "美元回落",
                "published_at": (now_dt - timedelta(hours=2)).isoformat(),
                "impact_direction": "bullish",
            },
        ],
        frequency="5m",
    )

    assert payload["reaction_count"] == 2
    assert payload["alignment_rate"] == 1.0
    assert payload["avg_follow_120m_pct"] > payload["avg_follow_30m_pct"] > 0
    assert payload["avg_dominant_move_pct"] >= payload["avg_follow_120m_pct"]
    assert "2小时平均变动" in payload["summary"]
    assert "6小时主导波动均值" in payload["summary"]
    assert "6小时主导波动" in payload["enriched_news"][0]["reaction_summary"]


def test_build_market_research_context_contains_evidence_summary():
    context = api._build_market_research_context(
        news_list=[
            {
                "title": "欧元走强",
                "content": "欧元兑美元上涨，市场关注欧央行表态。",
                "published_at": "2026-04-04T09:00:00",
                "source": "jin10",
                "evidence_type": "direct",
                "impact_direction": "bullish",
            },
            {
                "title": "美联储官员讲话",
                "content": "美元波动加大，等待非农与利率路径。",
                "published_at": "2026-04-04T10:00:00",
                "source": "jin10",
                "evidence_type": "driver",
                "impact_direction": "bearish",
            },
        ],
        economic_data_list=[
            {
                "ds_mnemonic": "USCPI",
                "indicator_name": "美国CPI",
                "latest_value": 3.1,
                "previous_value": 3.3,
                "yoy_change_pct": -0.2,
                "units": "%",
            }
        ],
        current_market="fx",
        current_code="EURUSD",
        name="欧元美元",
        geopolitical_news=[
            {
                "metadata": {"title": "俄乌局势升级", "importance_score": 0.8},
                "geopolitical_topics": ["russia_ukraine"],
                "geopolitical_matched_terms": ["俄乌", "制裁"],
                "geopolitical_score": 3.0,
            }
        ],
    )

    assert "研究对象: 欧元美元" in context
    assert "- 直接相关: 1" in context
    assert "- 驱动相关: 1" in context
    assert "- 利多: 1" in context
    assert "- 利空: 1" in context
    assert "美国CPI(USCPI)" in context
    assert "地缘政治影响摘要:" in context
    assert "- 总体判断: 偏利空" in context
    assert "俄乌局势升级" in context
    assert "资产研究模板:" in context
    assert "研究重点:" in context
    assert "优先主线:" in context


def test_macro_analyst_node_normalizes_dict_factors(monkeypatch):
    from chanlun.tools import ai_analyse as ai_module

    search_queries = []
    llm_responses = iter(
        [
            '[{"factor":"美国CPI数据已公布超预期"},{"query":"美联储鹰派言论"}]',
            "宏观分析结论",
        ]
    )

    monkeypatch.setattr(api, "_call_ai_and_get_content", lambda *args, **kwargs: next(llm_responses))
    monkeypatch.setattr(ai_module, "AIAnalyse", lambda market: SimpleNamespace())
    monkeypatch.setattr(
        api,
        "get_vector_db",
        lambda db_path="./chroma_db": SimpleNamespace(
            semantic_search=lambda query, **kwargs: search_queries.append(query)
            or [{"document": f"{query} 历史背景", "metadata": {"title": query}}]
        ),
    )

    result = api.macro_analyst_node(
        {
            "current_code": "EURUSD",
            "current_market": "fx",
            "original_news": [
                {
                    "title": "欧元美元上涨",
                    "body": "美国CPI公布后美元波动，美联储表态偏鹰。",
                    "published_at": "2026-04-04T10:00:00",
                    "source": "jin10",
                }
            ],
        }
    )

    assert result["macro_analysis"] == "宏观分析结论"
    assert search_queries == ["美国CPI数据已公布超预期", "美联储鹰派言论"]


def test_enhanced_chief_strategist_adds_research_debate_sections(monkeypatch):
    from chanlun.tools import ai_analyse as ai_module

    llm_responses = iter(
        [
            "QUALITY_APPROVED: 分析质量合格，可以进行最终整合",
            "多头核心结论：趋势仍偏多。",
            "空头核心结论：短期存在回撤风险。",
            "最终立场: 看多\n裁决理由: 多头证据链更完整。",
            "风险等级: 中\n最可能导致判断失效的3个信号: 美元反抽、数据不及预期、联动失效\n风险经理结论: 不宜追高。",
            "## 综合摘要\n当前主线偏多。\n## 研究结论\n看多。",
        ]
    )

    monkeypatch.setattr(api, "_call_ai_and_get_content", lambda *args, **kwargs: next(llm_responses))
    monkeypatch.setattr(ai_module, "AIAnalyse", lambda market: SimpleNamespace())

    result = api.enhanced_chief_strategist_node(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "research_context": "新闻证据统计:\n- 直接相关: 2\n- 驱动相关: 1",
            "macro_analysis": "宏观偏多",
            "economic_analysis": "经济数据偏多",
            "technical_analysis": "技术结构偏多",
            "chanlun_analysis": "缠论结构偏多",
            "financial_analysis": "当前市场不是股票市场，无需进行财务分析",
            "geopolitical_analysis": "地缘风险中性",
            "scenario_route": {"label": "价格与新闻共振", "trigger": "欧元区通胀回落", "reason": "价格与直接新闻同步"},
            "reflection_memory": {"memory_text": "- 类似场景里要先看美元方向是否继续强化"},
            "quick_research": {"summary": "先用快评路径判断是否继续下破"},
            "deep_research": {"summary": "深研阶段继续调用宏观、技术与地缘节点"},
            "revision_count": 0,
        }
    )

    assert "🧭 **研究辩论与裁决**" in result["final_report"]
    assert "## 🟢 多头研究员结论" in result["final_report"]
    assert "## 🔴 空头研究员结论" in result["final_report"]
    assert "## ⚖️ 研究经理裁决" in result["final_report"]
    assert "## 🛡️ 风险经理结论" in result["final_report"]
    assert "## ⚡ 快评快照" in result["final_report"]
    assert "## 🧠 反思记忆" in result["final_report"]
    assert result["bullish_thesis"].startswith("多头核心结论")
    assert result["bearish_thesis"].startswith("空头核心结论")
    assert result["research_verdict"].startswith("最终立场")
    assert result["risk_assessment"].startswith("风险等级")


def test_search_geopolitical_news_uses_keyword_filter_and_db_fallback(monkeypatch):
    semantic_calls = []

    monkeypatch.setattr(
        api,
        "get_vector_db",
        lambda db_path="./chroma_db": SimpleNamespace(
            semantic_search=lambda **kwargs: semantic_calls.append(kwargs) or []
        ),
    )
    monkeypatch.setattr(
        api,
        "_search_news_from_relational_db",
        lambda query, search_terms, start_date, end_date, n_results: [
            {
                "document": "中东冲突升级引发避险情绪",
                "metadata": {
                    "news_id": f"id-{query}",
                    "title": f"{query} 导致市场波动",
                    "importance_score": 0.9,
                    "published_at": "2026-04-04T10:00:00",
                },
            }
        ],
    )

    result = api._search_geopolitical_news(days=7, asset_code="XAU", market="futures")

    assert result
    assert semantic_calls
    assert semantic_calls[0]["query"] == "中东 以色列 伊朗"
    assert "中东" in semantic_calls[0]["keywords"]
    assert "伊朗" in semantic_calls[0]["keywords"]
    assert any("战争" in item["metadata"]["title"] or "冲突" in item["document"] for item in result)


def test_search_geopolitical_news_prioritizes_asset_focus_topics(monkeypatch):
    semantic_calls = []

    monkeypatch.setattr(
        api,
        "get_vector_db",
        lambda db_path="./chroma_db": SimpleNamespace(
            semantic_search=lambda **kwargs: semantic_calls.append(kwargs) or []
        ),
    )
    monkeypatch.setattr(api, "_search_news_from_relational_db", lambda *args, **kwargs: [])

    api._search_geopolitical_news(days=7, asset_code="USDCNY", market="fx")

    assert len(semantic_calls) >= 3
    assert semantic_calls[0]["query"] == "中美 关税 制裁"
    assert semantic_calls[1]["query"] == "台海 台湾 军演"


def test_summarize_geopolitical_asset_impact_maps_asset_direction():
    summary = api._summarize_geopolitical_asset_impact(
        geopolitical_news=[
            {
                "metadata": {"title": "中东局势紧张", "importance_score": 0.6},
                "geopolitical_topics": ["middle_east"],
                "geopolitical_matched_terms": ["中东", "以色列"],
                "geopolitical_score": 4.0,
            },
            {
                "metadata": {"title": "俄乌冲突升级", "importance_score": 0.8},
                "geopolitical_topics": ["russia_ukraine"],
                "geopolitical_matched_terms": ["俄乌", "制裁"],
                "geopolitical_score": 4.0,
            },
        ],
        asset_code="XAU",
        market="futures",
    )

    assert summary["overall_direction"] == "bullish"
    assert summary["direction_counts"]["bullish"] == 2
    assert any("利多黄金" in line or "避险" in line for line in summary["detail_lines"])


def test_build_asset_search_plan_covers_usdcny_aliases():
    product_info = api._get_product_info("USDCNY")
    plan = api._build_asset_search_plan(
        query="USDCNY",
        product_code="USDCNY",
        market="fx",
        product_info=product_info,
        stock_info={},
    )

    assert plan["canonical_code"] == "USDCNY"
    assert "USDCNH" in plan["direct_terms"]
    assert "离岸人民币" in plan["direct_terms"]
    assert "中国人民银行" in plan["driver_terms"]
    assert "美联储" in plan["driver_terms"]


def test_infer_news_asset_links_identifies_usdcny_chain():
    links = api.infer_news_asset_links(
        title="美元兑离岸人民币上涨，市场关注中间价",
        body="交易员聚焦中国人民银行、PBOC 和美联储后续表态，USDCNH 波动扩大。",
    )

    assert "USDCNY" in links["direct_assets"]
    assert "USDCNY" in links["driver_assets"] or "CNY" in links["driver_assets"]
    assert "PBOC" in links["matched_terms"] or "中国人民银行" in links["matched_terms"]


def test_build_asset_link_rows_creates_direct_and_driver_rows():
    rows = api.build_asset_link_rows(
        news_id="n1",
        title="美元兑离岸人民币上涨",
        body="交易员关注中国人民银行和美联储后续动作，USDCNH 波动扩大。",
    )

    relation_types = {row["relation_type"] for row in rows}
    canonical_assets = {row["canonical_asset"] for row in rows}
    assert "direct" in relation_types
    assert "driver" in relation_types
    assert "USDCNY" in canonical_assets


def test_infer_asset_impact_direction_for_usdcny():
    direction = api.infer_asset_impact_direction(
        title="美元兑离岸人民币上涨，人民币走弱",
        body="USDCNH 继续走高，市场关注中间价。",
        canonical_asset="USDCNY",
    )
    assert direction["impact_direction"] == "bullish"

    direction = api.infer_asset_impact_direction(
        title="人民币升值，美元兑在岸人民币回落",
        body="USDCNY 下跌，离岸人民币走强。",
        canonical_asset="USDCNY",
    )
    assert direction["impact_direction"] == "bearish"


def test_merge_search_batches_prioritizes_direct_hits():
    direct_result = {
        "id": "n1",
        "document": "美元兑离岸人民币走弱",
        "metadata": {"news_id": "n1", "published_at": "2026-04-04T10:00:00"},
        "score": 10.0,
    }
    macro_result = {
        "id": "n2",
        "document": "美联储官员讲话影响美元",
        "metadata": {"news_id": "n2", "published_at": "2026-04-04T11:00:00"},
        "score": 15.0,
    }

    merged = api._merge_search_batches(
        [
            {"stage": "driver", "bonus": 4.0, "results": [macro_result]},
            {"stage": "direct", "bonus": 18.0, "results": [direct_result]},
        ],
        n_results=5,
    )

    assert merged[0]["metadata"]["news_id"] == "n1"
    assert "direct" in merged[0]["search_stages"]


def test_bucket_news_evidence_groups_by_asset_relation():
    news_list = [
        {
            "id": "n1",
            "document": "直接新闻",
            "metadata": {"news_id": "n1", "direct_assets": ["USDCNY"], "driver_assets": []},
            "score": 20,
        },
        {
            "id": "n2",
            "document": "驱动新闻",
            "metadata": {"news_id": "n2", "direct_assets": [], "driver_assets": ["USDCNY"]},
            "score": 15,
        },
        {
            "id": "n3",
            "document": "背景新闻",
            "metadata": {"news_id": "n3", "direct_assets": [], "driver_assets": []},
            "score": 10,
        },
    ]

    buckets = api._bucket_news_evidence(news_list, "USDCNY")
    assert [item["metadata"]["news_id"] for item in buckets["direct"]] == ["n1"]
    assert [item["metadata"]["news_id"] for item in buckets["driver"]] == ["n2"]
    assert [item["metadata"]["news_id"] for item in buckets["background"]] == ["n3"]


def test_backfill_news_asset_links_replaces_rows(monkeypatch):
    replaced = []

    def fake_news_query(limit, start_date=None, end_date=None):
        return [
            SimpleNamespace(id=1, news_id="n1", title="美元兑离岸人民币上涨", body="PBOC 和 USDCNH 受关注"),
            SimpleNamespace(id=2, news_id="n2", title="普通宏观新闻", body="暂无资产别名"),
        ]

    monkeypatch.setattr(api.db, "news_query", fake_news_query)
    monkeypatch.setattr(
        api.db,
        "news_asset_links_replace",
        lambda news_id, asset_links: replaced.append((news_id, asset_links)) or True,
    )

    result = api._backfill_news_asset_links(limit=20, days=30)

    assert result["processed"] == 2
    assert result["linked_news"] >= 1
    assert replaced[0][0] == "n1"
    assert any(link["canonical_asset"] == "USDCNY" for link in replaced[0][1])


def test_build_asset_news_response_groups_buckets(monkeypatch):
    direct_row = SimpleNamespace(news_id="n1", confidence=0.95, reason="直接命中", matched_terms="USDCNH", relation_type="direct")
    driver_row = SimpleNamespace(news_id="n2", confidence=0.72, reason="驱动命中", matched_terms="PBOC", relation_type="driver")
    news_map = {
        "n1": SimpleNamespace(
            id=1, news_id="n1", title="美元兑离岸人民币上涨", body="USDCNH 快讯", source="jin10",
            category="fx", sentiment_score=0.0, importance_score=0.8, language="zh",
            story_id="n1", tags="", published_at=None,
        ),
        "n2": SimpleNamespace(
            id=2, news_id="n2", title="中国人民银行设定中间价", body="PBOC 新闻", source="jin10",
            category="fx", sentiment_score=0.0, importance_score=0.6, language="zh",
            story_id="n2", tags="", published_at=None,
        ),
    }

    def fake_links_query(canonical_asset=None, relation_type=None, news_ids=None, limit=500):
        if relation_type == "direct":
            return [direct_row]
        if relation_type == "driver":
            return [driver_row]
        return []

    monkeypatch.setattr(api.db, "news_asset_links_query", fake_links_query)
    monkeypatch.setattr(api.db, "news_get_by_id", lambda news_id: news_map.get(news_id))
    monkeypatch.setattr(
        api,
        "_search_news_from_relational_db",
        lambda *args, **kwargs: [
            {
                "id": "n3",
                "document": "美元指数回落",
                "metadata": {"news_id": "n3", "title": "美元指数回落", "direct_assets": [], "driver_assets": []},
                "score": 10.0,
            }
        ],
    )

    result = api._build_asset_news_response("USDCNY", "fx", days=7, limit=10)

    assert result["counts"]["direct"] == 1
    assert result["counts"]["driver"] == 1
    assert result["counts"]["background"] == 1
    assert result["buckets"]["direct"][0]["relation_type"] == "direct"
    assert result["buckets"]["driver"][0]["relation_type"] == "driver"


def test_bucket_news_evidence_adds_direction():
    buckets = api._bucket_news_evidence(
        [
            {
                "id": "n1",
                "document": "美元兑离岸人民币上涨，人民币走弱",
                "metadata": {
                    "news_id": "n1",
                    "title": "美元兑离岸人民币上涨",
                    "direct_assets": ["USDCNY"],
                    "driver_assets": [],
                },
                "score": 10.0,
            }
        ],
        "USDCNY",
    )
    assert buckets["direct"][0]["impact_direction"] == "bullish"


def test_build_realtime_focus_payload_combines_price_and_news(monkeypatch):
    monkeypatch.setattr(timesfm_service, "_timesfm_predict_native", lambda model_input: {"available": False, "reason": "native disabled for unit test"})
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: api._default_event_topic_definitions())
    monkeypatch.setattr(
        api.db,
        "market_summary_query",
        lambda **kwargs: [
            SimpleNamespace(
                id=1,
                title="欧元美元历史分析",
                content="过去类似场景提示要先看美元方向和价格延续是否一致。",
                summary_type="historical_analysis",
                created_at=base_dt - timedelta(days=1),
            )
        ],
    )

    monkeypatch.setattr(
        api,
        "_get_product_info",
        lambda code, market: {"name_cn": "欧元美元", "type": "forex"},
    )
    monkeypatch.setattr(
        api,
        "get_exchange",
        lambda market: SimpleNamespace(stock_info=lambda code: {"name": "欧元/美元"}),
    )
    monkeypatch.setattr(
        api,
        "get_vector_news",
        lambda *args, **kwargs: [
            {
                "id": "n1",
                "document": "欧元区通胀回落，欧元承压。",
                "metadata": {
                    "news_id": "n1",
                    "title": "欧元区通胀回落",
                    "published_at": (base_dt + timedelta(minutes=5)).isoformat(),
                    "importance_score": 0.82,
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                },
                "impact_direction": "bearish",
                "direction_reason": "利空欧元",
            },
            {
                "id": "n2",
                "document": "美元指数上行，风险偏好回落。",
                "metadata": {
                    "news_id": "n2",
                    "title": "美元指数上行",
                    "published_at": (base_dt + timedelta(minutes=10)).isoformat(),
                    "importance_score": 0.64,
                    "direct_assets": [],
                    "driver_assets": ["EURUSD"],
                },
                "impact_direction": "bearish",
                "direction_reason": "美元走强压制欧元",
            },
        ],
    )
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda market, code, frequency, lookback_hours, purpose=None: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.1000 - idx * 0.0008,
                "close": 1.0995 - idx * 0.0009,
                "high": 1.1003 - idx * 0.0007,
                "low": 1.0990 - idx * 0.0010,
                "volume": 1000 + idx,
            }
            for idx in range(12)
        ],
    )
    monkeypatch.setattr(
        api,
        "_detect_price_events",
        lambda *args, **kwargs: [
            {
                "event_time": base_dt + timedelta(minutes=55),
                "return_pct": -0.52,
                "range_pct": 0.68,
                "direction": "bearish",
            }
        ],
    )

    payload = api._build_realtime_focus_payload("fx", "EURUSD", "1h")

    assert payload["asset"]["code"] == "EURUSD"
    assert payload["alert_level"] == "high"
    assert payload["price_state"]["status_label"] == "价格快速异动"
    assert payload["direct_news"][0]["title"] == "欧元区通胀回落"
    assert payload["driver_news"][0]["title"] == "美元指数上行"
    assert len(payload["cross_asset_watch"]) >= 1
    assert payload["cross_asset_watch"][0]["code"] in {"USDJPY", "USDCNH", "XAU"}
    assert payload["cross_asset_summary"]
    assert payload["urgent_alert"]["enabled"] is True
    assert payload["urgent_alert"]["cause_type"] == "direct_news"
    assert payload["urgent_alert"]["cause_title"] == "欧元区通胀回落"
    assert payload["scenario_route"]["route"] == "price_news_resonance"
    assert payload["quick_research"]["mode"] == "quick"
    assert payload["deep_research"]["mode"] == "deep"
    assert payload["risk_brief"]["level"] == "high"
    assert "价格与新闻共振" in payload["quick_research"]["summary"]
    assert payload["reflection_memory"]["items"][0]["summary_type"] == "historical_analysis"
    assert payload["alerts"][0]["category"] in {"price", "direct_news"}
    assert payload["timesfm_frequency"] == "60m"
    assert payload["timesfm_forecast"]["forecast_primary"]["frequency"] == "60m"
    assert payload["timesfm_forecast"]["forecast_30m"]["summary"]
    assert payload["topic_timeline"][0]["topic_label"] in {"通胀数据", "宏观数据", "美联储官员讲话"}
    assert payload["topic_timeline"][0]["asset_performance"][0]["code"] == "EURUSD"
    assert payload["topic_timeline"][0]["asset_performance"][0]["role"] == "当前资产"


def test_timesfm_service_returns_native_unavailable_bundle_and_uses_cache(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(timesfm_service.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(timesfm_service.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(timesfm_service, "_timesfm_predict_native", lambda model_input: {"available": False, "reason": "native disabled for unit test"})
    monkeypatch.setattr(
        timesfm_service,
        "get_timesfm_native_runtime_status",
        lambda force_refresh=False: {"available": False, "reason": "native disabled for unit test", "checked_at": 0.0, "meta": {}},
    )

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1000 + idx * 0.0002,
            "close": 1.1002 + idx * 0.00025,
            "high": 1.1004 + idx * 0.00025,
            "low": 1.0998 + idx * 0.0002,
            "volume": 1000 + idx,
        }
        for idx in range(40)
    ]

    bundle = timesfm_service.generate_timesfm_forecast_bundle(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        horizons=[1, 4],
        covariates={"news_bias_score": 0.2},
    )

    second = timesfm_service.generate_timesfm_forecast_bundle(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        horizons=[1, 4],
        covariates={"news_bias_score": 0.2},
    )

    assert bundle["available"] is False
    assert bundle["degraded"] is False
    assert bundle["backend"] == "timesfm_native_unavailable"
    assert bundle["forecast_primary"]["horizon_label"] == "5分钟"
    assert bundle["forecast_secondary"]["horizon_label"] == "20分钟"
    assert bundle["forecast_primary"]["point_forecast_price_path"] == []
    assert bundle["backend_details"]["xreg_used"] is False
    assert bundle["backend_details"]["native_enabled"] is False
    assert "native disabled for unit test" in bundle["backend_details"]["native_message"]
    assert bundle["forecast_30m"]["summary"]
    assert bundle["forecast_120m"]["summary"]
    assert second["forecast_30m"]["source"] == "timesfm_cache"


def test_load_native_timesfm_model_falls_back_when_from_pretrained_rejects_proxies():
    captured = {}

    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_name):
            raise TypeError("TimesFM_2p5_200M_torch.__init__() got an unexpected keyword argument 'proxies'")

        @classmethod
        def _from_pretrained(cls, **kwargs):
            captured.update(kwargs)
            return {"backend": "compat_loader"}

    result = timesfm_service._load_native_timesfm_model(FakeModel, "google/timesfm-2.5-200m-pytorch")

    assert result["backend"] == "compat_loader"
    assert captured["model_id"] == "google/timesfm-2.5-200m-pytorch"
    assert captured["local_files_only"] is False
    assert "config" in captured


def test_load_native_timesfm_model_uses_from_pretrained_when_available():
    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_name):
            return {"model_name": model_name, "route": "from_pretrained"}

    result = timesfm_service._load_native_timesfm_model(FakeModel, "google/timesfm-2.5-200m-pytorch")

    assert result["route"] == "from_pretrained"
    assert result["model_name"] == "google/timesfm-2.5-200m-pytorch"


def test_timesfm_service_refreshes_stale_proxy_cache_when_native_recovers(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(timesfm_service.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(timesfm_service.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        timesfm_service,
        "get_timesfm_native_runtime_status",
        lambda force_refresh=False: {"available": True, "reason": "", "checked_at": 0.0, "meta": {}},
    )

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1000 + idx * 0.0002,
            "close": 1.1002 + idx * 0.00025,
            "high": 1.1004 + idx * 0.00025,
            "low": 1.0998 + idx * 0.0002,
            "volume": 1000 + idx,
        }
        for idx in range(40)
    ]
    model_input = timesfm_service.build_timesfm_input(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        horizon_bars=1,
        context_length=40,
        covariates={"news_bias_score": 0.2},
    )
    cache_key = timesfm_service._build_forecast_cache_key(model_input)
    cache_store[cache_key] = {
        "available": True,
        "backend": "timesfm_proxy",
        "source": "timesfm_proxy",
        "degraded": True,
        "summary": "stale proxy forecast",
        "native_status": {
            "enabled": False,
            "backend": "timesfm_proxy",
            "message": "cached before native runtime recovered",
        },
    }

    monkeypatch.setattr(
        timesfm_service,
        "_timesfm_predict_native",
        lambda payload: {
            "available": True,
            "backend": "timesfm_native",
            "source": "timesfm_native",
            "degraded": False,
            "summary": "fresh native forecast",
            "horizon_label": "5分钟",
            "frequency": "5m",
            "context_length": payload["context_length"],
            "context_end": payload["context_end"],
            "native_model": "google/timesfm-2.5-200m-pytorch",
            "native_model_source": "local_repo",
            "native_module_file": "/tmp/timesfm/__init__.py",
            "xreg_used": False,
        },
    )

    result = timesfm_service.predict_timesfm(model_input, use_cache=True)

    assert result["backend"] == "timesfm_native"
    assert result["source"] == "timesfm_native"
    assert result["native_status"]["enabled"] is True
    assert cache_store[cache_key]["backend"] == "timesfm_native"


def test_timesfm_service_generates_native_bundle(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(timesfm_service.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(timesfm_service.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(timesfm_service.importlib.util, "find_spec", lambda name: object() if name == "jax" else None)

    class FakeNativeModel:
        def forecast_with_covariates(self, inputs, dynamic_numerical_covariates=None, static_numerical_covariates=None, static_categorical_covariates=None, **kwargs):
            point = [[[1.2050], [1.2060], [1.2070], [1.2080]]]
            quantile = [[
                [1.2050, 1.2040, 1.2044, 1.2046, 1.2048, 1.2050, 1.2052, 1.2054, 1.2056, 1.2060],
                [1.2060, 1.2050, 1.2053, 1.2056, 1.2058, 1.2060, 1.2062, 1.2064, 1.2066, 1.2070],
                [1.2070, 1.2060, 1.2063, 1.2066, 1.2068, 1.2070, 1.2072, 1.2074, 1.2076, 1.2080],
                [1.2080, 1.2070, 1.2073, 1.2076, 1.2078, 1.2080, 1.2082, 1.2084, 1.2086, 1.2090],
            ]]
            return point, quantile

    monkeypatch.setattr(
        timesfm_service,
        "_get_native_model",
        lambda: (FakeNativeModel(), {"model_name": "google/timesfm-2.5-200m-pytorch", "module_source": "local_repo", "module_file": "/tmp/timesfm/__init__.py"}),
    )

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=15 * idx),
            "open": 1.1900 + idx * 0.0005,
            "close": 1.2000 + idx * 0.0008,
            "high": 1.2005 + idx * 0.0008,
            "low": 1.1995 + idx * 0.0007,
            "volume": 1000 + idx,
        }
        for idx in range(32)
    ]

    bundle = timesfm_service.generate_timesfm_forecast_bundle(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="15m",
        horizons=[1, 4],
        covariates={
            "use_event_covariates": True,
            "use_price_covariates": True,
            "news_bias_score": 0.2,
            "route": "news_catalyst",
            "direct_news_count": 2,
            "driver_news_count": 1,
        },
    )

    assert bundle["available"] is True
    assert bundle["backend"] == "timesfm_native_xreg"
    assert bundle["backend_details"]["xreg_used"] is True
    assert bundle["backend_details"]["native_enabled"] is True
    assert bundle["backend_details"]["native_message"] == ""
    assert bundle["backend_details"]["native_model"] == "google/timesfm-2.5-200m-pytorch"
    assert bundle["backend_details"]["target_series_field"] == "close"
    assert bundle["backend_details"]["price_covariates_used"] is True
    assert "ohlcv_open_gap_pct" in bundle["backend_details"]["price_covariate_fields"]
    assert bundle["forecast_primary"]["native_model_source"] == "local_repo"
    assert bundle["forecast_primary"]["quantile_forecast_price_path"]["p10"]
    assert bundle["forecast_secondary"]["display_band"]


def test_timesfm_service_trims_backcast_from_native_forecast(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(timesfm_service.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(timesfm_service.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(timesfm_service.importlib.util, "find_spec", lambda name: None)

    class FakeNativeModel:
        def forecast(self, horizon, inputs):
            point = [[[0.055], [0.056], [0.057], [1.205], [1.206], [1.207], [1.208]]]
            quantile = [[
                [0.055, 0.054, 0.0542, 0.0544, 0.0546, 0.0550, 0.0552, 0.0554, 0.0556, 0.0560],
                [0.056, 0.055, 0.0552, 0.0554, 0.0556, 0.0560, 0.0562, 0.0564, 0.0566, 0.0570],
                [0.057, 0.056, 0.0562, 0.0564, 0.0566, 0.0570, 0.0572, 0.0574, 0.0576, 0.0580],
                [1.205, 1.204, 1.2042, 1.2044, 1.2046, 1.2050, 1.2052, 1.2054, 1.2056, 1.2060],
                [1.206, 1.205, 1.2052, 1.2054, 1.2056, 1.2060, 1.2062, 1.2064, 1.2066, 1.2070],
                [1.207, 1.206, 1.2062, 1.2064, 1.2066, 1.2070, 1.2072, 1.2074, 1.2076, 1.2080],
                [1.208, 1.207, 1.2072, 1.2074, 1.2076, 1.2080, 1.2082, 1.2084, 1.2086, 1.2090],
            ]]
            return point, quantile

    monkeypatch.setattr(
        timesfm_service,
        "_get_native_model",
        lambda: (FakeNativeModel(), {"model_name": "google/timesfm-2.5-200m-pytorch", "module_source": "local_repo", "module_file": "/tmp/timesfm/__init__.py"}),
    )

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1900 + idx * 0.0005,
            "close": 1.2000 + idx * 0.0008,
            "high": 1.2005 + idx * 0.0008,
            "low": 1.1995 + idx * 0.0007,
            "volume": 1000 + idx,
        }
        for idx in range(32)
    ]

    bundle = timesfm_service.generate_timesfm_forecast_bundle(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        horizons=[1, 4],
        covariates={},
    )

    assert bundle["backend"] == "timesfm_native"
    assert bundle["forecast_primary"]["expected_price"] > 1.0
    assert abs(bundle["forecast_primary"]["expected_return_pct"]) < 5.0
    assert bundle["forecast_primary"]["quantiles_pct"]["p50"] > -5.0


def test_build_timesfm_input_adds_ohlcv_covariates_when_enabled():
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1000 + idx * 0.0002,
            "close": 1.1003 + idx * 0.00025,
            "high": 1.1006 + idx * 0.00025,
            "low": 1.0998 + idx * 0.0002,
            "volume": 1000 + idx * 5,
        }
        for idx in range(24)
    ]

    model_input = timesfm_service.build_timesfm_input(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        horizon_bars=4,
        context_length=20,
        covariates={"use_price_covariates": True},
    )

    assert model_input["price_covariates_enabled"] is True
    assert model_input["price_covariate_projection_method"] == "recent_profile_carry_forward"
    assert "ohlcv_open_gap_pct" in model_input["price_covariate_feature_names"]
    assert len(model_input["price_dynamic_covariates"]["ohlcv_open_gap_pct"][0]) == 24
    assert len(model_input["price_dynamic_covariates"]["ohlcv_volume_ratio"][0]) == 24
    assert model_input["price_covariate_digest"]


def test_generate_timesfm_forecast_payload_refreshes_stale_cache_when_native_recovers(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        api,
        "get_timesfm_native_runtime_status",
        lambda force_refresh=False: {"available": True, "reason": "", "checked_at": 0.0, "meta": {}},
    )
    monkeypatch.setattr(api, "_load_historical_price_bars", lambda **kwargs: [{"dt": datetime(2026, 4, 4, 9, 0, 0), "close": 1.2}] * 12)
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: {
            "backend": "timesfm_native",
            "summary": "fresh native payload",
            "backend_details": {"native_enabled": True, "native_message": "", "xreg_used": False},
        },
    )

    payload = api._normalize_timesfm_request({"current_market": "fx", "current_code": "EURUSD", "frequency": "5m"})
    api._save_summary_result_cache(
        "timesfm_forecast",
        payload,
        {
            "backend": "timesfm_proxy",
            "summary": "stale cached payload",
            "backend_details": {"native_enabled": False, "native_message": "stale proxy cache"},
        },
    )

    result = api._generate_timesfm_forecast_payload(payload)

    assert result["cache_hit"] is False
    assert result["backend"] == "timesfm_native"
    assert result["backend_details"]["native_enabled"] is True


def test_build_event_forecast_respects_requested_context_length(monkeypatch):
    captured = {"context_length": None}
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1 + idx * 0.0002,
            "close": 1.1002 + idx * 0.00025,
            "high": 1.1004 + idx * 0.00025,
            "low": 1.0998 + idx * 0.0002,
            "volume": 1000 + idx,
        }
        for idx in range(40)
    ]
    monkeypatch.setattr(
        timesfm_service,
        "generate_timesfm_forecast_bundle",
        lambda **kwargs: captured.__setitem__("context_length", kwargs.get("context_length")) or {
            "available": True,
            "forecast_primary": {"horizon_label": "5分钟", "expected_return_pct": 0.1},
            "forecast_secondary": {"horizon_label": "20分钟", "expected_return_pct": 0.2},
            "forecast_30m": {"horizon_label": "5分钟", "expected_return_pct": 0.1},
            "forecast_120m": {"horizon_label": "20分钟", "expected_return_pct": 0.2},
        },
    )

    result = timesfm_service.build_event_forecast(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        event_time=base_dt + timedelta(minutes=60),
        actual_follow_primary_pct=0.12,
        actual_follow_secondary_pct=0.25,
        context_length=24,
    )

    assert captured["context_length"] == 13
    assert result["primary_label"] == "5分钟"


def test_timesfm_native_runtime_smoke(monkeypatch):
    if os.getenv("RUN_TIMESFM_NATIVE_SMOKE") != "1":
        pytest.skip("设置 RUN_TIMESFM_NATIVE_SMOKE=1 后执行原生 TimesFM 烟雾验证")

    cache_store = {}
    monkeypatch.setattr(timesfm_service.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(timesfm_service.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)

    status = timesfm_service.get_timesfm_native_runtime_status(force_refresh=True)
    assert status["available"] is True, status.get("reason", "")

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1000 + idx * 0.0002,
            "close": 1.1002 + idx * 0.00025,
            "high": 1.1004 + idx * 0.00025,
            "low": 1.0998 + idx * 0.0002,
            "volume": 1000 + idx,
        }
        for idx in range(48)
    ]

    bundle = timesfm_service.generate_timesfm_forecast_bundle(
        price_bars=price_bars,
        market="fx",
        code="EURUSD",
        frequency="5m",
        horizons=[1, 4],
        covariates={"news_bias_score": 0.15, "route": "news_catalyst", "direct_news_count": 1, "driver_news_count": 1},
    )

    assert bundle["backend_details"]["native_enabled"] is True, bundle["backend_details"].get("native_message", "")
    assert bundle["backend"] in {"timesfm_native", "timesfm_native_xreg"}
    assert bundle["forecast_primary"]["point_forecast_price_path"]


def test_generate_timesfm_forecast_payload_uses_cache(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(timesfm_service, "_timesfm_predict_native", lambda model_input: {"available": False, "reason": "native disabled for unit test"})
    monkeypatch.setattr(
        api,
        "get_timesfm_native_runtime_status",
        lambda force_refresh=False: {"available": False, "reason": "native disabled for unit test", "checked_at": 0.0, "meta": {}},
    )
    monkeypatch.setattr(
        timesfm_service,
        "get_timesfm_native_runtime_status",
        lambda force_refresh=False: {"available": False, "reason": "native disabled for unit test", "checked_at": 0.0, "meta": {}},
    )

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda market, code, frequency, lookback_hours, purpose=None: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.1 + idx * 0.0002,
                "close": 1.1002 + idx * 0.00025,
                "high": 1.1004 + idx * 0.00025,
                "low": 1.0998 + idx * 0.0002,
                "volume": 1000 + idx,
            }
            for idx in range(30)
        ],
    )

    first = api._generate_timesfm_forecast_payload(
        {"current_market": "fx", "current_code": "EURUSD", "frequency": "1d"}
    )
    second = api._generate_timesfm_forecast_payload(
        {"current_market": "fx", "current_code": "EURUSD", "frequency": "1d"}
    )

    assert first["forecast_30m"]["summary"]
    assert first["cache_hit"] is False
    assert first["frequency"] == "d"
    assert first["forecast_primary"]["horizon_label"] == "1日"
    assert first["forecast_secondary"]["horizon_label"] == "4日"
    assert first["backend_details"]["native_enabled"] is False
    assert "native disabled for unit test" in first["backend_details"]["native_message"]
    assert first["selected_forecast_mode"] in {"pure_price", "price_event_covariates"}
    assert first["selected_forecast_mode_label"] in {"纯价格", "价格+协变量"}
    assert len(first["forecast_mode_results"]) == 2
    assert len(first["mode_comparison"]) == 2
    assert {item["mode_key"] for item in first["mode_comparison"]} == {"pure_price", "price_event_covariates"}
    assert first["input_snapshot"]["price_window"]["context_length"] >= 10
    assert first["input_snapshot"]["price_window"]["recent_closes"]
    assert first["visual_chart"]["observed"]
    assert first["visual_chart"]["forecast_primary"]
    assert first["visual_chart"]["forecast_primary_band"]["p10"]
    assert first["visual_chart"]["forecast_30m"]
    assert second["cache_hit"] is True
    assert second["forecast_30m"]["summary"]


def test_generate_timesfm_forecast_payload_respects_requested_context_length(monkeypatch):
    cache_store = {}
    captured = {"context_length": None}
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(api, "_load_historical_price_bars", lambda **kwargs: [{"dt": datetime(2026, 4, 4, 9, 0, 0), "close": 1.2}] * 20)
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: captured.__setitem__("context_length", kwargs.get("context_length")) or {
            "backend": "timesfm_native_unavailable",
            "summary": "ok",
            "forecast_primary": {"summary": "primary"},
            "forecast_secondary": {"summary": "secondary"},
            "forecast_30m": {"summary": "primary"},
            "forecast_120m": {"summary": "secondary"},
            "backend_details": {"native_enabled": False, "native_message": "", "xreg_used": False},
            "input_snapshot": {"price_window": {"context_length": kwargs.get("context_length")}},
            "visual_chart": {"observed": [], "forecast_primary": [], "forecast_primary_band": {"p10": []}, "forecast_30m": []},
        },
    )

    result = api._generate_timesfm_forecast_payload(
        {"current_market": "fx", "current_code": "EURUSD", "frequency": "5m", "context_length": 64}
    )

    assert captured["context_length"] == 64
    assert result["cache_hit"] is False


def test_build_timesfm_forecast_exposes_dual_modes(monkeypatch):
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    price_bars = [
        {
            "dt": base_dt + timedelta(minutes=5 * idx),
            "open": 1.1 + idx * 0.0002,
            "close": 1.1002 + idx * 0.00025,
            "high": 1.1004 + idx * 0.00025,
            "low": 1.0998 + idx * 0.0002,
            "volume": 1000 + idx,
        }
        for idx in range(36)
    ]

    def fake_bundle(**kwargs):
        covariates = kwargs.get("covariates") or {}
        xreg_used = bool(covariates)
        continuation_secondary = 0.78 if xreg_used else 0.58
        backend = "timesfm_native_xreg" if xreg_used else "timesfm_native"
        return {
            "available": True,
            "backend": backend,
            "summary": "mode summary",
            "forecast_primary": {
                "summary": "primary",
                "direction": "bullish",
                "continuation_probability": 0.66 if xreg_used else 0.55,
                "forecast_confidence": "high" if xreg_used else "medium",
                "uncertainty_level": "low" if xreg_used else "medium",
                "horizon_label": "5分钟",
                "display_band": "[0.1%,0.3%]",
            },
            "forecast_secondary": {
                "summary": "secondary",
                "direction": "bullish",
                "continuation_probability": continuation_secondary,
                "forecast_confidence": "high" if xreg_used else "medium",
                "uncertainty_level": "low" if xreg_used else "medium",
                "horizon_label": "20分钟",
                "display_band": "[0.2%,0.6%]",
            },
            "forecast_30m": {
                "summary": "primary",
                "direction": "bullish",
                "continuation_probability": 0.66 if xreg_used else 0.55,
                "forecast_confidence": "high" if xreg_used else "medium",
                "uncertainty_level": "low" if xreg_used else "medium",
            },
            "forecast_120m": {
                "summary": "secondary",
                "direction": "bullish",
                "continuation_probability": continuation_secondary,
                "forecast_confidence": "high" if xreg_used else "medium",
                "uncertainty_level": "low" if xreg_used else "medium",
            },
            "backend_details": {
                "native_enabled": True,
                "native_message": "",
                "xreg_used": xreg_used,
            },
        }

    monkeypatch.setattr(api, "generate_timesfm_forecast_bundle", fake_bundle)

    result = api._build_timesfm_forecast(
        current_market="fx",
        current_code="EURUSD",
        frequency="5m",
        price_bars=price_bars,
        price_state={"change_30m_pct": 0.3},
        direct_news=[{"title": "usd"}],
        driver_news=[{"title": "yield"}],
        cross_asset_watch={"summary": "risk-on"},
        scenario_route={"route": "trend_follow"},
    )

    assert result["selected_forecast_mode"] == "price_event_covariates"
    assert result["selected_forecast_mode_label"] == "价格+协变量"
    assert len(result["forecast_mode_results"]) == 2
    assert len(result["mode_comparison"]) == 2
    assert result["summary"].startswith("当前主模式为价格+协变量，")
    assert result["mode_comparison"][0]["mode_key"] in {"pure_price", "price_event_covariates"}
    enhanced_mode = next(item for item in result["forecast_mode_results"] if item["forecast_mode"] == "price_event_covariates")
    pure_mode = next(item for item in result["forecast_mode_results"] if item["forecast_mode"] == "pure_price")
    assert enhanced_mode["backend_details"]["xreg_used"] is True
    assert pure_mode["backend_details"]["xreg_used"] is False
    assert enhanced_mode["covariates"]["use_price_covariates"] is True
    assert result["input_snapshot"]["model_design"]["target_series_field"] == "close"
    assert result["input_snapshot"]["model_design"]["dynamic_price_covariates_enabled"] is True
    assert result["input_snapshot"]["price_window"]["recent_ohlcv"]
    assert result["trade_plan"]["action"] in {"long", "watch_long", "no_trade"}
    assert result["trade_plan"]["summary"]


def test_timesfm_native_result_raises_probability_for_stable_small_5m_trend():
    series = [100.0 + idx * 0.01 for idx in range(40)]
    latest_price = series[-1]
    result = timesfm_service._build_native_result(
        model_input={
            "series": series,
            "market": "fx",
            "code": "EURUSD",
            "frequency": "5m",
            "horizon_bars": 1,
            "context_length": len(series),
            "context_end": "2026-04-05T10:00:00",
        },
        point_prices=[latest_price * 1.00012],
        quantile_prices={
            "mean": [latest_price * 1.00012],
            "p10": [latest_price * 1.00006],
            "p50": [latest_price * 1.00012],
            "p90": [latest_price * 1.00018],
        },
        backend="timesfm_native",
        backend_meta={},
        xreg_used=False,
    )

    assert result["direction"] == "bullish"
    assert result["continuation_probability"] >= 0.7
    assert result["baseline_move_pct"] > 0
    assert result["path_consistency"] >= 0.99
    assert result["quantile_consensus"] >= 0.99


def test_timesfm_native_result_keeps_probability_conservative_when_quantiles_are_unclear():
    series = [100.0 + idx * 0.01 for idx in range(40)]
    latest_price = series[-1]
    result = timesfm_service._build_native_result(
        model_input={
            "series": series,
            "market": "fx",
            "code": "EURUSD",
            "frequency": "5m",
            "horizon_bars": 1,
            "context_length": len(series),
            "context_end": "2026-04-05T10:00:00",
        },
        point_prices=[latest_price * 1.00001],
        quantile_prices={
            "mean": [latest_price * 1.00001],
            "p10": [latest_price * 0.9995],
            "p50": [latest_price * 1.00001],
            "p90": [latest_price * 1.0004],
        },
        backend="timesfm_native",
        backend_meta={},
        xreg_used=False,
    )

    assert result["direction"] == "neutral"
    assert result["continuation_probability"] <= 0.58
    assert result["uncertainty_level"] in {"medium", "high"}


def test_generate_timesfm_event_forecast_payload_builds_event_comparison(monkeypatch):
    cache_store = {}
    monkeypatch.setattr(api.db, "cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: cache_store.__setitem__(key, val) or True)
    monkeypatch.setattr(timesfm_service, "_timesfm_predict_native", lambda model_input: {"available": False, "reason": "native disabled for unit test"})

    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda market, code, frequency, lookback_hours, purpose=None: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.1 + idx * 0.0002,
                "close": 1.1002 + idx * 0.00025,
                "high": 1.1004 + idx * 0.00025,
                "low": 1.0998 + idx * 0.0002,
                "volume": 1000 + idx,
            }
            for idx in range(40)
        ],
    )

    result = api._generate_timesfm_event_forecast_payload(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "frequency": "5m",
            "event_time": (base_dt + timedelta(minutes=90)).isoformat(),
            "actual_follow_30m_pct": -0.32,
            "actual_follow_120m_pct": -0.61,
        }
    )

    assert result["event_time"]
    assert result["available"] is False
    assert result["backend"] == "timesfm_native_unavailable"
    assert "native disabled for unit test" in result["summary"]


def test_generate_timesfm_review_payload_backtests_price_events(monkeypatch):
    base_dt = datetime(2026, 4, 5, 9, 0, 0)
    captured = {"load_frequency": None, "forecast_calls": []}
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda **kwargs: captured.__setitem__("load_frequency", kwargs.get("frequency")) or [
            {
                "dt": base_dt + timedelta(hours=idx),
                    "open": 1.1 + idx * 0.0015,
                    "close": 1.101 + idx * 0.002,
                    "high": 1.1015 + idx * 0.002,
                    "low": 1.0995 + idx * 0.0015,
                "volume": 1000 + idx,
            }
            for idx in range(80)
        ],
    )
    monkeypatch.setattr(
        api,
        "_detect_price_events",
        lambda **kwargs: [
            {
                "trigger_dt": base_dt + timedelta(hours=6),
                "direction": "bullish",
                "return_pct": 0.72,
                "follow_30m_pct": 0.42,
                "follow_120m_pct": 0.75,
            },
            {
                "trigger_dt": base_dt + timedelta(hours=18),
                "direction": "bearish",
                "return_pct": -0.61,
                "follow_30m_pct": -0.28,
                "follow_120m_pct": -0.45,
            },
        ],
    )
    monkeypatch.setattr(
        api,
        "build_event_forecast",
        lambda **kwargs: captured["forecast_calls"].append((kwargs.get("frequency"), kwargs.get("context_length"))) or {
            "available": True,
            "primary_label": "1小时",
            "secondary_label": "4小时",
            "summary": "历史上冲后偏上行" if kwargs.get("actual_follow_primary_pct", 0) >= 0 else "历史下探后偏下行",
            "surprise_score": 0.18 if kwargs.get("actual_follow_primary_pct", 0) >= 0 else 0.22,
            "forecast_primary": {"expected_return_pct": 0.3 if kwargs.get("actual_follow_primary_pct", 0) >= 0 else -0.15},
            "forecast_secondary": {"expected_return_pct": 0.6 if kwargs.get("actual_follow_secondary_pct", 0) >= 0 else -0.38},
            "forecast_30m": {"expected_return_pct": 0.3 if kwargs.get("actual_follow_primary_pct", 0) >= 0 else -0.15},
            "forecast_120m": {"expected_return_pct": 0.6 if kwargs.get("actual_follow_secondary_pct", 0) >= 0 else -0.38},
        },
    )

    result = api._generate_timesfm_review_payload(
        {"current_market": "fx", "current_code": "EURUSD", "review_days": 30, "frequency": "1h", "max_items": 5}
    )

    assert result["event_count"] == 2
    assert result["analysis_count"] == 2
    assert result["review_days"] == 30
    assert result["frequency"] == "1h"
    assert result["frequency_label"] == "1小时"
    assert result["primary_label"] == "1小时"
    assert result["secondary_label"] == "4小时"
    assert captured["load_frequency"] == "60m"
    assert captured["forecast_calls"]
    assert all(item[0] == "60m" for item in captured["forecast_calls"])
    assert result["stats"]["direction_hit_rate_primary"] == 1.0
    assert result["stats"]["direction_hit_rate_secondary"] == 1.0
    assert result["stats"]["mae_primary_pct"] >= 0
    assert result["stats"]["reliability_score"] is not None
    assert result["stats"]["sample_quality_label"] in {"样本偏少", "样本一般", "样本较充分"}
    assert result["stats"]["group_breakdown"]["bullish"]["count"] == 1
    assert result["stats"]["group_breakdown"]["bearish"]["count"] == 1
    assert "notes" in result["stats"]
    assert "1小时价格" in result["summary"]
    assert "主模式" in result["summary"]
    assert "验证方法" not in result["summary"]
    assert "事件触发当时" in result["validation_method"]
    assert "纯价格" in result["validation_method"]
    assert "价格+事件协变量" in result["validation_method"]
    assert result["context_length_used"] in {24, 48, 72, 96}
    assert result["context_evaluation"]["evaluations"]
    assert result["selected_review_mode"] in {"pure_price", "price_event_covariates"}
    assert result["selected_review_mode_label"] in {"纯价格", "价格+事件协变量"}
    assert len(result["review_mode_results"]) == 2
    assert len(result["mode_comparison"]) == 2
    assert {item["mode_key"] for item in result["mode_comparison"]} == {"pure_price", "price_event_covariates"}
    assert result["events"][0]["primary_label"] == "1小时"
    assert result["events"][0]["forecast_summary"]
    assert result["events"][0]["event_price_table"]


def test_generate_timesfm_review_payload_counts_same_direction_as_hit_for_small_5m_moves(monkeypatch):
    base_dt = datetime(2026, 4, 5, 9, 0, 0)
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda **kwargs: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.1 + idx * 0.0001,
                "close": 1.1001 + idx * 0.0001,
                "high": 1.1002 + idx * 0.0001,
                "low": 1.0999 + idx * 0.0001,
                "volume": 1000 + idx,
            }
            for idx in range(80)
        ],
    )
    monkeypatch.setattr(
        api,
        "_detect_price_events",
        lambda **kwargs: [
            {"trigger_dt": base_dt + timedelta(minutes=25), "direction": "bullish", "return_pct": 0.48},
            {"trigger_dt": base_dt + timedelta(minutes=55), "direction": "bearish", "return_pct": -0.44},
        ],
    )
    monkeypatch.setattr(
        api,
        "build_event_forecast",
        lambda **kwargs: {
            "available": True,
            "primary_label": "5分钟",
            "secondary_label": "20分钟",
            "summary": "小波动回测",
            "surprise_score": 0.06,
            "forecast_primary": {
                "expected_return_pct": 0.012,
                "point_forecast_price_path": [1.1002],
            },
            "forecast_secondary": {
                "expected_return_pct": 0.018,
                "point_forecast_price_path": [1.1002, 1.10021, 1.10022, 1.10023],
            },
            "forecast_30m": {"expected_return_pct": 0.012},
            "forecast_120m": {"expected_return_pct": 0.018},
        },
    )
    monkeypatch.setattr(
        api,
        "_compute_forward_return_pct",
        lambda price_bars, start_index, horizon_bars: 0.011 if horizon_bars == 1 else 0.019,
    )

    result = api._generate_timesfm_review_payload(
        {"current_market": "fx", "current_code": "EURUSD", "review_days": 14, "frequency": "5m", "max_items": 5}
    )

    assert result["available"] is True
    assert result["stats"]["direction_hit_rate_primary"] == 1.0
    assert result["stats"]["neutral_match_rate_primary"] == 0.0
    assert "方向命中率" in result["summary"]
    assert "只要预测方向与实际方向一致就计为命中" in result["validation_method"]


def test_build_realtime_focus_payload_passes_selected_context_length(monkeypatch):
    captured = {"context_length": None}
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: api._default_event_topic_definitions())
    monkeypatch.setattr(api, "_get_product_info", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "get_exchange", lambda *args, **kwargs: type("DummyExchange", (), {"stock_info": lambda self, code: {}})())
    monkeypatch.setattr(api, "get_vector_news", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda *args, **kwargs: {"direct": [], "driver": [], "background": []})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda *args, **kwargs: {"available": True, "recent_event": None, "direction": "neutral", "alert_level": "low"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"items": [], "summary": ""})
    monkeypatch.setattr(api, "_build_research_scenario_route", lambda *args, **kwargs: {"label": "", "route": "balanced_monitoring"})
    monkeypatch.setattr(api, "_build_reflection_memory", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_quick_research_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_deep_research_plan", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_rule_based_risk_brief", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_realtime_spike_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: captured.__setitem__("context_length", kwargs.get("context_length")) or {"summary": "ok", "backend_details": {"native_enabled": True, "native_message": "", "xreg_used": False}},
    )

    result = api._build_realtime_focus_payload("fx", "EURUSD", "5m", 96)

    assert captured["context_length"] == 96
    assert result["timesfm_context_length"] == 96


def test_build_realtime_focus_payload_defaults_timesfm_frequency_to_30m(monkeypatch):
    captured = {"frequency": None}
    monkeypatch.setattr(api, "_get_product_info", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "get_exchange", lambda *args, **kwargs: type("DummyExchange", (), {"stock_info": lambda self, code: {}})())
    monkeypatch.setattr(api, "get_vector_news", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_search_news_from_relational_db", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda *args, **kwargs: {"direct": [], "driver": [], "background": []})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda *args, **kwargs: {"available": True, "recent_event": None, "direction": "neutral", "alert_level": "low", "status_label": "价格平稳"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"items": [], "summary": ""})
    monkeypatch.setattr(api, "_build_research_scenario_route", lambda *args, **kwargs: {"label": "", "route": "balanced_monitoring"})
    monkeypatch.setattr(api, "_build_reflection_memory", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_quick_research_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_deep_research_plan", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_rule_based_risk_brief", lambda *args, **kwargs: {})
    monkeypatch.setattr(api, "_build_realtime_spike_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api,
        "_build_timesfm_forecast",
        lambda **kwargs: captured.__setitem__("frequency", kwargs.get("frequency")) or {"summary": "ok", "backend_details": {"native_enabled": True, "native_message": "", "xreg_used": False}},
    )

    api._build_realtime_focus_payload("fx", "EURUSD")

    assert captured["frequency"] == "30m"


def test_generate_timesfm_review_payload_returns_unavailable_when_native_missing(monkeypatch):
    base_dt = datetime(2026, 4, 5, 9, 0, 0)
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda **kwargs: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.1 + idx * 0.0002,
                "close": 1.1003 + idx * 0.00025,
                "high": 1.1005 + idx * 0.00025,
                "low": 1.0998 + idx * 0.0002,
                "volume": 1000 + idx,
            }
            for idx in range(120)
        ],
    )
    monkeypatch.setattr(
        api,
        "_detect_price_events",
        lambda **kwargs: [
            {
                "trigger_dt": base_dt + timedelta(minutes=50),
                "direction": "bullish",
                "return_pct": 0.52,
            }
        ],
    )
    monkeypatch.setattr(
        api,
        "build_event_forecast",
        lambda **kwargs: {
            "available": False,
            "backend": "timesfm_native_unavailable",
            "summary": "原生 TimesFM 不可用，无法生成反事实预测。",
            "error_message": "原生 TimesFM 不可用，无法生成反事实预测。",
        },
    )

    result = api._generate_timesfm_review_payload(
        {"current_market": "fx", "current_code": "EURUSD", "review_days": 14, "frequency": "5m"}
    )

    assert result["available"] is False
    assert result["backend"] == "timesfm_native_unavailable"
    assert "原生 TimesFM 不可用" in result["summary"]
    assert result["event_count"] == 0
    assert len(result["mode_comparison"]) == 2


def test_normalize_timesfm_request_defaults_to_30m():
    result = api._normalize_timesfm_request({"current_market": "fx", "current_code": "EURUSD"})
    assert result["frequency"] == "30m"


def test_generate_timesfm_review_payload_defaults_to_30m_frequency(monkeypatch):
    captured = {"frequency": None}
    base_dt = datetime(2026, 4, 5, 9, 0, 0)
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda **kwargs: captured.__setitem__("frequency", kwargs.get("frequency")) or [
            {
                "dt": base_dt + timedelta(minutes=30 * idx),
                "open": 1.1 + idx * 0.0002,
                "close": 1.1002 + idx * 0.00025,
                "high": 1.1004 + idx * 0.00025,
                "low": 1.0998 + idx * 0.0002,
                "volume": 1000 + idx,
            }
            for idx in range(80)
        ],
    )
    monkeypatch.setattr(api, "_detect_price_events", lambda **kwargs: [])

    result = api._generate_timesfm_review_payload({"current_market": "fx", "current_code": "EURUSD"})

    assert captured["frequency"] == "30m"
    assert result["frequency"] == "30m"
    assert result["frequency_label"] == "30分钟"


def test_historical_analysis_persists_timesfm_review_metadata(monkeypatch):
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        api,
        "_normalize_history_analysis_params",
        lambda data: {
            "lookback_hours": 24,
            "event_frequency": "5m",
            "event_window_minutes": 5,
            "merge_gap_minutes": 20,
            "min_return_pct": 0.3,
            "min_range_pct": 0.4,
            "atr_multiple": 1.2,
            "max_events": 2,
        },
    )
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: api._default_event_topic_definitions())
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda **kwargs: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.10 + idx * 0.0002,
                "close": 1.1003 + idx * 0.00025,
                "high": 1.1006 + idx * 0.00025,
                "low": 1.0999 + idx * 0.0002,
                "volume": 1000 + idx,
            }
            for idx in range(50)
        ],
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "欧元美元"})
    monkeypatch.setattr(api, "get_exchange", lambda market: SimpleNamespace(stock_info=lambda code: {"name": "欧元美元"}))
    monkeypatch.setattr(
        api,
        "_detect_price_events",
        lambda **kwargs: [
            {
                "event_id": "evt_1",
                "trigger_dt": base_dt + timedelta(minutes=90),
                "direction": "bullish",
                "return_pct": 0.68,
                "bar_range_pct": 0.92,
                "follow_30m_pct": 0.44,
                "follow_120m_pct": 0.73,
                "event_news": [],
                "top_news_titles": ["美元回落"],
            }
        ],
    )
    monkeypatch.setattr(api, "_collect_event_news", lambda **kwargs: [])
    monkeypatch.setattr(api, "_derive_storyline_label", lambda *args, **kwargs: "美元回落")
    monkeypatch.setattr(api, "_build_historical_storylines", lambda *args, **kwargs: [{"storyline": "美元回落", "strength_score": 0.72}])
    monkeypatch.setattr(api, "_summarize_historical_pricing_state", lambda *args, **kwargs: {"future_bias": "存在上行延续", "pricing_status": "partially_absorbed"})
    monkeypatch.setattr(api, "_estimate_remaining_pricing_room", lambda *args, **kwargs: {"estimated_room_pct": 0.38})
    monkeypatch.setattr(api, "_collect_similar_historical_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_build_research_scenario_route", lambda **kwargs: {"route": "historical_followthrough", "label": "历史主线延续"})
    monkeypatch.setattr(api, "_build_reflection_memory", lambda **kwargs: {"summary": "过去类似事件常先涨后稳"})
    monkeypatch.setattr(api, "_build_quick_research_snapshot", lambda **kwargs: {"summary": "先确认延续性"})
    monkeypatch.setattr(api, "_build_deep_research_plan", lambda **kwargs: {"summary": "继续确认跨资产反馈"})
    monkeypatch.setattr(api, "_build_timesfm_forecast", lambda **kwargs: {"summary": "未来120分钟偏上行"})
    monkeypatch.setattr(api, "build_event_forecast", lambda **kwargs: {"summary": "事件后预测偏上行", "surprise_score": 0.2, "forecast_30m": {"expected_return_pct": 0.3}, "forecast_120m": {"expected_return_pct": 0.6}})
    monkeypatch.setattr(api, "_build_rule_based_risk_brief", lambda **kwargs: {"summary": "注意短线回撤"})
    monkeypatch.setattr(api, "_build_historical_analysis_context", lambda **kwargs: "context")
    monkeypatch.setattr(api, "_generate_ai_historical_analysis", lambda **kwargs: "历史分析报告")

    captured = {}
    monkeypatch.setattr(
        api.db,
        "market_summary_insert",
        lambda payload: (captured.__setitem__("payload", payload), 1001)[1],
    )

    result = api._generate_historical_analysis_payload({"current_market": "fx", "current_code": "EURUSD"})

    chart_snapshot = json.loads(captured["payload"]["chart_snapshot"])
    assert captured["payload"]["summary_type"] == "historical_analysis"
    assert captured["payload"]["title"] == "欧元美元 1天历史分析"
    assert chart_snapshot["schema"] == "timesfm_review_v1"
    assert chart_snapshot["events"][0]["timesfm_forecast"]["summary"] == "事件后预测偏上行"
    assert result["events"][0]["timesfm_forecast"]["summary"] == "事件后预测偏上行"


def test_build_reflection_memory_prefers_matching_route(monkeypatch):
    now = datetime(2026, 4, 4, 12, 0, 0)
    monkeypatch.setattr(
        api.db,
        "market_summary_query",
        lambda **kwargs: [
            SimpleNamespace(
                id=1,
                title="价格与新闻共振复盘",
                content="价格与新闻共振场景里，若30分钟没有延续就属于失效信号，不要追。",
                summary_type="historical_analysis",
                created_at=now,
            ),
            SimpleNamespace(
                id=2,
                title="普通市场总结",
                content="这是一般性总结。",
                summary_type="market_analysis",
                created_at=now - timedelta(days=1),
            ),
        ],
    )

    memory = api._build_reflection_memory(
        current_market="fx",
        current_code="EURUSD",
        scenario_route={"label": "价格与新闻共振", "trigger": "CPI"},
    )

    assert memory["items"][0]["summary_id"] == 1
    assert "失效" in memory["summary"] or "过去" in memory["summary"]


def test_get_product_info_accepts_optional_market_arg():
    result = api._get_product_info("EURUSD", "fx")

    assert result["name_cn"] == "欧元美元"
    assert result["type"] == "forex"


def test_get_product_info_normalizes_futures_code_to_akshare_symbol():
    result = api._get_product_info("QZ.MAL8", "futures")

    assert result["akshare_symbol"] == "MA"
    assert result["akshare_name_cn"] == "甲醇"
    assert result["is_futures"] is True


def test_build_market_data_symbol_candidates_prefers_akshare_symbol():
    candidates = api._build_market_data_symbol_candidates(
        "QZ.MAL8",
        {
            "name_cn": "甲醇主连",
            "name_en": "Methanol Futures",
            "symbol": "QZ.MAL8",
            "akshare_symbol": "MA",
            "akshare_name_cn": "甲醇",
        },
    )

    assert candidates[0] == "QZ.MAL8"
    assert "MA" in candidates
    assert "甲醇" in candidates


def test_build_market_data_symbol_candidates_includes_forex_aliases():
    candidates = api._build_market_data_symbol_candidates(
        "USDCNY",
        {
            "name_cn": "美元人民币",
            "name_en": "US Dollar / Chinese Yuan",
            "type": "forex",
            "symbol": "USDCNY",
            "base_currency": "USD",
            "quote_currency": "CNY",
            "aliases": ["USDCNH", "USD/CNY"],
        },
    )

    assert "USDCNY" in candidates
    assert "USDCNH" in candidates
    assert "USD/CNY" in candidates
    assert "CNY" in candidates


def test_build_market_data_sync_plan_for_fx_includes_pair_specific_tasks():
    tasks = api._build_market_data_sync_plan(
        "fx",
        "EURUSD",
        {
            "name_cn": "欧元美元",
            "name_en": "EURUSD",
            "type": "forex",
            "symbol": "EURUSD",
            "base_currency": "EUR",
            "quote_currency": "USD",
        },
    )

    datasets = [item["dataset"] for item in tasks]
    banks = [item["args"].get("bank") for item in tasks if item["dataset"] == "central_bank_rate"]
    assert datasets[0] == "macro_calendar"
    assert "cftc" in datasets
    assert set(banks) == {"ecb", "federal_reserve"}


def test_summarize_realtime_price_state_calls_detect_price_events_with_supported_kwargs(monkeypatch):
    base_dt = datetime(2026, 4, 4, 9, 0, 0)
    monkeypatch.setattr(
        api,
        "_load_historical_price_bars",
        lambda market, code, frequency, lookback_hours, purpose=None: [
            {
                "dt": base_dt + timedelta(minutes=5 * idx),
                "open": 1.0 + idx * 0.01,
                "close": 1.01 + idx * 0.01,
                "high": 1.02 + idx * 0.01,
                "low": 0.99 + idx * 0.01,
                "volume": 100 + idx,
            }
            for idx in range(12)
        ],
    )

    captured = {}

    def fake_detect(price_bars, min_return_pct, min_range_pct, atr_multiple, event_window_minutes, merge_gap_minutes):
        captured["min_return_pct"] = min_return_pct
        captured["min_range_pct"] = min_range_pct
        captured["atr_multiple"] = atr_multiple
        captured["event_window_minutes"] = event_window_minutes
        captured["merge_gap_minutes"] = merge_gap_minutes
        return []

    monkeypatch.setattr(api, "_detect_price_events", fake_detect)

    result = api._summarize_realtime_price_state("fx", "EURUSD")

    assert result["available"] is True
    assert captured == {
        "min_return_pct": 0.18,
        "min_range_pct": 0.28,
        "atr_multiple": 1.0,
        "event_window_minutes": 5,
        "merge_gap_minutes": 10,
    }


def test_generate_theme_simulation_payload_builds_reasoning_bundle(monkeypatch):
    memory_store = {}
    search_calls = []
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(
        api,
        "_get_product_info",
        lambda code, market="": {"name_cn": "欧元美元", "name_en": "EURUSD", "type": "forex"},
    )
    monkeypatch.setattr(
        api,
        "_summarize_realtime_price_state",
        lambda market, code: {
            "available": True,
            "direction": "bullish",
            "change_30m_pct": 0.42,
            "latest_price": 1.0865,
            "status_label": "短线开始发力",
        },
    )
    monkeypatch.setattr(
        api,
        "_build_cross_asset_watch",
        lambda current_market, current_code, current_price_state, product_info=None: {
            "items": [
                {"code": "USDJPY", "name": "美元日元", "market": "fx", "relation": "inverse", "change_30m_pct": -0.31, "status_label": "联动确认"}
            ],
            "summary": "联动确认"
        },
    )
    monkeypatch.setattr(
        api,
        "_build_asset_news_response",
        lambda asset_code, market, days=7, limit=20: {"buckets": {"direct": [], "driver": [], "background": []}},
    )
    def fake_search_news(query, search_terms, start_date, end_date, n_results):
        search_calls.append({"query": query, "search_terms": list(search_terms or [])})
        return [
            {
                "document": "鲍威尔讲话强化降息预期，美元回落。",
                "metadata": {
                    "news_id": "n1",
                    "title": "鲍威尔讲话强化降息预期",
                    "published_at": "2026-04-06T08:00:00",
                    "importance_score": 0.92,
                    "direct_assets": ["EURUSD"],
                    "driver_assets": [],
                },
            },
            {
                "document": "美国通胀继续放缓，市场押注美联储更早转向。",
                "metadata": {
                    "news_id": "n2",
                    "title": "美国通胀继续放缓",
                    "published_at": "2026-04-06T07:30:00",
                    "importance_score": 0.81,
                    "direct_assets": [],
                    "driver_assets": ["EURUSD"],
                },
            },
        ]

    monkeypatch.setattr(api, "_search_news_from_relational_db", fake_search_news)
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [news_list[0]], "driver": [news_list[1]], "background": []})
    monkeypatch.setattr(
        api,
        "_load_event_topic_definitions",
        lambda: [
            {
                "id": "fed-officials",
                "label": "美联储官员讲话",
                "description": "联储官员讲话对美元与利率预期的冲击",
                "keywords": ["美联储", "鲍威尔", "官员讲话", "降息预期"],
                "enabled": True,
            }
        ],
    )

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "theme_label": "美联储官员讲话",
            "lookback_hours": 24,
            "max_news": 6,
        }
    )

    assert payload["theme"]["label"] == "美联储官员讲话"
    assert payload["run_id"]
    assert payload["generated_at"]
    assert payload["asset_context"]["asset_name"] == "欧元美元"
    assert payload["news_counts"]["direct"] == 1
    assert payload["news_counts"]["searched"] == 2
    assert payload["report"]["trade_bias"] == "顺势看多"
    assert "鲍威尔讲话强化降息预期" in payload["report"]["news_summary"]
    assert any(item["title"] == "鲍威尔讲话强化降息预期" for item in payload["theme_news"])
    assert payload["propagation_chain"][0]["stage"] == "主题触发"
    assert payload["ontology"]["entity_count"] >= 3
    assert payload["research_agent"]["manual_trigger_only"] is True
    assert any(item["label"] == "主题证据扫描" for item in payload["research_agent"]["tool_findings"])
    assert payload["research_agent"]["actor_profiles"][0]["name"] == "美联储"
    assert payload["research_agent"]["rounds_completed"] == 2
    assert payload["research_agent"]["agent_rounds"][0]["focus"] == "direct_evidence"
    assert payload["research_agent"]["report_sections"][0]["title"] == "市场结论"
    assert payload["research_agent"]["agent_journal"][0]["stage"] == "planner"
    assert payload["research_agent"]["planner_source"] == "evidence_gap_heuristic"
    assert payload["theme_agent_panel"]["arbiter"]["summary"]
    assert payload["theme_agent_panel"]["consensus"]["stance"] in {"偏多", "偏空", "中性"}
    assert payload["theme_agent_panel"]["route_context"]["route_label"] == "央行路径"
    assert payload["theme_agent_panel"]["active_agents"][0]["selection_reason"]
    assert payload["report"]["fx_decision_template"]["route_label"] == "央行路径"
    assert payload["comprehensive_reasoning"]["router"]["route_label"] == "央行路径"
    assert payload["comprehensive_reasoning"]["cross_asset_evidence"]["regime_label"] in {"跨资产共振", "部分确认", "跨资产背离", "证据缺失"}
    assert payload["comprehensive_reasoning"]["arbiter_execution"]["pricing_stage"] in {"多市场确认", "部分定价", "待确认"}
    assert payload["research_agent"]["theme_multi_agent_panel"]["arbiter"]["summary"]
    assert payload["research_agent"]["comprehensive_reasoning"]["router"]["route_label"] == "央行路径"
    assert payload["analysis_scope"]["theme_agent_count"] >= 4
    assert payload["analysis_scope"]["theme_agent_labels"]
    assert payload["analysis_scope"]["comprehensive_route_label"] == "央行路径"
    assert payload["analysis_scope"]["pricing_stage"] in {"多市场确认", "部分定价", "待确认"}
    assert payload["research_memory"]["run_count"] == 1
    assert payload["news_counts"]["supplemental"] == 4
    assert payload["analysis_scope"]["agent_rounds_completed"] == 2
    assert payload["analysis_scope"]["is_new_run"] is True
    assert payload["analysis_scope"]["force_refresh"] is False
    assert payload["analysis_scope"]["manual_trigger_only"] is True
    assert len(search_calls) == 3


def test_select_theme_agents_prefers_asset_and_theme_specific_agents(monkeypatch):
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "欧元美元", "name_en": "EURUSD", "type": "forex"})

    selected_agents = api._select_theme_agents(
        current_market="fx",
        current_code="EURUSD",
        theme_definition={
            "label": "美联储官员讲话",
            "description": "联储讲话推动美元与利率预期重估",
            "keywords": ["美联储", "鲍威尔", "降息预期"],
        },
        agent_definitions=api._get_theme_agent_definitions("fx", "EURUSD", "美联储官员讲话"),
    )

    selected_ids = {item["id"] for item in selected_agents}
    assert "evidence_scout" in selected_ids
    assert "market_validator" in selected_ids
    assert "market_structure" in selected_ids
    assert "risk_arbiter" in selected_ids
    assert "fx_macro_policy" in selected_ids


def test_select_theme_agents_routes_audusd_growth_theme_to_pair_and_cross_asset_agents(monkeypatch):
    monkeypatch.setattr(
        api,
        "_get_product_info",
        lambda code, market="": {
            "name_cn": "澳元美元",
            "name_en": "AUDUSD",
            "type": "forex",
            "base_currency": "AUD",
            "quote_currency": "USD",
        },
    )

    selected_agents = api._select_theme_agents(
        current_market="fx",
        current_code="AUDUSD",
        theme_definition={
            "label": "中国刺激与铁矿石反弹",
            "description": "中国稳增长预期回升，铁矿石和铜价反弹带动澳元交易重估",
            "keywords": ["中国刺激", "铁矿石", "铜", "风险偏好"],
        },
        agent_definitions=api._get_theme_agent_definitions("fx", "AUDUSD", "中国刺激与铁矿石反弹"),
    )

    selected_ids = {item["id"] for item in selected_agents}
    assert "fx_pair_specialist" in selected_ids
    assert "fx_cross_asset" in selected_ids
    assert "fx_risk_sentiment" in selected_ids
    pair_specialist = next(item for item in selected_agents if item["id"] == "fx_pair_specialist")
    assert int(pair_specialist.get("selection_score", 0)) >= 6


def test_build_theme_agent_output_uses_fx_pair_specialist_profile(monkeypatch):
    monkeypatch.setattr(
        api,
        "_get_product_info",
        lambda code, market="": {
            "name_cn": "美元日元",
            "name_en": "USDJPY",
            "type": "forex",
            "base_currency": "USD",
            "quote_currency": "JPY",
        },
    )

    output = api._build_theme_agent_output(
        agent_definition={
            "id": "fx_pair_specialist",
            "label": "日元干预 Agent",
            "agent_type": "pair_specialist",
            "role": "美债收益率与日央行干预机制",
            "description": "聚焦 USDJPY 的干预机制。",
            "priority": 95,
            "preset_source": "asset_default",
            "focus_points": ["美债收益率", "日央行", "干预", "套息交易"],
        },
        theme_definition={
            "label": "日本官员警告汇率波动",
            "description": "日本官员继续释放干预警告，USDJPY 波动加剧。",
            "keywords": ["日本", "干预", "汇率", "官员讲话"],
        },
        asset_context={
            "current_market": "fx",
            "current_code": "USDJPY",
            "asset_name": "美元日元",
            "asset_type": "forex",
            "base_currency": "USD",
            "quote_currency": "JPY",
            "price_direction": "bearish",
            "status_label": "快速回落",
        },
        toolkit_payload={
            "evidence_matrix": {"bucket_counts": {"driver": 2, "background": 1}, "dominant_direction": "bearish"},
            "theme_news": [{"title": "日本官员警告汇率波动", "reaction_summary": "新闻后价格偏下行，30分钟 -0.350%，120分钟 -0.620%。"}],
            "direct_theme_news": [],
            "actor_profiles": [],
            "cross_asset_signals": [],
        },
        temporal_evidence={},
        market_data_snapshot={"structure_metrics": []},
        market_data_digest={"catalog_overview": [], "analysis_focus": [], "summary": ""},
        cross_asset_watch={"summary": "美元走强与日元干预风险并存", "items": []},
    )

    assert output["agent_type"] == "pair_specialist"
    assert output["summary"].startswith("日元干预 Agent")
    assert any("美债收益率与日央行干预机制" in item for item in output["findings"])
    assert any("政策干预" in item for item in output["findings"])


def test_generate_theme_simulation_payload_respects_custom_theme_agents(monkeypatch):
    memory_store = {}
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "黄金", "name_en": "XAU", "type": "commodity"})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda market, code: {"direction": "bullish", "change_30m_pct": 0.28, "latest_price": 2328.0, "status_label": "价格走强"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"items": [], "summary": "ok"})
    monkeypatch.setattr(api, "_build_asset_news_response", lambda *args, **kwargs: {"buckets": {"direct": [], "driver": [], "background": []}})
    monkeypatch.setattr(api, "_search_news_from_relational_db", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [], "driver": [], "background": []})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: [])

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "futures",
            "current_code": "XAU",
            "theme_label": "地缘冲突",
            "theme_agents": [
                {
                    "id": "custom_geopolitics",
                    "label": "自定义地缘 Agent",
                    "agent_type": "geopolitics",
                    "role": "跟踪地缘升级",
                    "description": "关注中东冲突与避险溢价。",
                    "focus_points": ["中东", "避险", "供给扰动"],
                    "theme_keywords": ["冲突", "战争", "伊朗"],
                    "instructions": "优先区分一次性冲击还是持续升级。",
                    "priority": 120,
                    "enabled": True,
                    "preset_source": "custom",
                }
            ],
        }
    )

    active_labels = [item["label"] for item in payload["theme_agent_panel"]["active_agents"]]
    assert "自定义地缘 Agent" in active_labels
    assert any(item["label"] == "多 Agent 裁决" for item in payload["research_agent"]["tool_findings"])
    assert payload["analysis_scope"]["theme_agent_count"] >= 4


def test_generate_theme_simulation_payload_supports_ad_hoc_theme(monkeypatch):
    memory_store = {}
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "黄金", "name_en": "XAU", "type": "commodity"})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda market, code: {"direction": "bearish", "change_30m_pct": -0.25, "latest_price": 2320.0, "status_label": "价格回落"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"references": []})
    monkeypatch.setattr(api, "_build_asset_news_response", lambda *args, **kwargs: {"buckets": {"direct": [], "driver": [], "background": []}})
    monkeypatch.setattr(
        api,
        "_search_news_from_relational_db",
        lambda *args, **kwargs: [
            {
                "document": "特朗普讲话再提关税，黄金短线承压。",
                "metadata": {
                    "news_id": "n3",
                    "title": "特朗普讲话再提关税",
                    "published_at": "2026-04-06T09:00:00",
                    "importance_score": 0.66,
                    "direct_assets": [],
                    "driver_assets": [],
                },
            }
        ],
    )
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [], "driver": [], "background": news_list})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: [])

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "futures",
            "current_code": "XAU",
            "theme_label": "特朗普讲话",
        }
    )

    assert payload["theme"]["source"] in {"ad_hoc_theme", "configured_topic"}
    assert payload["analysis_scope"]["is_new_run"] is True
    assert payload["news_counts"]["background"] == 1
    assert payload["news_counts"]["searched"] == 1
    assert payload["news_counts"]["supplemental"] == 2
    assert payload["report"]["summary"]
    assert payload["research_agent"]["tool_findings"]
    assert payload["research_agent"]["rounds_completed"] == 2
    assert payload["research_agent"]["report_sections"]
    assert payload["research_memory"]["last_trade_bias"] == payload["report"]["trade_bias"]


def test_extract_uploaded_file_text_supports_markdown():
    evidence = api._extract_uploaded_file_text(
        "fed_view.md",
        "# 美联储官员讲话\n\n鲍威尔强调更依赖数据，美元短线承压。".encode("utf-8"),
    )

    assert evidence["file_type"] == "md"
    assert evidence["source_label"] == "文本材料"
    assert "鲍威尔" in evidence["content"]
    assert evidence["summary"]


def test_generate_theme_simulation_payload_calls_cross_asset_watch_with_current_price_state(monkeypatch):
    memory_store = {}
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "欧元美元", "name_en": "EURUSD", "type": "forex"})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda market, code: {"direction": "neutral", "change_30m_pct": 0.0, "latest_price": 1.08, "status_label": "价格平稳"})
    monkeypatch.setattr(api, "_build_asset_news_response", lambda *args, **kwargs: {"buckets": {"direct": [], "driver": [], "background": []}})
    monkeypatch.setattr(api, "_search_news_from_relational_db", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [], "driver": [], "background": []})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: [])

    captured = {}

    def fake_cross_asset_watch(current_market, current_code, current_price_state, product_info=None):
        captured["current_market"] = current_market
        captured["current_code"] = current_code
        captured["current_price_state"] = current_price_state
        captured["product_info"] = product_info
        return {"items": [], "summary": "ok"}

    monkeypatch.setattr(api, "_build_cross_asset_watch", fake_cross_asset_watch)

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "theme_label": "美元走弱",
        }
    )

    assert payload["asset_context"]["current_code"] == "EURUSD"
    assert captured["current_market"] == "fx"
    assert captured["current_code"] == "EURUSD"
    assert captured["current_price_state"]["status_label"] == "价格平稳"
    assert captured["product_info"]["type"] == "forex"


def test_generate_theme_simulation_payload_includes_uploaded_evidence(monkeypatch):
    memory_store = {}
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "黄金", "name_en": "XAU", "type": "commodity"})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda market, code: {"direction": "neutral", "change_30m_pct": 0.0, "latest_price": 2320.0, "status_label": "价格平稳"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"items": [], "summary": "ok"})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: [])
    monkeypatch.setattr(api, "_search_news_from_relational_db", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [], "driver": [], "background": []})
    monkeypatch.setattr(
        api,
        "_estimate_price_reaction_around_time",
        lambda market, code, frequency, anchor_dt: {
            "return_pct": 0.35,
            "follow_30m_pct": 0.42,
            "follow_120m_pct": 0.61,
            "absorption_status": "not_fully_priced",
            "absorption_reason": "延续存在",
            "direction": "bullish",
        },
    )

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "futures",
            "current_code": "XAU",
            "theme_label": "特朗普讲话",
            "uploaded_evidence": [
                {
                    "evidence_id": "manual-1",
                    "title": "特朗普讲话纪要.md",
                    "file_name": "特朗普讲话纪要.md",
                    "file_type": "md",
                    "source_label": "文本材料",
                    "summary": "特朗普讲话提到关税与大选议题，黄金避险需求可能回升。",
                    "content": "特朗普讲话提到关税与大选议题，黄金避险需求可能回升。",
                    "published_at": "2026-04-06T09:00:00",
                    "impact_direction": "bullish",
                }
            ],
        }
    )

    assert payload["news_counts"]["uploaded"] == 1
    assert payload["uploaded_evidence"][0]["title"] == "特朗普讲话纪要.md"
    assert payload["analysis_scope"]["uploaded_evidence_count"] == 1
    assert payload["analysis_scope"]["temporal_reaction_count"] >= 1
    assert payload["research_agent"]["temporal_evidence"]["alignment_rate"] >= 0.3
    assert any(item["label"] == "用户材料证据" for item in payload["research_agent"]["tool_findings"])


def test_generate_theme_simulation_payload_includes_market_data_snapshot(monkeypatch):
    memory_store = {}
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "欧元美元", "name_en": "EURUSD", "type": "forex"})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda market, code: {"direction": "bullish", "change_30m_pct": 0.35, "latest_price": 1.09, "status_label": "价格走强"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"items": [], "summary": "ok"})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: [])
    monkeypatch.setattr(api, "_search_news_from_relational_db", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [], "driver": [], "background": []})
    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=6: {
            "asset": {"market": current_market, "code": current_code, "asset_class": "fx"},
            "summary": {"event_count": 1, "factor_count": 1, "metric_count": 1, "reaction_count": 1, "agent_log_count": 0},
            "sync_plan": [],
            "events": [{"title": "美国 CPI", "symbol": "EURUSD"}],
            "factors": [{"factor_name": "cftc_net_position", "value": 12.5, "unit": "contracts"}],
            "structure_metrics": [{"metric_name": "theme_diffusion_score", "metric_value": 0.78}],
            "price_reactions": [{"reaction_label": "news_followthrough", "return_30m_pct": 0.42}],
            "agent_logs": [],
            "updated_at": "2026-04-07T16:00:00",
        },
    )

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "fx",
            "current_code": "EURUSD",
            "theme_label": "美元走弱",
        }
    )

    assert payload["market_data_snapshot"]["summary"]["event_count"] == 1
    assert payload["asset_context"]["market_data_event_count"] == 1
    assert payload["asset_context"]["market_data_summary"].startswith("市场数据底座已命中")
    assert payload["analysis_scope"]["market_data_reaction_count"] == 1
    assert any(item["label"] == "市场数据底座" for item in payload["research_agent"]["tool_findings"])
    assert payload["research_agent"]["market_data_digest"]["highlights"][0].startswith("事件：")


def test_generate_theme_simulation_payload_force_refresh_bypasses_result_cache(monkeypatch):
    cached_payload = {
        "run_id": "cached-run",
        "generated_at": "2026-04-06T09:00:00",
        "analysis_scope": {"manual_trigger_only": True},
        "report": {"summary": "cached"},
    }
    memory_store = {}
    search_calls = []
    monkeypatch.setattr(api, "_load_summary_result_cache", lambda *args, **kwargs: dict(cached_payload))
    monkeypatch.setattr(api, "_save_summary_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.db, "cache_get", lambda key: memory_store.get(key))
    monkeypatch.setattr(api.db, "cache_set", lambda key, val, expire=0: memory_store.__setitem__(key, val) or True)
    monkeypatch.setattr(
        theme_reasoning,
        "_run_gemini_theme_reasoning",
        lambda **kwargs: {"enabled": False, "provider": "openrouter", "model": "", "message": "Gemini disabled for test", "data": {}},
    )
    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "黄金", "name_en": "XAU", "type": "commodity"})
    monkeypatch.setattr(api, "_summarize_realtime_price_state", lambda market, code: {"direction": "bearish", "change_30m_pct": -0.25, "latest_price": 2320.0, "status_label": "价格回落"})
    monkeypatch.setattr(api, "_build_cross_asset_watch", lambda *args, **kwargs: {"references": []})
    monkeypatch.setattr(api, "_build_asset_news_response", lambda *args, **kwargs: {"buckets": {"direct": [], "driver": [], "background": []}})

    def fake_search(*args, **kwargs):
        search_calls.append(1)
        return [
            {
                "document": "特朗普讲话再提关税，黄金短线承压。",
                "metadata": {
                    "news_id": "n3",
                    "title": "特朗普讲话再提关税",
                    "published_at": "2026-04-06T09:00:00",
                    "importance_score": 0.66,
                    "direct_assets": [],
                    "driver_assets": [],
                },
            }
        ]

    monkeypatch.setattr(api, "_search_news_from_relational_db", fake_search)
    monkeypatch.setattr(api, "_bucket_news_evidence", lambda news_list, canonical_asset: {"direct": [], "driver": [], "background": news_list})
    monkeypatch.setattr(api, "_load_event_topic_definitions", lambda: [])

    payload = api._generate_theme_simulation_payload(
        {
            "current_market": "futures",
            "current_code": "XAU",
            "theme_label": "特朗普讲话",
            "force_refresh": True,
            "run_id": "manual-run-1",
        }
    )

    assert payload["run_id"] == "manual-run-1"
    assert payload["analysis_scope"]["is_new_run"] is True
    assert payload["analysis_scope"]["force_refresh"] is True
    assert payload["report"]["summary"] != "cached"
    assert search_calls


def test_build_theme_reasoning_report_uses_gemini_when_available(monkeypatch):
    monkeypatch.setattr(theme_reasoning.cl_config, "OPENROUTER_AI_MODEL", "google/gemini-2.5-pro-preview")
    monkeypatch.setattr(theme_reasoning.cl_config, "OPENROUTER_AI_KEYS", "test-key")

    class FakeAI:
        def __init__(self, market):
            self.market = market

        def req_openrouter_ai_model(self, prompt):
            return {
                "ok": True,
                "model": "google/gemini-2.5-pro-preview",
                "msg": json.dumps(
                    {
                        "summary": "Gemini 判断该主题仍在扩散，短线主线未结束。",
                        "trade_bias": "顺势看多",
                        "news_summary": "核心新闻集中在联储转向预期和美元走弱。",
                        "relationship_chain": ["美联储官员讲话 -> 降息预期升温 -> 美元回落 -> EURUSD受益上行"],
                        "future_reasoning": "未来24小时若再有联储官员确认转向，EURUSD上行动能可能继续扩展。",
                        "future_scenarios": ["基准情景：震荡偏强", "强化情景：继续上破", "失效情景：美元重新转强"],
                        "execution_plan": ["等回踩后顺势跟进", "观察美元指数是否继续回落", "若消息反转则立刻降权"],
                        "risk_flags": ["若美元指数快速反弹，主题失效"],
                        "key_drivers": ["联储讲话", "美元方向"],
                        "invalidations": ["美元重新转强"],
                        "tool_insights": ["主题证据扫描确认联储转向预期正在强化。"],
                        "market_data_insights": ["事件：美国 CPI", "因子：cftc_net_position=12.5contracts"],
                        "market_data_catalog": ["央行决议：用于比较欧央行与美联储相对利差。", "外汇结构因子：用于判断 EURUSD 中短线方向。"],
                        "analysis_playbook": ["先定主轴 / 央行决议 + 外汇结构因子 / 用利差定义方向", "再找催化 / 宏观日历 / 用数据确认触发器"],
                        "actor_signals": ["美联储：仍是主导 EURUSD 短线方向的关键主体。"],
                        "multi_agent_consensus": "多 Agent 裁决偏多，主要来自央行宏观 Agent 与时间验证 Agent 的一致结论。",
                        "comprehensive_reasoning": {
                            "summary": "当前全面推演优先采用「央行路径」框架；跨资产处于「跨资产共振」阶段，确认分数 0.78；裁决层给出的执行偏向为「顺势跟踪多头」，当前定价阶段为「多市场确认」。",
                            "router": {"route_label": "央行路径", "focus": "先看相对强弱，再看美元主线、利差、风险偏好与货币对专属机制。"},
                            "cross_asset_evidence": {"regime_label": "跨资产共振", "confirmation_score": 0.78, "corroboration_summary": "美元回落与跨资产确认共同支撑 EURUSD 继续偏强。"},
                            "arbiter_execution": {"pricing_stage": "多市场确认", "execution_bias": "顺势跟踪多头", "main_driver": "央行路径：多 Agent 裁决偏多。", "invalidation_triggers": ["美元重新转强"]},
                        },
                        "fx_decision_template": {
                            "route_label": "央行路径",
                            "pair_label": "欧美相对增长 Agent",
                            "primary_driver": "央行路径：比较 EUR 与 USD 的政策利差，当前差值 +1.25。",
                            "trigger_signal": "联储官员讲话触发美元回落并推动 EURUSD 重估。",
                            "amplifier": "时间验证一致率 100%；6小时主导波动 0.820%",
                            "execution_bias": "顺势看多",
                            "invalidation_rules": ["若利差与政策路径重新逆转，当前方向判断需要立刻降权。"],
                        },
                        "agent_round_summary": "第1轮补强直接催化，第2轮补足跨资产验证，结论继续偏多。",
                        "memory_takeaway": "最近研究结论继续维持顺势看多。",
                        "confidence_score": 0.82,
                        "key_news": [{"title": "鲍威尔讲话强化降息预期", "impact_reason": "美元回落", "published_at": "2026-04-06T08:00:00"}],
                    },
                    ensure_ascii=False,
                ),
            }

    monkeypatch.setattr(theme_reasoning, "AIAnalyse", FakeAI)

    report = theme_reasoning.build_theme_reasoning_report(
        theme_definition={"label": "美联储官员讲话"},
        asset_context={"current_market": "fx", "current_code": "EURUSD", "asset_name": "欧元美元", "price_direction": "bullish", "latest_change_pct": 0.4},
        theme_news=[{"title": "鲍威尔讲话强化降息预期", "summary": "美元回落", "published_at": "2026-04-06T08:00:00"}],
        propagation_chain=[{"stage": "主题触发", "summary": "联储官员讲话重新定价降息路径"}],
        ontology={"entity_count": 3, "relation_count": 2},
        retrieval_summary={"lookback_hours": 24},
        research_payload={
            "research_tools": [{"label": "主题证据扫描", "summary": "联储转向预期强化", "highlights": ["鲍威尔讲话强化降息预期"]}],
            "actor_profiles": [{"name": "美联储", "actor_type": "CentralBank", "stance": "推动 EURUSD 上行", "summary": "联储仍是主导变量"}],
            "cross_asset_signals": [{"name": "美元指数", "alignment_label": "反向确认", "change_30m_pct": -0.3, "summary": "美元回落"}],
            "similar_cases": [{"title": "历史联储转向阶段", "published_at": "2025-09-01"}],
            "evidence_matrix": {"total_news": 2, "bucket_counts": {"direct": 1, "driver": 1, "background": 0}},
            "agent_rounds": [
                {"round_id": 1, "focus": "direct_evidence", "objective": "补强直接催化", "status": "completed", "search_terms": ["美联储", "鲍威尔"], "evidence_gain": {"delta": 1}},
                {"round_id": 2, "focus": "cross_asset_and_analog", "objective": "补跨资产验证", "status": "completed", "search_terms": ["美元指数", "美债收益率"], "evidence_gain": {"delta": 1}},
            ],
            "rounds_completed": 2,
            "planner_source": "evidence_gap_heuristic",
            "research_digest": "直接证据与驱动链条同时增强。",
            "theme_multi_agent_panel": {
                "mode": "asset_theme_multi_agent",
                "active_agents": [
                    {"id": "evidence_scout", "label": "证据侦察 Agent", "agent_type": "evidence", "role": "主题证据与催化扫描"},
                    {"id": "fx_macro_policy", "label": "央行宏观 Agent", "agent_type": "macro_policy", "role": "央行与宏观主轴"},
                ],
                "agent_outputs": [
                    {"agent_id": "evidence_scout", "label": "证据侦察 Agent", "stance": "偏多", "summary": "主题新闻仍在发酵。"},
                    {"agent_id": "fx_macro_policy", "label": "央行宏观 Agent", "stance": "偏多", "summary": "利率预期对 EURUSD 偏利多。"},
                ],
                "arbiter": {
                    "label": "裁决 Agent",
                    "stance": "偏多",
                    "summary": "多 Agent 裁决偏多，主要来自央行宏观 Agent 与时间验证 Agent 的一致结论。",
                    "confidence": 0.84,
                    "findings": ["形成共识的 Agent：证据侦察 Agent、央行宏观 Agent"],
                },
                "consensus": {"stance": "偏多", "aligned_agents": ["证据侦察 Agent", "央行宏观 Agent"], "conflicting_agents": []},
                "route_context": {
                    "theme_type": "policy_path",
                    "route_label": "央行路径",
                    "pair_code": "EURUSD",
                    "pair_label": "欧美相对增长 Agent",
                    "pair_role": "欧美增长与利差相对强弱",
                },
            },
            "comprehensive_reasoning": {
                "summary": "当前全面推演优先采用「央行路径」框架；跨资产处于「跨资产共振」阶段，确认分数 0.78；裁决层给出的执行偏向为「顺势跟踪多头」，当前定价阶段为「多市场确认」。",
                "router": {"route_label": "央行路径", "focus": "先看相对强弱，再看美元主线、利差、风险偏好与货币对专属机制。"},
                "cross_asset_evidence": {"regime_label": "跨资产共振", "confirmation_score": 0.78, "corroboration_summary": "美元回落与跨资产确认共同支撑 EURUSD 继续偏强。"},
                "arbiter_execution": {"pricing_stage": "多市场确认", "execution_bias": "顺势跟踪多头", "main_driver": "央行路径：多 Agent 裁决偏多。", "invalidation_triggers": ["美元重新转强"]},
            },
            "market_data_snapshot": {
                "asset": {"market": "fx", "code": "EURUSD", "asset_class": "fx"},
                "summary": {"event_count": 1, "factor_count": 1, "metric_count": 1, "reaction_count": 1, "agent_log_count": 0},
                "events": [{"title": "美国 CPI", "symbol": "EURUSD"}],
                "factors": [{"factor_name": "cftc_net_position", "value": 12.5, "unit": "contracts"}],
                "structure_metrics": [{"metric_name": "theme_diffusion_score", "metric_value": 0.78}],
                "price_reactions": [{"reaction_label": "news_followthrough", "return_30m_pct": 0.42}],
                "data_catalog": [
                    {"dataset": "central_bank_rate", "label": "央行决议", "count": 2, "analysis": "用于比较欧央行与美联储相对利差。"},
                    {"dataset": "fx_structure", "label": "外汇结构因子", "count": 1, "analysis": "用于判断 EURUSD 中短线方向。"},
                ],
                "analysis_playbook": [
                    {"step": "先定主轴", "focus": "央行决议 + 外汇结构因子", "method": "先用利差与结构因子定义主方向。"},
                    {"step": "再找催化", "focus": "宏观日历", "method": "再用 CPI、非农等事件确认触发器。"},
                ],
                "agent_logs": [],
                "updated_at": "2026-04-07T16:00:00",
            },
        },
        research_memory={"run_count": 2, "last_trade_bias": "顺势看多", "theme_shift": "最近结论继续维持顺势看多。"},
    )

    assert report["reasoning_source"] == "gemini_llm"
    assert report["ai_status"]["enabled"] is True
    assert "EURUSD受益上行" in report["relationship_chain"][0]
    assert report["future_scenarios"][0].startswith("基准情景")
    assert report["confidence_score"] == 0.82
    assert report["tool_insights"][0].startswith("主题证据扫描")
    assert report["market_data_insights"][0] == "事件：美国 CPI"
    assert report["market_data_catalog"][0].startswith("央行决议")
    assert report["analysis_playbook"][0].startswith("先定主轴")
    assert report["actor_signals"][0].startswith("美联储")
    assert report["multi_agent_consensus"].startswith("多 Agent 裁决偏多")
    assert report["comprehensive_reasoning"]["router"]["route_label"] == "央行路径"
    assert report["cross_asset_corroboration"].startswith("美元回落")
    assert report["fx_decision_template"]["route_label"] == "央行路径"
    assert report["fx_decision_template"]["primary_driver"].startswith("央行路径")
    assert "第1轮补强直接催化" in report["agent_round_summary"]
    assert report["research_agent"]["manual_trigger_only"] is True
    assert report["research_agent"]["rounds_completed"] == 2
    assert report["research_agent"]["theme_multi_agent_panel"]["arbiter"]["summary"].startswith("多 Agent 裁决偏多")
    assert report["research_agent"]["active_theme_agents"][0]["label"] == "证据侦察 Agent"
    assert report["research_agent"]["comprehensive_reasoning"]["arbiter_execution"]["pricing_stage"] == "多市场确认"
    assert report["research_agent"]["fx_decision_template"]["pair_label"] == "欧美相对增长 Agent"
    assert report["research_agent"]["market_data_digest"]["summary"].startswith("市场数据底座已补充")
    assert report["research_agent"]["market_data_digest"]["catalog_overview"][0].startswith("央行决议")
    assert report["research_agent"]["market_data_digest"]["analysis_focus"][0].startswith("先定主轴")
    assert report["research_agent"]["market_data_catalog"][0]["label"] == "央行决议"
    assert report["research_agent"]["market_data_playbook"][0]["step"] == "先定主轴"
    assert report["research_agent"]["report_sections"][1]["title"] == "证据与主体"
    assert any(item["stage"] == "market_data" for item in report["research_agent"]["agent_journal"])
    assert report["research_agent"]["agent_journal"][-1]["stage"] == "memory"


def test_build_theme_reasoning_report_marks_ai_unavailable_when_model_is_not_gemini(monkeypatch):
    monkeypatch.setattr(theme_reasoning.cl_config, "OPENROUTER_AI_MODEL", "openai/gpt-4o")
    monkeypatch.setattr(theme_reasoning.cl_config, "OPENROUTER_AI_KEYS", "test-key")

    report = theme_reasoning.build_theme_reasoning_report(
        theme_definition={"label": "特朗普讲话"},
        asset_context={"current_market": "futures", "current_code": "XAU", "asset_name": "黄金", "price_direction": "bearish", "latest_change_pct": -0.2},
        theme_news=[],
        propagation_chain=[],
        ontology={"entity_count": 0, "relation_count": 0},
        retrieval_summary={"lookback_hours": 24},
        research_payload={
            "research_tools": [{"label": "主题证据扫描", "summary": "暂无直接证据"}],
            "agent_rounds": [{"round_id": 1, "focus": "direct_evidence", "objective": "补直接证据", "status": "no_new_evidence", "search_terms": ["特朗普", "黄金"], "evidence_gain": {"delta": 0}}],
            "rounds_completed": 1,
        },
        research_memory={"run_count": 1, "last_trade_bias": "观望"},
    )

    assert report["reasoning_source"] == "rule_engine"
    assert report["ai_status"]["enabled"] is False
    assert "Gemini" in report["ai_status"]["message"]
    assert report["research_agent"]["tool_findings"][0]["label"] == "主题证据扫描"
    assert report["research_agent"]["agent_rounds"][0]["focus"] == "direct_evidence"
    assert report["research_agent"]["report_sections"][0]["title"] == "市场结论"
    assert report["research_agent"]["comprehensive_reasoning"] == {}
    assert report["fx_decision_template"] == {}


def test_market_data_schema_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(chanlun_db.config, "DB_TYPE", "sqlite", raising=False)
    monkeypatch.setattr(chanlun_db.config, "DB_DATABASE", "market_data_schema_test", raising=False)
    monkeypatch.setattr(chanlun_db, "get_data_path", lambda: tmp_path)

    temp_db = chanlun_db.DB.__wrapped__()

    temp_db.market_event_fact_upsert(
        {
            "event_type": "macro_calendar",
            "asset_class": "fx",
            "region": "us",
            "symbol": "EURUSD",
            "title": "美国 CPI 公布",
            "source_name": "akshare_macro_info_ws",
            "actual_value": 3.2,
            "forecast_value": 3.0,
            "previous_value": 3.1,
            "surprise_value": 0.2,
            "published_at": datetime(2026, 4, 7, 20, 30),
        }
    )
    temp_db.market_factor_snapshot_upsert(
        {
            "factor_group": "yield_curve",
            "factor_name": "yield_curve_point",
            "asset_class": "rates_futures",
            "symbol": "中债国债收益率曲线",
            "tenor": "10年",
            "value": 2.15,
            "unit": "%",
            "source_name": "akshare_bond_china_yield",
            "as_of_time": datetime(2026, 4, 7, 15, 0),
        }
    )
    temp_db.market_structure_metric_upsert(
        {
            "asset_class": "equity",
            "symbol": "AI主题",
            "metric_name": "theme_diffusion_score",
            "metric_value": 0.81,
            "window": "1d",
            "source_name": "internal",
            "as_of_time": datetime(2026, 4, 7, 15, 0),
        }
    )
    temp_db.agent_inference_log_insert(
        {
            "run_id": "run-1",
            "agent_name": "PriceValidationAgent",
            "asset_class": "fx",
            "symbol": "EURUSD",
            "question": "事件后 EURUSD 是否延续？",
            "thesis": "30 分钟仍延续上行",
            "confidence_before": 0.61,
            "confidence_after": 0.74,
            "used_event_ids": ["evt-1"],
            "used_factor_ids": ["factor-1"],
            "changed_conclusion": True,
        }
    )
    temp_db.event_price_reaction_upsert(
        {
            "event_uid": "evt-1",
            "symbol": "EURUSD",
            "frequency": "30m",
            "return_30m_pct": 0.36,
            "return_120m_pct": 0.54,
            "return_1d_pct": 0.82,
            "direction_aligned": True,
            "reaction_label": "bullish_followthrough",
            "validated_at": datetime(2026, 4, 7, 21, 0),
        }
    )

    event_rows = temp_db.market_event_fact_query(symbol="EURUSD", limit=5)
    factor_rows = temp_db.market_factor_snapshot_query(symbol="中债国债收益率曲线", limit=5)
    metric_rows = temp_db.market_structure_metric_query(symbol="AI主题", limit=5)
    log_rows = temp_db.agent_inference_log_query(run_id="run-1", limit=5)
    reaction_rows = temp_db.event_price_reaction_query(event_uid="evt-1", limit=5)

    assert event_rows[0].surprise_value == 0.2
    assert factor_rows[0].tenor == "10年"
    assert metric_rows[0].metric_name == "theme_diffusion_score"
    assert log_rows[0].agent_name == "PriceValidationAgent"
    assert reaction_rows[0].direction_aligned == 1


def test_akshare_market_data_adapter_normalizes_and_syncs_records():
    class FakeDB:
        def __init__(self):
            self.events = []
            self.factors = []

        def market_event_fact_upsert(self, payload):
            self.events.append(payload)
            return True

        def market_factor_snapshot_upsert(self, payload):
            self.factors.append(payload)
            return True

    class FakeAk:
        def __init__(self):
            self.macro_dates = []
            self.inventory_symbols = []

        def macro_info_ws(self, date):
            self.macro_dates.append(date)
            return pd.DataFrame(
                [
                    {
                        "事件": "美国 CPI",
                        "地区": "美国",
                        "时间": f"{date} 20:30:00",
                        "今值": 3.2,
                        "预期值": 3.0,
                        "前值": 3.1,
                        "重要性": 3,
                    }
                ]
            )

        def futures_inventory_em(self, symbol):
            self.inventory_symbols.append(symbol)
            if symbol not in {"CU", "AU", "MA"}:
                raise ValueError("请输入正确的 symbol")
            return pd.DataFrame(
                [
                    {
                        "日期": "2026-04-07",
                        "库存": 120000,
                        "增减": -2500,
                        "单位": "吨",
                    }
                ]
            )

        def macro_usa_cftc_nc_holding(self):
            return pd.DataFrame(
                [
                    {
                        "日期": "2026-04-07",
                        "欧元非商业多头持仓": 150.0,
                        "欧元非商业空头持仓": 100.0,
                        "日元非商业多头持仓": 90.0,
                        "日元非商业空头持仓": 140.0,
                    }
                ]
            )

        def stock_hsgt_fund_flow_summary_em(self):
            return pd.DataFrame(
                [
                    {
                        "交易日": "2026-04-07",
                        "资金方向": "北向资金",
                        "板块": "沪股通",
                        "成交净买额": 58.4,
                        "资金净流入": 61.2,
                    }
                ]
            )

    fake_db = FakeDB()
    fake_ak = FakeAk()
    adapter = market_data_adapter.AkshareMarketDataAdapter(ak_module=fake_ak, db_instance=fake_db)

    macro_events = adapter.fetch_macro_calendar_events("2026-04-07")
    inventory_factors = adapter.fetch_futures_inventory_snapshots("CU")
    inventory_alias_factors = adapter.fetch_futures_inventory_snapshots("XAU")
    inventory_main_contract_factors = adapter.fetch_futures_inventory_snapshots("QZ.MAL8")
    cftc_fx_factors = adapter.fetch_cftc_snapshots("EURUSD")
    unsupported_inventory_factors = adapter.fetch_futures_inventory_snapshots("CL")
    hsgt_factors = adapter.fetch_stock_hsgt_snapshots()

    assert fake_ak.macro_dates == ["20260407"]
    assert macro_events[0]["surprise_value"] == 0.2
    assert inventory_factors[0]["factor_group"] == "inventory"
    assert inventory_alias_factors[0]["symbol"] == "AU"
    assert inventory_main_contract_factors[0]["symbol"] == "MA"
    assert cftc_fx_factors[0]["symbol"] == "EURUSD"
    assert cftc_fx_factors[0]["value"] == 50.0
    assert unsupported_inventory_factors == []
    assert hsgt_factors[0]["symbol"] == "北向资金"

    assert adapter.sync_records("event", macro_events) == 1
    assert adapter.sync_records("factor", inventory_factors + hsgt_factors) == 2
    assert len(fake_db.events) == 1
    assert len(fake_db.factors) == 2


def test_normalize_akshare_futures_symbol_supports_main_contract_codes():
    assert market_data_adapter.normalize_akshare_futures_symbol("QZ.MAL8") == "MA"
    assert market_data_adapter.normalize_akshare_futures_symbol("CZ.IC2509") == "IC"
    assert market_data_adapter.normalize_akshare_futures_symbol("QG.LCL8") == "lc"


def test_fetch_cftc_snapshots_supports_forex_pair_aliases():
    class FakeAk:
        def macro_usa_cftc_nc_holding(self):
            return pd.DataFrame(
                [
                    {
                        "日期": "2026-04-07",
                        "欧元非商业多头持仓": 210.0,
                        "欧元非商业空头持仓": 160.0,
                    }
                ]
            )

    adapter = market_data_adapter.AkshareMarketDataAdapter(ak_module=FakeAk(), db_instance=None)
    records = adapter.fetch_cftc_snapshots("EURUSD")

    assert len(records) == 1
    assert records[0]["symbol"] == "EURUSD"
    assert records[0]["value"] == 50.0


def test_build_market_data_view_payload_aggregates_new_tables(monkeypatch):
    event_row = SimpleNamespace(
        event_uid="evt-1",
        event_type="macro_calendar",
        asset_class="macro",
        region="us",
        symbol="EURUSD",
        title="美国 CPI",
        source_name="akshare_macro_info_ws",
        importance_score=3,
        actual_value=3.2,
        forecast_value=3.0,
        previous_value=3.1,
        surprise_value=0.2,
        published_at=datetime(2026, 4, 7, 20, 30),
        effective_at=datetime(2026, 4, 7, 20, 30),
    )
    factor_row = SimpleNamespace(
        snapshot_uid="factor-1",
        factor_group="cross_border_flow",
        factor_name="northbound_net_flow",
        asset_class="equity",
        symbol="NORTHBOUND",
        tenor="",
        value=58.4,
        unit="cny",
        change_1d=None,
        change_5d=None,
        zscore_60d=None,
        source_name="akshare_stock_hsgt_fund_flow_summary_em",
        as_of_time=datetime(2026, 4, 7, 15, 0),
    )
    metric_row = SimpleNamespace(
        metric_uid="metric-1",
        asset_class="equity",
        symbol="000001",
        metric_name="theme_diffusion_score",
        metric_value=0.78,
        window="1d",
        cross_section_rank=0.9,
        source_name="internal",
        as_of_time=datetime(2026, 4, 7, 15, 0),
    )
    reaction_row = SimpleNamespace(
        reaction_uid="reaction-1",
        event_uid="evt-1",
        symbol="000001",
        frequency="30m",
        return_30m_pct=0.52,
        return_120m_pct=0.75,
        return_1d_pct=1.1,
        return_5d_pct=2.3,
        direction_aligned=1,
        reaction_label="bullish_followthrough",
        validated_at=datetime(2026, 4, 7, 16, 0),
    )
    log_row = SimpleNamespace(
        id=1,
        run_id="run-1",
        agent_name="PriceValidationAgent",
        asset_class="equity",
        symbol="000001",
        question="是否延续？",
        thesis="有延续",
        confidence_before=0.62,
        confidence_after=0.78,
        changed_conclusion="true",
        created_at=datetime(2026, 4, 7, 16, 5),
    )

    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "平安银行", "type": "stock"})
    monkeypatch.setattr(api.db, "market_event_fact_query", lambda **kwargs: [event_row])
    monkeypatch.setattr(api.db, "market_factor_snapshot_query", lambda **kwargs: [factor_row])
    monkeypatch.setattr(api.db, "market_structure_metric_query", lambda **kwargs: [metric_row])
    monkeypatch.setattr(api.db, "event_price_reaction_query", lambda **kwargs: [reaction_row])
    monkeypatch.setattr(api.db, "agent_inference_log_query", lambda **kwargs: [log_row])

    payload = api._build_market_data_view_payload("a", "000001", limit=6)

    assert payload["asset"]["asset_class"] == "equity"
    assert payload["summary"]["event_count"] == 1
    assert payload["events"][0]["title"] == "美国 CPI"
    assert payload["factors"][0]["factor_name"] == "northbound_net_flow"
    assert payload["price_reactions"][0]["reaction_label"] == "bullish_followthrough"
    assert payload["agent_logs"][0]["agent_name"] == "PriceValidationAgent"
    assert payload["summary"]["catalog_total"] >= 6
    assert payload["summary"]["catalog_synced"] >= 4
    assert any(item["dataset"] == "stock_hsgt" for item in payload["data_catalog"])
    assert any(item["step"] == "先找催化" for item in payload["analysis_playbook"])


def test_sync_market_data_for_asset_returns_sync_result(monkeypatch):
    class FakeAdapter:
        def __init__(self, db_instance=None):
            self.db_instance = db_instance
            self.available = True

        def fetch_stock_profit_forecast_snapshots(self, symbol=""):
            return [{"symbol": symbol or "000001"}]

        def fetch_stock_fund_flow_snapshots(self, indicator="即时"):
            return [{"symbol": "000001"}]

        def fetch_stock_hsgt_snapshots(self):
            return [{"symbol": "北向资金"}]

        def fetch_stock_repurchase_events(self):
            return [{"symbol": "000001"}]

        def fetch_stock_restricted_release_events(self, symbol="全部股票", start_date="", end_date=""):
            return [{"symbol": "000001"}]

        def sync_records(self, dataset_type, records):
            return len(records)

    monkeypatch.setattr(api, "_get_product_info", lambda code, market="": {"name_cn": "平安银行", "type": "stock"})
    monkeypatch.setattr(api, "AkshareMarketDataAdapter", FakeAdapter)
    monkeypatch.setattr(api, "_build_market_data_view_payload", lambda market, code, limit=8: {
        "asset": {"market": market, "code": code, "asset_class": "equity"},
        "summary": {"event_count": 2, "factor_count": 3, "metric_count": 0, "reaction_count": 0, "agent_log_count": 0},
        "events": [],
        "factors": [],
        "structure_metrics": [],
        "price_reactions": [],
        "agent_logs": [],
        "sync_plan": [],
        "updated_at": "2026-04-07T16:00:00",
    })

    payload = api._sync_market_data_for_asset("a", "000001")

    assert payload["sync_result"]["saved_total"] == 5
    assert len(payload["sync_result"]["tasks"]) == 5
    assert payload["asset"]["asset_class"] == "equity"


def test_build_fx_structure_metrics_from_task_records():
    metrics = api._build_fx_structure_metrics_from_task_records(
        "EURUSD",
        {
            "type": "forex",
            "symbol": "EURUSD",
            "base_currency": "EUR",
            "quote_currency": "USD",
        },
        {
            "central_bank_rate": [
                {
                    "region": "ecb",
                    "actual_value": 4.0,
                    "surprise_value": 0.1,
                    "effective_at": datetime(2026, 4, 7, 20, 0),
                },
                {
                    "region": "federal_reserve",
                    "actual_value": 5.25,
                    "surprise_value": -0.05,
                    "effective_at": datetime(2026, 4, 7, 20, 0),
                },
            ],
            "cftc": [
                {
                    "symbol": "EURUSD",
                    "factor_group": "positioning",
                    "value": 75.0,
                    "as_of_time": datetime(2026, 4, 7, 15, 0),
                }
            ],
        },
    )

    metric_names = {item["metric_name"] for item in metrics}
    metric_values = {item["metric_name"]: item["metric_value"] for item in metrics}
    assert "policy_rate_differential" in metric_names
    assert "policy_surprise_differential" in metric_names
    assert "cftc_positioning_bias" in metric_names
    assert "usd_counter_currency_pressure" in metric_names
    assert metric_values["policy_rate_differential"] == -1.25
    assert metric_values["policy_surprise_differential"] == pytest.approx(0.15)
    assert metric_values["cftc_positioning_bias"] == 75.0
    assert metric_values["usd_counter_currency_pressure"] == 75.0


def test_sync_market_data_for_fx_persists_structure_metrics(monkeypatch):
    class FakeAdapter:
        def __init__(self, db_instance=None):
            self.db_instance = db_instance
            self.available = True
            self.sync_calls = []

        def fetch_macro_calendar_events(self, date=""):
            return [{"title": "美国 CPI", "symbol": "macro"}]

        def fetch_central_bank_rate_events(self, bank=""):
            if bank == "ecb":
                return [{"region": "ecb", "actual_value": 4.0, "surprise_value": 0.1, "effective_at": datetime(2026, 4, 7, 20, 0)}]
            if bank == "federal_reserve":
                return [{"region": "federal_reserve", "actual_value": 5.25, "surprise_value": -0.05, "effective_at": datetime(2026, 4, 7, 20, 0)}]
            return []

        def fetch_cftc_snapshots(self, symbol=""):
            return [{"symbol": symbol, "factor_group": "positioning", "value": 70.0, "as_of_time": datetime(2026, 4, 7, 15, 0)}]

        def sync_records(self, dataset_type, records):
            self.sync_calls.append((dataset_type, records))
            return len(records)

    fake_adapter = FakeAdapter()
    monkeypatch.setattr(
        api,
        "_get_product_info",
        lambda code, market="": {"name_cn": "欧元美元", "type": "forex", "symbol": "EURUSD", "base_currency": "EUR", "quote_currency": "USD"},
    )
    monkeypatch.setattr(api, "AkshareMarketDataAdapter", lambda db_instance=None: fake_adapter)
    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda market, code, limit=8: {
            "asset": {"market": market, "code": code, "asset_class": "fx"},
            "summary": {"event_count": 3, "factor_count": 1, "metric_count": 4, "reaction_count": 0, "agent_log_count": 0},
            "events": [],
            "factors": [],
            "structure_metrics": [],
            "price_reactions": [],
            "agent_logs": [],
            "sync_plan": [],
            "updated_at": "2026-04-07T16:00:00",
        },
    )

    payload = api._sync_market_data_for_asset("fx", "EURUSD")

    assert payload["sync_result"]["saved_total"] == 9
    assert any(item["dataset"] == "fx_structure" and item["saved"] == 5 for item in payload["sync_result"]["tasks"])
    structure_sync = [item for item in fake_adapter.sync_calls if item[0] == "structure"]
    assert len(structure_sync) == 1
    assert {metric["metric_name"] for metric in structure_sync[0][1]} == {
        "policy_rate_differential",
        "policy_surprise_differential",
        "cftc_positioning_bias",
        "usd_counter_currency_pressure",
        "policy_relative_strength_score",
    }
