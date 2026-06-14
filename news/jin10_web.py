#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import datetime as dt
import re
import warnings
from dataclasses import dataclass
from typing import List, Optional

# requests 在部分发行版环境会抛出依赖版本告警（不影响抓取），这里直接静默
warnings.filterwarnings("ignore", message="urllib3 .* doesn't match a supported version!*")
warnings.filterwarnings("ignore", message="chardet .* doesn't match a supported version!*")

import requests
from bs4 import BeautifulSoup

from news import NewsItem


_ID_RE = re.compile(r"^flash(?P<ymdhms>\d{14})\d*$")


def _parse_flash_id_to_dt(flash_id: str) -> Optional[dt.datetime]:
    """
    例：flash20260404064618900800
    取中间 14 位：YYYYMMDDHHMMSS
    """
    m = _ID_RE.match(flash_id)
    if not m:
        return None
    s = m.group("ymdhms")
    try:
        # 金十页面展示的是北京时间；这里先按北京时间解析并附加东八区tzinfo
        tz = dt.timezone(dt.timedelta(hours=8))
        return dt.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=tz)
    except Exception:
        return None


def fetch_flash_from_homepage(url: str = "https://www.jin10.com/", timeout_sec: int = 20) -> List[NewsItem]:
    """
    从金十首页的“快讯”区域抓取标题级内容。

    注意：
    - 这是“网页解析”方案，页面结构可能变动；建议控制请求频率、做好容错
    - 返回的是标题/短内容，并非全文
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ibkr_fx_research/1.0)",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    # 某些环境下 requests 可能提示依赖版本告警，这里对抓取不构成影响，直接静默
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.get(url, headers=headers, timeout=timeout_sec)
    r.encoding = "utf-8"

    soup = BeautifulSoup(r.text, "html.parser")

    items: List[NewsItem] = []
    containers = soup.select("div.jin-flash-item-container[id^=flash]")
    for c in containers:
        flash_id = c.get("id") or ""
        ts = _parse_flash_id_to_dt(flash_id) or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))

        title_el = c.select_one("b.right-common-title")
        title = (title_el.get_text(" ", strip=True) if title_el else "").strip()
        # content（可选）
        content_el = c.select_one("div.right-content")
        content = content_el.get_text(" ", strip=True) if content_el else ""

        if not title:
            # 有些条目没有 <b> 标题，尽量使用内容区，避免把“分享/收藏”等UI文字抓进来
            title = (content or "").strip()
            if not title:
                title = (c.select_one("div.item-right") or c).get_text(" ", strip=True)[:140].strip()

        # 组合成 headline：优先 title，其次 content
        headline = title
        if content and content not in headline:
            headline = f"{title} - {content}".strip(" -")

        items.append(
            NewsItem(
                time=ts,
                provider="jin10_web",
                headline=headline,
                article_id=flash_id or f"jin10_{int(ts.timestamp())}",
            )
        )

    # 按时间倒序
    items.sort(key=lambda x: x.time, reverse=True)

    # 去重（按 headline）
    dedup = {}
    for it in items:
        k = it.headline.strip().lower()
        if not k:
            continue
        if k not in dedup:
            dedup[k] = it
    out = list(dedup.values())
    out.sort(key=lambda x: x.time, reverse=True)
    return out
