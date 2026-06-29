from __future__ import annotations

from typing import Any

from chanlun.db import db

from .community_discussions import normalize_discussion_item
from .community_providers import get_default_community_providers


def sync_community_discussions_for_stock(
    *,
    symbol: str,
    company_name: str,
    limit: int = 20,
    db_instance=None,
) -> dict[str, Any]:
    database = db_instance or db
    total_posts = 0
    total_comments = 0
    provider_results: list[dict[str, Any]] = []
    rows_to_upsert: list[dict[str, Any]] = []
    for provider in get_default_community_providers():
        provider_status = provider.provider_status().get("status", "unavailable")
        posts = provider.fetch_posts(symbol=symbol, company_name=company_name, limit=limit)
        comments: list[dict[str, Any]] = []
        for post in posts:
            post_id = str(post.get("platform_item_id") or "")
            if not post_id:
                continue
            comments.extend(provider.fetch_comments(post_id=post_id, limit=limit, post=post))
        normalized_posts = [normalize_discussion_item(item) for item in posts]
        normalized_comments = [normalize_discussion_item(item) for item in comments]
        rows_to_upsert.extend(normalized_posts)
        rows_to_upsert.extend(normalized_comments)
        total_posts += len(normalized_posts)
        total_comments += len(normalized_comments)
        result_status = "ok" if normalized_posts or normalized_comments else provider_status
        if provider_status == "partial" and normalized_posts and not normalized_comments:
            result_status = "partial"
        provider_results.append(
            {
                "platform": provider.platform,
                "posts": len(normalized_posts),
                "comments": len(normalized_comments),
                "status": result_status,
            }
        )
    replace = getattr(database, "community_discussions_replace_or_upsert", None)
    if callable(replace) and rows_to_upsert:
        replace(rows_to_upsert)
    return {
        "symbol": symbol,
        "company_name": company_name,
        "posts": total_posts,
        "comments": total_comments,
        "providers": provider_results,
        "status": "ok" if rows_to_upsert else "no_data",
    }
