from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Sequence
from urllib.parse import urlencode

from sqlalchemy import or_

from chanlun.base import Market
from chanlun.db import db
from chanlun.db import TableByCompanyFinancials
from chanlun.exchange import get_exchange
from chanlun.tools.ai_analyse import AIAnalyse

from .a_share_matches_quotes import (
    fetch_tick_snapshots,
    infer_project_quote_target,
    normalize_a_share_code,
    normalize_hk_code,
)
from .a_share_matches_tweets import build_tweet_detail_url
from .smart_news_search import search_stock_news as search_news_by_stock


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def build_stock_analysis_detail_url(
    *,
    entity_type: str,
    identifier: str,
    display_name: str = "",
    company_name: str = "",
    exchange: str = "",
    market: str = "",
    numeric_code: str = "",
) -> str:
    normalized_type = _normalize_text(entity_type) or "project"
    normalized_identifier = _normalize_text(identifier)
    params = {
        "display_name": _normalize_text(display_name),
        "company_name": _normalize_text(company_name),
        "exchange": _normalize_text(exchange),
        "market": _normalize_text(market),
        "numeric_code": _normalize_text(numeric_code),
    }
    query = urlencode({k: v for k, v in params.items() if v})
    base = f"/a_share_matches/stock-analysis/{normalized_type}/{normalized_identifier}"
    return f"{base}?{query}" if query else base


def _pick_latest_metric(records: Sequence[Any], aliases: Sequence[str]) -> tuple[tuple[dt.date, float] | None, tuple[dt.date, float] | None]:
    matched: dict[dt.date, float] = {}
    alias_keys = {alias.casefold() for alias in aliases}
    for row in records:
        item_name = _normalize_text(getattr(row, "item_name", ""))
        if not item_name:
            continue
        lower_name = item_name.casefold()
        if not any(alias in lower_name for alias in alias_keys):
            continue
        report_date = getattr(row, "report_date", None)
        item_value = getattr(row, "item_value", None)
        if report_date is None or item_value is None:
            continue
        if report_date not in matched:
            try:
                matched[report_date] = float(item_value)
            except (TypeError, ValueError):
                continue
    if not matched:
        return None, None
    sorted_dates = sorted(matched.keys(), reverse=True)
    latest = (sorted_dates[0], matched[sorted_dates[0]])
    previous = (sorted_dates[1], matched[sorted_dates[1]]) if len(sorted_dates) > 1 else None
    return latest, previous


def _format_change(current: float, previous: float) -> str:
    if previous == 0:
        return "变化基数为 0"
    change = ((current - previous) / abs(previous)) * 100
    return f"{change:+.1f}%"


def _format_number(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_0000_0000:
        return f"{value / 1_0000_0000:.2f}亿"
    if abs_value >= 1_0000:
        return f"{value / 1_0000:.2f}万"
    return f"{value:.2f}"


def _format_live_price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if abs(number) >= 100:
        return f"{number:.2f}"
    if abs(number) >= 1:
        return f"{number:.3f}"
    return f"{number:.4f}"


def _format_live_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.2f}%"


def _build_empty_live_quote(market_text: str = "") -> dict[str, str]:
    return {
        "price_text": "--",
        "change_text": "--",
        "market_cap_text": "实时总市值待行情源补齐",
        "swing_text": "--",
        "range_text": "--",
        "market_text": _normalize_text(market_text).upper() or "--",
    }


