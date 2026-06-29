from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .community_discussions import (
    get_community_provider_statuses,
    get_stored_community_discussions,
    summarize_discussion_items,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SERENITY_TWEETS_PATH = _PROJECT_ROOT / "serenity-aleabitoreddit-main" / "data" / "aleabitoreddit_tweets.json"
_SERENITY_SYNC_STATE_PATH = _PROJECT_ROOT / "serenity-aleabitoreddit-main" / "data" / "sync_state.json"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _format_datetime_text(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if not value:
        return ""
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _safe_read_json(file_path: Path) -> Any:
    try:
        with file_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_serenity_archive_metadata() -> dict[str, str]:
    sync_state = _safe_read_json(_SERENITY_SYNC_STATE_PATH)
    tweets_payload = _safe_read_json(_SERENITY_TWEETS_PATH)
    archive_updated_at = _normalize_text((sync_state or {}).get("last_update_time"))
    latest_archive_at = ""
    if isinstance(tweets_payload, list):
        for item in tweets_payload:
            created_at = _normalize_text((item or {}).get("createdAtISO"))
            if created_at and created_at > latest_archive_at:
                latest_archive_at = created_at
    if not archive_updated_at and _SERENITY_TWEETS_PATH.exists():
        archive_updated_at = dt.datetime.fromtimestamp(_SERENITY_TWEETS_PATH.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    status = "unavailable"
    if archive_updated_at:
        status = "available"
        try:
            updated_dt = dt.datetime.fromisoformat(archive_updated_at.replace("Z", "+00:00"))
            if dt.datetime.now(dt.timezone.utc) - updated_dt > dt.timedelta(days=3):
                status = "stale"
        except ValueError:
            status = "available"
    return {
        "source_scope": "serenity_x_archive_only",
        "archive_updated_at": archive_updated_at,
        "latest_archive_at": latest_archive_at,
        "status": status,
        "coverage_note": "当前仅覆盖 Serenity 的 X/Twitter 档案，不代表全网讨论，也不含实时行情。",
    }


def _live_quote_status(live_quote: dict[str, Any] | None) -> tuple[str, str, str]:
    quote = live_quote or {}
    price_text = _normalize_text(quote.get("price_text"))
    market_cap_text = _normalize_text(quote.get("market_cap_text"))
    if price_text and price_text != "--":
        note = "已接入最新价、涨跌幅和实时总市值。"
        return "available", "", note if market_cap_text else "已接入最新价和涨跌幅，实时总市值待补齐。"
    return "unavailable", "", "当前未拿到可用的实时行情。"


def build_analysis_inputs_view(
    *,
    entity_type: str = "",
    identifier: str = "",
    display_name: str = "",
    company_name: str = "",
    exchange: str = "",
    market: str = "",
    numeric_code: str = "",
    live_quote: dict[str, Any] | None = None,
    latest_news: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del entity_type, display_name, exchange, market
    archive_metadata = get_serenity_archive_metadata()
    discussion_symbol = _normalize_text(numeric_code) or _normalize_text(identifier)
    discussion_items = get_stored_community_discussions(
        symbol=discussion_symbol,
        company_name=_normalize_text(company_name),
        limit=20,
    )
    discussion_summary = summarize_discussion_items(discussion_items)
    provider_statuses = {item["platform"]: item for item in get_community_provider_statuses()}
    breakdown_map = {
        item["platform"]: {
            "posts": int(item.get("posts") or 0),
            "comments": int(item.get("comments") or 0),
            "status": _normalize_text(item.get("status")) or "available",
        }
        for item in discussion_summary.get("platform_breakdown", [])
    }

    live_quote_status, live_quote_latest_at, live_quote_note = _live_quote_status(live_quote)
    news_count = len(latest_news or [])
    eastmoney_news_status = "available" if news_count else "unavailable"
    eastmoney_news_note = "已拿到东方财富/本地新闻线索。" if news_count else "当前未拿到可展示的新闻线索。"

    sources = [
        {
            "source_name": "实时行情",
            "source_key": "live_quote",
            "status": live_quote_status,
            "latest_at": live_quote_latest_at,
            "coverage_note": live_quote_note,
            "record_count": 1 if live_quote_status == "available" else 0,
            "source_hint": "exchange.ticks",
        },
        {
            "source_name": "Serenity 推文档案",
            "source_key": "serenity_tweets",
            "status": archive_metadata["status"],
            "latest_at": _format_datetime_text(archive_metadata["archive_updated_at"]),
            "coverage_note": archive_metadata["coverage_note"],
            "record_count": 1 if archive_metadata["archive_updated_at"] else 0,
            "source_hint": archive_metadata["source_scope"],
        },
        {
            "source_name": "东方财富新闻",
            "source_key": "eastmoney_news",
            "status": eastmoney_news_status,
            "latest_at": "",
            "coverage_note": eastmoney_news_note,
            "record_count": news_count,
            "source_hint": "news",
        },
    ]

    source_specs = [
        ("eastmoney", "东方财富股吧帖子", "eastmoney_guba_posts", "posts"),
        ("eastmoney", "东方财富股吧评论", "eastmoney_guba_comments", "comments"),
        ("xueqiu", "雪球帖子", "xueqiu_posts", "posts"),
        ("xueqiu", "雪球评论", "xueqiu_comments", "comments"),
    ]
    for platform, source_name, source_key, field_name in source_specs:
        counts = breakdown_map.get(platform, {})
        provider = provider_statuses.get(platform, {})
        record_count = int(counts.get(field_name) or 0)
        status = _normalize_text(counts.get("status")) or _normalize_text(provider.get("status")) or "unavailable"
        coverage_note = _normalize_text(provider.get("coverage_note"))
        if record_count > 0:
            status = "available"
            coverage_note = f"当前已收录 {record_count} 条{source_name.replace(platform, '') or source_name}。"
        sources.append(
            {
                "source_name": source_name,
                "source_key": source_key,
                "status": status,
                "latest_at": "",
                "coverage_note": coverage_note or "当前暂无可用讨论数据。",
                "record_count": record_count,
                "source_hint": platform,
            }
        )

    return {
        "sources": sources,
        "data_freshness_view": {
            "live_quote": _format_datetime_text(live_quote_latest_at),
            "serenity_archive": archive_metadata["archive_updated_at"],
            "community_discussions": discussion_items[0]["published_at"] if discussion_items else "",
        },
        "community_discussion_summary": discussion_summary,
        "community_discussion_items": discussion_items,
    }
