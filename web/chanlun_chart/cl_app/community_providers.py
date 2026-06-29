from __future__ import annotations
import json
import re

from typing import Any

import requests


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_symbol(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return digits or _normalize_text(value)


class BaseCommunityProvider:
    platform = ""

    def fetch_posts(self, symbol: str, company_name: str, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def fetch_comments(
        self,
        post_id: str,
        limit: int = 20,
        post: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def provider_status(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "status": "unavailable",
            "coverage_note": "当前未接入稳定的公开讨论抓取能力。",
        }


class EastmoneyGubaProvider(BaseCommunityProvider):
    platform = "eastmoney"
    _ARTICLE_LIST_PATTERN = re.compile(r"var\s+article_list\s*=\s*(\{.*?\})\s*;", re.DOTALL)
    _LIST_PAGE_URL = "https://guba.eastmoney.com/list,{symbol},f_{page}.html"
    _REPLY_LIST_PATH = "reply/api/Reply/ArticleNewReplyList"
    _GET_DATA_URL = "https://guba.eastmoney.com/api/getData?code={symbol}&path={path}"
    _REQUEST_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; chanlun-community-sync/1.0)",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def fetch_posts(self, symbol: str, company_name: str, limit: int = 20) -> list[dict[str, Any]]:
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return []
        payload = self._fetch_article_payload(normalized_symbol, page=1)
        raw_posts = payload.get("re") if isinstance(payload.get("re"), list) else []
        posts: list[dict[str, Any]] = []
        for raw_post in raw_posts:
            mapped = self._map_post(
                raw_post=raw_post,
                symbol=normalized_symbol,
                company_name=company_name,
            )
            if mapped:
                posts.append(mapped)
            if len(posts) >= max(int(limit or 0), 1):
                break
        return posts

    def fetch_comments(
        self,
        post_id: str,
        limit: int = 20,
        post: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_post_id = _normalize_text(post_id)
        if not normalized_post_id:
            return []
        symbol = _normalize_symbol((post or {}).get("symbol"))
        payload = self._fetch_reply_payload(
            post_id=normalized_post_id,
            symbol=symbol,
            page=1,
            page_size=max(int(limit or 0), 1),
        )
        raw_comments = payload.get("re") if isinstance(payload.get("re"), list) else []
        comments: list[dict[str, Any]] = []
        for raw_comment in raw_comments:
            mapped = self._map_comment(raw_comment=raw_comment, post_id=normalized_post_id, post=post)
            if mapped:
                comments.append(mapped)
            child_comments = raw_comment.get("child_replys")
            for child_comment in child_comments if isinstance(child_comments, list) else []:
                mapped_child = self._map_comment(raw_comment=child_comment, post_id=normalized_post_id, post=post)
                if mapped_child:
                    comments.append(mapped_child)
            if len(comments) >= max(int(limit or 0), 1):
                break
        return comments

    def _fetch_article_payload(self, symbol: str, page: int = 1) -> dict[str, Any]:
        url = self._LIST_PAGE_URL.format(symbol=symbol, page=max(int(page or 1), 1))
        try:
            response = requests.get(url, headers=self._REQUEST_HEADERS, timeout=15)
            response.raise_for_status()
        except Exception:
            return {}
        match = self._ARTICLE_LIST_PATTERN.search(response.text or "")
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _fetch_reply_payload(
        self,
        *,
        post_id: str,
        symbol: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return {}
        url = self._GET_DATA_URL.format(symbol=normalized_symbol, path=self._REPLY_LIST_PATH)
        data = {
            "param": (
                f"postid={post_id}&sort=1&sorttype=1"
                f"&p={max(int(page or 1), 1)}&ps={max(int(page_size or 20), 1)}&needHide=true"
            ),
            "plat": "Web",
            "path": self._REPLY_LIST_PATH,
            "env": 1,
            "origin": "",
            "version": "2022",
            "product": "Guba",
        }
        try:
            response = requests.post(url, data=data, headers=self._REQUEST_HEADERS, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) and int(payload.get("rc") or 0) == 1 else {}

    def _map_post(
        self,
        *,
        raw_post: dict[str, Any] | None,
        symbol: str,
        company_name: str,
    ) -> dict[str, Any]:
        item = raw_post or {}
        post_id = _normalize_text(item.get("post_id"))
        title = _normalize_text(item.get("post_title"))
        stockbar_code = _normalize_symbol(item.get("stockbar_code"))
        if not post_id or not title or stockbar_code != symbol:
            return {}
        stockbar_name = _normalize_text(item.get("stockbar_name"))
        return {
            "platform": self.platform,
            "content_type": "post",
            "platform_item_id": post_id,
            "parent_item_id": "",
            "title": title,
            "content": title,
            "author_name": _normalize_text(item.get("user_nickname")),
            "published_at": _normalize_text(item.get("post_publish_time") or item.get("post_display_time")),
            "reply_count": int(item.get("post_comment_count") or 0),
            "like_count": int(item.get("post_click_count") or 0),
            "url": f"https://guba.eastmoney.com/news,{stockbar_code},{post_id}.html",
            "symbol": symbol,
            "company_name": _normalize_text(company_name) or stockbar_name.replace("吧", ""),
            "raw_payload": item,
        }

    def _map_comment(
        self,
        *,
        raw_comment: dict[str, Any] | None,
        post_id: str,
        post: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = raw_comment or {}
        reply_id = _normalize_text(item.get("reply_id"))
        reply_text = _normalize_text(item.get("reply_text"))
        if not reply_id or not reply_text:
            return {}
        parent_item_id = _normalize_text(item.get("source_reply_id")) or _normalize_text(item.get("source_post_id")) or post_id
        post_url = _normalize_text((post or {}).get("url"))
        return {
            "platform": self.platform,
            "content_type": "comment",
            "platform_item_id": reply_id,
            "parent_item_id": parent_item_id,
            "title": "",
            "content": reply_text,
            "author_name": _normalize_text((item.get("reply_user") or {}).get("user_nickname")),
            "published_at": _normalize_text(item.get("reply_publish_time")),
            "reply_count": 0,
            "like_count": int(item.get("reply_like_count") or 0),
            "url": f"{post_url}#reply-{reply_id}" if post_url else "",
            "symbol": _normalize_symbol((post or {}).get("symbol")),
            "company_name": _normalize_text((post or {}).get("company_name")),
            "raw_payload": item,
        }

    def provider_status(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "status": "partial",
            "coverage_note": "当前已接入东方财富股吧公开帖子与评论抓取链路，评论接口受东财风控或稳定性影响时会回退为空。",
        }


class XueqiuProvider(BaseCommunityProvider):
    platform = "xueqiu"

    def provider_status(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "status": "unavailable",
            "coverage_note": "当前未接入雪球公开帖子或评论抓取。",
        }


def get_default_community_providers() -> list[BaseCommunityProvider]:
    return [EastmoneyGubaProvider(), XueqiuProvider()]