def _build_live_quote_snapshot(
    *,
    entity_type: str,
    identifier: str,
    exchange: str = "",
    market: str = "",
    company_name: str = "",
) -> dict[str, str]:
    normalized_type = _normalize_text(entity_type)
    normalized_identifier = _normalize_text(identifier)
    normalized_market = _normalize_text(market).upper()
    live_quote = _build_empty_live_quote(normalized_market)
    if not normalized_type or not normalized_identifier:
        return live_quote

    try:
        if normalized_type == "match" or normalized_market in {"A", "CN", "CHINA"}:
            ex = get_exchange(Market.A)
            code = normalize_a_share_code(normalized_identifier)
            snapshots = fetch_tick_snapshots(ex, [code])
            snapshot = snapshots.get(code) or next(iter(snapshots.values()), None)
            market_label = "A"
        else:
            target = infer_project_quote_target(
                normalized_identifier,
                _normalize_text(exchange),
                _normalize_text(market),
                _normalize_text(company_name),
            )
            if not target:
                return live_quote
            market_key = str(target.get("market") or "").strip().lower()
            code = str(target.get("code") or "").strip()
            if not market_key or not code:
                return live_quote
            ex = get_exchange(Market(market_key))
            snapshots = fetch_tick_snapshots(ex, [code])
            snapshot = snapshots.get(code) or next(iter(snapshots.values()), None)
            market_label = market_key.upper()
    except Exception:
        return live_quote

    if not snapshot:
        return live_quote

    low_text = _format_live_price(snapshot.get("low"))
    high_text = _format_live_price(snapshot.get("high"))
    return {
        "price_text": _format_live_price(snapshot.get("price")),
        "change_text": _format_live_percent(snapshot.get("rate")),
        "market_cap_text": str(snapshot.get("market_cap_text") or "实时总市值待行情源补齐"),
        "swing_text": _format_live_percent(snapshot.get("swing_rate")),
        "range_text": f"{low_text} - {high_text}",
        "market_text": market_label,
    }


def _build_financial_summary(records: Sequence[Any]) -> tuple[str, str]:
    if not records:
        return "暂无财务数据。", "暂无财务数据"

    revenue_latest, revenue_previous = _pick_latest_metric(
        records,
        ["revenue", "sales", "营业收入", "营收"],
    )
    profit_latest, profit_previous = _pick_latest_metric(
        records,
        ["net income", "net profit", "净利润", "profit attributable"],
    )

    parts = []
    short_parts = []

    if revenue_latest is not None:
        revenue_text = f"最新营收 {_format_number(revenue_latest[1])}"
        if revenue_previous is not None:
            revenue_text += f"，较上期 {_format_change(revenue_latest[1], revenue_previous[1])}"
        parts.append(revenue_text)
        short_parts.append(revenue_text)

    if profit_latest is not None:
        profit_text = f"最新净利 {_format_number(profit_latest[1])}"
        if profit_previous is not None:
            profit_text += f"，较上期 {_format_change(profit_latest[1], profit_previous[1])}"
        parts.append(profit_text)
        if len(short_parts) < 2:
            short_parts.append(profit_text)

    if not parts:
        latest_record = records[0]
        parts.append(
            f"最新报告期 {getattr(latest_record, 'report_date', '')} 已入库，共 {len(records)} 条财务记录。"
        )
        short_parts.append("财务数据已入库，等待关键指标补齐。")

    return "；".join(parts) + "。", "；".join(short_parts) + "。"


def _find_selection_metrics(entity_type: str, identifier: str) -> dict[str, Any]:
    normalized_type = _normalize_text(entity_type)
    normalized_identifier = _normalize_text(identifier).upper()
    if not normalized_type or not normalized_identifier:
        return {}

    from .a_share_matches_catalog import get_a_share_match_catalog

    catalog = get_a_share_match_catalog()
    for theme in catalog.get("themes", []):
        for stock in theme.get("project_stocks", []):
            if normalized_type == "project" and _normalize_text(stock.get("symbol")).upper() == normalized_identifier:
                return {
                    "selection_reason": stock.get("selection_reason") or {},
                    "scarcity_view": stock.get("scarcity_view") or {},
                    "capacity_view": stock.get("capacity_view") or {},
                    "pricing_view": stock.get("pricing_view") or {},
                    "market_cap_research": stock.get("market_cap_research") or {},
                    "segment_market_view": stock.get("segment_market_view") or {},
                }
            if normalized_type == "match":
                for match in list(stock.get("main_matches") or []) + list(stock.get("candidate_matches") or []):
                    if _normalize_text(match.get("code")).upper() == normalized_identifier:
                        return {
                            "selection_reason": match.get("selection_reason") or {},
                            "scarcity_view": match.get("scarcity_view") or {},
                            "capacity_view": match.get("capacity_view") or {},
                            "pricing_view": match.get("pricing_view") or {},
                            "market_cap_research": match.get("market_cap_research") or {},
                            "segment_market_view": match.get("segment_market_view") or {},
                        }
    return {}


