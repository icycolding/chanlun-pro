from __future__ import annotations

from typing import Any

from chanlun.db import db

from .community_providers import get_default_community_providers


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def normalize_discussion_item(raw_item: dict[str, Any] | None) -> dict[str, Any]:
    item = raw_item or {}
    return {
        "platform": _normalize_text(item.get("platform")).lower(),
        "content_type": _normalize_text(item.get("content_type")).lower() or "post",
        "platform_item_id": _normalize_text(item.get("platform_item_id")),
        "parent_item_id": _normalize_text(item.get("parent_item_id")),
        "title": _normalize_text(item.get("title")),
        "content": _normalize_text(item.get("content")),
        "author_name": _normalize_text(item.get("author_name")),
        "published_at": _normalize_text(item.get("published_at")),
        "reply_count": _normalize_int(item.get("reply_count")),
        "like_count": _normalize_int(item.get("like_count")),
        "url": _normalize_text(item.get("url")),
        "symbol": _normalize_text(item.get("symbol")),
        "company_name": _normalize_text(item.get("company_name")),
        "raw_payload": item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else {},
    }


def summarize_discussion_items(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized_items = [normalize_discussion_item(item) for item in items or []]
    platform_map: dict[str, dict[str, Any]] = {}
    for item in normalized_items:
        platform = item.get("platform") or "unknown"
        stats = platform_map.setdefault(
            platform,
            {"platform": platform, "posts": 0, "comments": 0, "status": "available"},
        )
        if item.get("content_type") == "comment":
            stats["comments"] += 1
        else:
            stats["posts"] += 1

    platform_breakdown = sorted(platform_map.values(), key=lambda row: row["platform"])
    return {
        "hot_topics": [],
        "bullish_points": [],
        "bearish_points": [],
        "noise_warning": "" if normalized_items else "当前没有可用的中文社区讨论输入。",
        "platform_breakdown": platform_breakdown,
    }


def get_stored_community_discussions(
    *,
    symbol: str = "",
    company_name: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = getattr(db, "community_discussions_query", None)
    if not callable(query):
        return []
    rows = query(symbol=symbol, company_name=company_name, limit=limit)
    return [normalize_discussion_item(item) for item in rows]


def get_community_provider_statuses() -> list[dict[str, str]]:
    statuses: list[dict[str, str]] = []
    for provider in get_default_community_providers():
        status = provider.provider_status()
        statuses.append(
            {
                "platform": _normalize_text(status.get("platform")).lower(),
                "status": _normalize_text(status.get("status")) or "unavailable",
                "coverage_note": _normalize_text(status.get("coverage_note")),
            }
        )
    return statuses
