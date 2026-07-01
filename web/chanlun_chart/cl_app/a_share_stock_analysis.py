from __future__ import annotations

import datetime as dt
import json
import re
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
from .serenity_analysis_inputs import build_analysis_inputs_view
from .serenity_aistocks_serenity_fit import get_serenity_aistock_fit_entry
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
    numeric_code: str = "",
) -> dict[str, str]:
    normalized_type = _normalize_text(entity_type)
    normalized_identifier = _normalize_text(identifier)
    normalized_market = _normalize_text(market).upper()
    normalized_numeric_code = _normalize_text(numeric_code)
    live_quote = _build_empty_live_quote(normalized_market)
    if not normalized_type or not normalized_identifier:
        return live_quote

    try:
        if normalized_type == "serenity_aistock" and normalized_market in {"A", "CN", "CHINA"}:
            ex = get_exchange(Market.A)
            code = normalize_a_share_code(normalized_numeric_code or normalized_identifier)
            snapshots = fetch_tick_snapshots(ex, [code])
            snapshot = snapshots.get(code) or next(iter(snapshots.values()), None)
            market_label = "A"
        elif normalized_type == "serenity_aistock" and normalized_market in {"HK", "HONG KONG"}:
            ex = get_exchange(Market.HK)
            code = normalize_hk_code(normalized_numeric_code or normalized_identifier)
            snapshots = fetch_tick_snapshots(ex, [code])
            snapshot = snapshots.get(code) or next(iter(snapshots.values()), None)
            market_label = "HK"
        elif normalized_type == "serenity_aistock" and normalized_market in {"US", "USA"}:
            ex = get_exchange(Market.US)
            code = (normalized_numeric_code or normalized_identifier).upper()
            snapshots = fetch_tick_snapshots(ex, [code])
            snapshot = snapshots.get(code) or next(iter(snapshots.values()), None)
            market_label = "US"
        elif normalized_type == "match" or normalized_market in {"A", "CN", "CHINA"}:
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
    raw_identifier = _normalize_text(identifier)
    normalized_identifier = raw_identifier.upper()
    if not normalized_type or not raw_identifier:
        return {}

    if normalized_type == "serenity_aistock":
        entry = get_serenity_aistock_fit_entry(raw_identifier)
        if entry:
            return {
                "selection_reason": entry.get("selection_reason") or {},
                "scarcity_view": entry.get("scarcity_view") or {},
                "capacity_view": entry.get("capacity_view") or {},
                "pricing_view": entry.get("pricing_view") or {},
                "market_cap_research": entry.get("market_cap_research") or {},
                "segment_market_view": entry.get("segment_market_view") or {},
                "sector_context_view": entry.get("sector_context_view") or {},
                "industry_chain_view": entry.get("industry_chain_view") or {},
                "financials_view": entry.get("financials_view") or {},
                "moat_view": entry.get("moat_view") or {},
                "valuation_view": entry.get("valuation_view") or {},
                "catalysts_view": entry.get("catalysts_view") or [],
                "risks_view": entry.get("risks_view") or [],
                "thesis_view": entry.get("thesis_view") or {},
                "scenario_view": entry.get("scenario_view") or {},
                "confidence": entry.get("confidence") or {},
                "serenity_certification": entry.get("serenity_certification") or {},
                "evidence_sources": entry.get("evidence_sources") or [],
            }
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
                    "sector_context_view": stock.get("sector_context_view") or {},
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
                            "sector_context_view": match.get("sector_context_view") or {},
                        }
    return {}


def _default_selection_metrics() -> dict[str, dict[str, str]]:
    from .a_share_matches_catalog import (
        _capacity_view,
        _market_cap_research,
        _pricing_view,
        _scarcity_view,
        _sector_context_view,
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
        "sector_context_view": _sector_context_view(),
        "industry_chain_view": {
            "upstream": "待补充",
            "midstream": "待补充",
            "downstream": "待补充",
            "company_link_position": "公司环节待补充",
            "choke_point_note": "真正 choke point 待补充",
        },
        # v2 新增视图组（默认空，供 _merge_selection_metrics 纳入并作 v1 兜底）
        "financials_view": {
            "revenue_segments": [],
            "revenue_trend_3y": "",
            "margin_text": "",
            "operating_leverage_text": "",
        },
        "moat_view": {"moat_types": [], "durability": "", "detail": ""},
        "valuation_view": {
            "pe_text": "",
            "pb_text": "",
            "peg_text": "",
            "vs_history_text": "",
            "vs_peers_text": "",
            "verdict": "",
        },
        "catalysts_view": [],
        "risks_view": [],
        "thesis_view": {"variant_perception": "", "bull_points": [], "bear_points": []},
        "scenario_view": {"bull": {}, "base": {}, "bear": {}},
        "confidence": {"overall": "", "by_dimension": {}, "evidence_tier_summary": ""},
        "serenity_certification": {
            "verdict": "",
            "score": "",
            "checklist": [],
            "bottleneck_map": "",
            "disqualifiers": [],
            "anti_patterns_checked": "",
            "summary": "",
        },
        "evidence_sources": [],
    }