def _default_selection_metrics() -> dict[str, dict[str, str]]:
    from .a_share_matches_catalog import (
        _capacity_view,
        _market_cap_research,
        _pricing_view,
        _scarcity_view,
        _segment_market_view,
        _selection_reason,
    )

    return {
        "selection_reason": _selection_reason(),
        "scarcity_view": _scarcity_view(),
        "capacity_view": _capacity_view(),
        "pricing_view": _pricing_view(),
        "market_cap_research": _market_cap_research(),
        "segment_market_view": _segment_market_view(),
    }


def _merge_selection_metrics(metrics: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    source_metrics = metrics or {}
    for key, default_value in _default_selection_metrics().items():
        current_value = source_metrics.get(key)
        if isinstance(current_value, dict):
            merged[key] = {**default_value, **current_value}
        else:
            merged[key] = dict(default_value)
    return merged


def _sort_news_rows(rows: Sequence[Any]) -> list[Any]:
    def _key(item: Any) -> tuple[float, dt.datetime]:
        importance = float(getattr(item, "importance_score", 0) or 0)
        published_at = getattr(item, "published_at", None)
        if isinstance(published_at, str):
            try:
                published_at = dt.datetime.fromisoformat(published_at)
            except ValueError:
                published_at = dt.datetime.min
        if published_at is None:
            published_at = dt.datetime.min
        return (importance, published_at)

    return sorted(list(rows), key=_key, reverse=True)


def _build_news_preview(rows: Sequence[Any], limit: int) -> list[dict[str, str]]:
    previews = []
    for row in _sort_news_rows(rows)[:limit]:
        published_at = getattr(row, "published_at", "")
        if isinstance(published_at, dt.datetime):
            published_at_text = published_at.strftime("%Y-%m-%d %H:%M")
        else:
            published_at_text = _normalize_text(published_at)
        previews.append(
            {
                "title": _normalize_text(getattr(row, "title", "")) or "未命名新闻",
                "published_at": published_at_text,
                "source": _normalize_text(getattr(row, "source", "")) or "未知来源",
            }
        )
    return previews


def _search_local_news(
    *,
    identifier: str,
    display_name: str,
    company_name: str,
    limit: int,
) -> tuple[list[dict[str, str]], str]:
    keywords = [_normalize_text(display_name), _normalize_text(company_name), _normalize_text(identifier)]
    keywords = [keyword for keyword in keywords if keyword]
    rows = db.news_search(
        query_text=keywords[0] if keywords else None,
        keywords=keywords,
        limit=max(limit, 10),
    )
    if rows:
        return _build_news_preview(rows, limit), "workspace"

    stock_input = _normalize_text(company_name) or _normalize_text(display_name) or _normalize_text(identifier)
    if not stock_input:
        return [], "unavailable"

    try:
        fallback_result = search_news_by_stock(stock_input, vector_db=None, n_results=max(limit, 10), days_back=30)
    except TypeError:
        fallback_result = search_news_by_stock(stock_input, n_results=max(limit, 10), days_back=30)
    except Exception:
        fallback_result = {"success": False, "results": [], "total_found": 0}

    previews = []
    for item in (fallback_result or {}).get("results", [])[:limit]:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        previews.append(
            {
                "title": _normalize_text(item.get("title") if isinstance(item, dict) else "") or "未命名新闻",
                "published_at": _normalize_text(metadata.get("published_at")),
                "source": _normalize_text(metadata.get("source")) or "本地回退",
            }
        )
    if previews:
        return previews, "local_fallback"
    return [], "unavailable"


def _dedupe_financial_rows(rows: Sequence[Any]) -> list[Any]:
    deduped = []
    seen = set()
    for row in rows:
        key = (
            getattr(row, "code", None),
            getattr(row, "name", None),
            getattr(row, "report_date", None),
            getattr(row, "statement_type", None),
            getattr(row, "item_name", None),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    deduped.sort(
        key=lambda item: (
            getattr(item, "report_date", dt.date.min) or dt.date.min,
            _normalize_text(getattr(item, "item_name", "")),
        ),
        reverse=True,
    )
    return deduped


def _build_financial_code_candidates(
    *,
    entity_type: str,
    identifier: str,
    exchange: str,
    market: str,
    numeric_code: str,
) -> list[str]:
    candidates = []
    normalized_identifier = _normalize_text(identifier).upper()
    normalized_exchange = _normalize_text(exchange).upper()
    normalized_market = _normalize_text(market).upper()
    normalized_numeric_code = _normalize_text(numeric_code).upper()

    for raw in [normalized_identifier, normalized_numeric_code]:
        if raw and raw not in candidates:
            candidates.append(raw)

    if entity_type == "match" or normalized_market in {"A", "CN", "CHINA"} or normalized_exchange in {"SSE", "SZSE", "BSE", "STAR", "CHINEXT"}:
        for raw in [normalized_identifier, normalized_numeric_code]:
            normalized = normalize_a_share_code(raw)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

    if normalized_market in {"HK", "HONG KONG"} or normalized_exchange in {"HKG", "HKEX", "SEHK"}:
        for raw in [normalized_identifier, normalized_numeric_code]:
            normalized = normalize_hk_code(raw)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

    return [candidate for candidate in candidates if candidate]


def _query_financial_rows(
    *,
    entity_type: str,
    identifier: str,
    company_name: str,
    exchange: str = "",
    market: str = "",
    numeric_code: str = "",
) -> list[Any]:
    rows = []
    for code in _build_financial_code_candidates(
        entity_type=entity_type,
        identifier=identifier,
        exchange=exchange,
        market=market,
        numeric_code=numeric_code,
    ):
        query_rows = list(db.company_financials_query(code=code, limit=200))
        if query_rows:
            rows.extend(query_rows)

    normalized_company_name = _normalize_text(company_name)
    if normalized_company_name:
        exact_name_rows = list(db.company_financials_query(name=normalized_company_name, limit=200))
        if exact_name_rows:
            rows.extend(exact_name_rows)
        else:
            with db.Session() as session:
                fuzzy_rows = (
                    session.query(TableByCompanyFinancials)
                    .filter(
                        or_(
                            TableByCompanyFinancials.name.ilike(f"%{normalized_company_name}%"),
                            TableByCompanyFinancials.name.ilike(f"%{normalized_company_name.replace('.', '')}%"),
                        )
                    )
                    .order_by(TableByCompanyFinancials.report_date.desc(), TableByCompanyFinancials.item_name)
                    .limit(200)
                    .all()
                )
                rows.extend(fuzzy_rows)

    return _dedupe_financial_rows(rows)


def _build_ai_financial_analysis(records: Sequence[Any], display_name: str) -> str:
    if not records:
        return "暂无财务数据，无法生成 AI 解读。"
    summary, _ = _build_financial_summary(records)
    prompt = (
        f"请基于以下财务摘要，为{display_name or '该股票'}输出一段简洁的中文财务解读，"
        "重点突出最新一期变化、盈利趋势和风险提示，控制在180字以内。\n"
        f"财务摘要：{summary}"
    )
    try:
        result = AIAnalyse("a").req_openrouter_ai_model(prompt)
    except Exception as exc:
        return f"AI 财务解读暂不可用：{exc}"
    if isinstance(result, dict) and result.get("ok"):
        return _normalize_text(result.get("msg")) or "AI 未返回有效内容。"
    error_msg = ""
    if isinstance(result, dict):
        error_msg = _normalize_text(result.get("msg"))
    return f"AI 财务解读暂不可用：{error_msg or '未知错误'}"


def _build_summary_item(item: dict[str, Any]) -> dict[str, Any]:
    entity_type = _normalize_text(item.get("entity_type")) or "project"
    identifier = _normalize_text(item.get("identifier") or item.get("symbol") or item.get("code"))
    display_name = _normalize_text(item.get("display_name"))
    company_name = _normalize_text(item.get("company_name"))
    exchange = _normalize_text(item.get("exchange"))
    market = _normalize_text(item.get("market"))
    numeric_code = _normalize_text(item.get("numeric_code"))
    chart_url = _normalize_text(item.get("chart_url"))

    financial_rows = _query_financial_rows(
        entity_type=entity_type,
        identifier=identifier,
        company_name=company_name,
        exchange=exchange,
        market=market,
        numeric_code=numeric_code,
    )
    financial_summary, financial_summary_short = _build_financial_summary(financial_rows)
    financial_source = "workspace" if financial_rows else "unavailable"

    return {
        "entity_type": entity_type,
        "identifier": identifier,
        "display_name": display_name,
        "company_name": company_name,
        "exchange": exchange,
        "market": market,
        "chart_url": chart_url,
        "financial_summary": financial_summary,
        "financial_summary_short": financial_summary_short,
        "financial_source": financial_source,
        "news_source": "hidden",
        "latest_news": [],
        "analysis_source_label": "Workspace" if financial_source == "workspace" else "",
        "detail_url": build_stock_analysis_detail_url(
            entity_type=entity_type,
            identifier=identifier,
            display_name=display_name,
            company_name=company_name,
            exchange=exchange,
            market=market,
        ),
    }


def build_stock_analysis_summaries(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_build_summary_item(item) for item in items or []]


def build_stock_analysis_detail_payload(
    *,
    entity_type: str,
    identifier: str,
    display_name: str = "",
    company_name: str = "",
    exchange: str = "",
    market: str = "",
    numeric_code: str = "",
    chart_url: str = "",
) -> dict[str, Any]:
    summary = _build_summary_item(
        {
            "entity_type": entity_type,
            "identifier": identifier,
            "display_name": display_name,
            "company_name": company_name,
            "exchange": exchange,
            "market": market,
            "numeric_code": _normalize_text(numeric_code),
            "chart_url": chart_url,
        }
    )
    financial_rows = _query_financial_rows(
        entity_type=entity_type,
        identifier=identifier,
        company_name=company_name,
        exchange=exchange,
        market=market,
        numeric_code=_normalize_text(numeric_code),
    )
    latest_news, news_source = _search_local_news(
        identifier=identifier,
        display_name=display_name,
        company_name=company_name,
        limit=10,
    )
    live_quote = _build_live_quote_snapshot(
        entity_type=entity_type,
        identifier=identifier,
        exchange=exchange,
        market=market,
        company_name=company_name,
    )

    payload = {
        **summary,
        "latest_news": latest_news,
        "news_source": news_source,
        "financial_ai_analysis": _build_ai_financial_analysis(financial_rows, display_name or company_name or identifier),
        "tweet_detail_url": "",
        "market_cap_live_text": live_quote.get("market_cap_text") or "实时总市值待行情源补齐",
        "live_quote": live_quote,
    }
    payload.update(_merge_selection_metrics(_find_selection_metrics(entity_type, identifier)))
    if _normalize_text(entity_type) == "project":
        payload["tweet_detail_url"] = build_tweet_detail_url(
            _normalize_text(identifier),
            company_name,
            exchange,
            market,
            display_name,
        )
    return payload