def _merge_selection_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    source_metrics = metrics or {}
    for key, default_value in _default_selection_metrics().items():
        current_value = source_metrics.get(key)
        if isinstance(current_value, dict):
            merged[key] = {**default_value, **current_value}
        elif isinstance(current_value, list) and isinstance(default_value, list):
            merged[key] = list(current_value)
        else:
            merged[key] = dict(default_value) if isinstance(default_value, dict) else list(default_value)
    return merged


def _derive_sector_name(segment_market_text: str = "") -> str:
    text = _normalize_text(segment_market_text)
    if not text or "待研究补齐" in text or "待补充" in text:
        return ""
    text = re.sub(r"^若以[^，。,；]*[，,]\s*", "", text)
    text = text.replace("对应", "", 1).strip()
    for marker in ["可按", "市场当前可按", "市场可按", "已被", "本身不是最大收入池"]:
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    return text.strip("。；，, ")


def _build_sector_context_from_metrics(
    metrics: dict[str, Any] | None,
    *,
    display_name: str = "",
    company_name: str = "",
) -> dict[str, str]:
    from .a_share_matches_catalog import _sector_context_view

    source_metrics = metrics or {}
    base = source_metrics.get("sector_context_view") or {}
    segment = source_metrics.get("segment_market_view") or {}
    selection_reason = source_metrics.get("selection_reason") or {}

    sector_name = _normalize_text(base.get("sector_name"))
    if not sector_name or sector_name == "板块待补充":
        sector_name = _derive_sector_name(segment.get("market_size_text", ""))

    sector_role = _normalize_text(base.get("sector_role"))
    if not sector_role or sector_role == "板块定位待 AI 研究补齐":
        sector_role = f"{_normalize_text(display_name) or _normalize_text(company_name) or '该公司'}所处细分环节样本"

    selection_fit_basis = _normalize_text(selection_reason.get("fit_basis"))
    if selection_fit_basis.startswith("仍需补充"):
        selection_fit_basis = ""

    growth_outlook = _normalize_text(base.get("growth_outlook"))
    if not growth_outlook or growth_outlook == "增长前景待 AI 研究补齐":
        growth_outlook = selection_fit_basis

    selection_summary = _normalize_text(selection_reason.get("summary"))
    if selection_summary.startswith("仍需补充"):
        selection_summary = ""

    company_position_text = _normalize_text(base.get("company_position_text"))
    if not company_position_text or company_position_text == "行业地位待 AI 研究补齐":
        company_position_text = selection_summary

    company_share_text = _normalize_text(base.get("company_share_text")) or _normalize_text(segment.get("company_share_text"))
    market_size_text = _normalize_text(base.get("market_size_text")) or _normalize_text(segment.get("market_size_text"))
    share_level = _normalize_text(base.get("share_level")) or _normalize_text(segment.get("share_level"))
    evidence_note = _normalize_text(base.get("evidence_note")) or "优先结合现有主题研究、市场空间视图与 AI 摘要继续补齐。"

    return _sector_context_view(
        sector_name=sector_name,
        sector_role=sector_role,
        market_size_text=market_size_text,
        growth_outlook=growth_outlook,
        company_position_text=company_position_text,
        company_share_text=company_share_text,
        share_level=share_level,
        evidence_note=evidence_note,
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return {}
    try:
        parsed = json.loads(normalized_text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", normalized_text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_ai_sector_context(
    *,
    base_context: dict[str, str],
    latest_news: Sequence[dict[str, str]],
    financial_summary: str,
    display_name: str = "",
    company_name: str = "",
) -> dict[str, str]:
    missing_core_fields = [
        _normalize_text(base_context.get("sector_name")) in {"", "板块待补充"},
        _normalize_text(base_context.get("growth_outlook")) in {"", "增长前景待 AI 研究补齐"},
        _normalize_text(base_context.get("company_position_text")) in {"", "行业地位待 AI 研究补齐"},
    ]
    if sum(1 for is_missing in missing_core_fields if is_missing) < 2:
        return {}

    news_titles = [str(item.get("title") or "").strip() for item in latest_news or [] if str(item.get("title") or "").strip()]
    if not news_titles and ("暂无财务数据" in _normalize_text(financial_summary) or not _normalize_text(financial_summary)):
        return {}

    prompt = (
        "请基于以下信息，输出一段严格 JSON，字段必须包含："
        "sector_name, sector_role, market_size_text, growth_outlook, company_position_text, "
        "company_share_text, share_level, evidence_note。\n"
        "要求：\n"
        "1. 使用中文；\n"
        "2. 尽量给细分板块，而不是泛行业；\n"
        "3. 市场空间使用量级或区间表达，不要伪精确；\n"
        "4. 行业地位和份额表达要带不确定性，不要编造确定数字；\n"
        "5. 只输出 JSON，不要解释。\n"
        f"股票显示名：{display_name or company_name or '未知标的'}\n"
        f"公司名：{company_name or display_name or '未知公司'}\n"
        f"现有基础信息：{json.dumps(base_context, ensure_ascii=False)}\n"
        f"财务摘要：{financial_summary or '暂无'}\n"
        f"新闻标题：{json.dumps(news_titles[:5], ensure_ascii=False)}"
    )
    try:
        result = AIAnalyse("a").req_openrouter_ai_model(prompt)
    except Exception:
        return {}

    ai_text = ""
    if isinstance(result, dict) and result.get("ok"):
        ai_text = _normalize_text(result.get("msg"))
    elif isinstance(result, dict):
        ai_text = _normalize_text(result.get("msg"))
    else:
        ai_text = _normalize_text(result)

    parsed = _extract_json_object(ai_text)
    if not parsed:
        return {}

    allowed_keys = {
        "sector_name",
        "sector_role",
        "market_size_text",
        "growth_outlook",
        "company_position_text",
        "company_share_text",
        "share_level",
        "evidence_note",
    }
    return {
        key: _normalize_text(parsed.get(key))
        for key in allowed_keys
        if _normalize_text(parsed.get(key))
    }


def _merge_sector_context(
    base_context: dict[str, str] | None,
    ai_context: dict[str, str] | None,
) -> dict[str, str]:
    from .a_share_matches_catalog import _sector_context_view

    defaults = _sector_context_view()
    merged = dict(defaults)
    for source in [base_context or {}, ai_context or {}]:
        for key, value in source.items():
            normalized_value = _normalize_text(value)
            if normalized_value:
                merged[key] = normalized_value
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

    base_candidates = (
        [normalized_numeric_code, normalized_identifier]
        if entity_type == "serenity_aistock"
        else [normalized_identifier, normalized_numeric_code]
    )
    for raw in base_candidates:
        if raw and raw not in candidates:
            candidates.append(raw)

    if entity_type == "match" or normalized_market in {"A", "CN", "CHINA"} or normalized_exchange in {"SSE", "SZSE", "BSE", "STAR", "CHINEXT"}:
        for raw in base_candidates:
            normalized = normalize_a_share_code(raw)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

    if normalized_market in {"HK", "HONG KONG"} or normalized_exchange in {"HKG", "HKEX", "SEHK"}:
        for raw in base_candidates:
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
    selection_metrics = _merge_selection_metrics(_find_selection_metrics(entity_type, identifier))
    sector_context = _build_sector_context_from_metrics(
        selection_metrics,
        display_name=display_name,
        company_name=company_name,
    )

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
        "sector_context_view": sector_context,
        "sector_name": sector_context.get("sector_name", ""),
        "growth_outlook_short": sector_context.get("growth_outlook", ""),
        "company_position_short": sector_context.get("company_position_text", ""),
        "market_size_short": sector_context.get("market_size_text", ""),
        "company_share_short": sector_context.get("company_share_text", ""),
        "analysis_source_label": "Workspace" if financial_source == "workspace" else "",
        "detail_url": build_stock_analysis_detail_url(
            entity_type=entity_type,
            identifier=identifier,
            display_name=display_name,
            company_name=company_name,
            exchange=exchange,
            market=market,
            numeric_code=numeric_code,
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
        numeric_code=_normalize_text(numeric_code),
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
    analysis_inputs = build_analysis_inputs_view(
        entity_type=entity_type,
        identifier=identifier,
        display_name=display_name,
        company_name=company_name,
        exchange=exchange,
        market=market,
        numeric_code=_normalize_text(numeric_code),
        live_quote=live_quote,
        latest_news=latest_news,
    )
    payload["analysis_inputs"] = {"sources": list(analysis_inputs.get("sources") or [])}
    payload["data_freshness_view"] = dict(analysis_inputs.get("data_freshness_view") or {})
    payload["community_discussion_summary"] = dict(analysis_inputs.get("community_discussion_summary") or {})
    payload["community_discussion_items"] = list(analysis_inputs.get("community_discussion_items") or [])
    selection_metrics = _merge_selection_metrics(_find_selection_metrics(entity_type, identifier))
    base_sector_context = _build_sector_context_from_metrics(
        selection_metrics,
        display_name=display_name,
        company_name=company_name,
    )
    ai_sector_context = _build_ai_sector_context(
        base_context=base_sector_context,
        latest_news=latest_news,
        financial_summary=summary.get("financial_summary", ""),
        display_name=display_name,
        company_name=company_name,
    )
    selection_metrics["sector_context_view"] = _merge_sector_context(base_sector_context, ai_sector_context)
    payload.update(selection_metrics)
    if _normalize_text(entity_type) == "project":
        payload["tweet_detail_url"] = build_tweet_detail_url(
            _normalize_text(identifier),
            company_name,
            exchange,
            market,
            display_name,
        )
    return payload
