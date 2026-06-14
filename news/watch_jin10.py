#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
盘中“实时”抓取金十首页快讯（网页解析版）：
- 轮询抓取 https://www.jin10.com/
- 发现新 flash_id 就输出到控制台

注意：网页结构可能变动；请控制轮询频率，避免对网站造成压力。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

from jin10_web import fetch_flash_from_homepage
from news import NewsItem

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from chanlun.db import DB

_BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))
_VECTOR_DB_INSTANCE = None
_VECTOR_DB_LOAD_ERROR = None


def load_seen(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_seen(path: Path, seen: Dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_published_at(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(_BEIJING_TZ).replace(tzinfo=None)


def build_news_record(item: NewsItem) -> dict:
    published_at = normalize_published_at(item.time)
    news_id = item.article_id or f"jin10_{int(item.time.timestamp())}"
    return {
        "news_id": news_id,
        "story_id": news_id,
        "title": item.headline,
        "body": item.headline,
        "source": item.provider or "jin10_web",
        "published_at": published_at,
        "language": "zh",
        "category": "jin10_flash",
        "tags": "jin10,flash",
        "sentiment_score": None,
        "importance_score": 0.5,
    }


def get_vector_db_safe():
    global _VECTOR_DB_INSTANCE, _VECTOR_DB_LOAD_ERROR

    if _VECTOR_DB_INSTANCE is not None:
        return _VECTOR_DB_INSTANCE
    if _VECTOR_DB_LOAD_ERROR is not None:
        return None


def build_asset_link_rows_safe(record: dict) -> list[dict]:
    try:
        cl_app_dir = _PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app"
        if str(cl_app_dir) not in sys.path:
            sys.path.insert(0, str(cl_app_dir))
        from asset_news_mapping import build_asset_link_rows

        return build_asset_link_rows(
            news_id=record.get("news_id", ""),
            title=record.get("title", ""),
            body=record.get("body", ""),
            product_info=record.get("product_info"),
            product_code=record.get("product_code"),
        )
    except Exception as e:
        print(f"[asset-link] build skipped: {e}")
        return []

    try:
        cl_app_dir = _PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app"
        if str(cl_app_dir) not in sys.path:
            sys.path.insert(0, str(cl_app_dir))
        from news_vector_db import get_vector_db

        _VECTOR_DB_INSTANCE = get_vector_db()
        return _VECTOR_DB_INSTANCE
    except Exception as e:
        _VECTOR_DB_LOAD_ERROR = str(e)
        print(f"[vector] init skipped: {e}")
        return None


def sync_record_to_vector(record: dict, vector_db: Optional[object]) -> bool:
    if vector_db is None:
        return False

    try:
        added = bool(vector_db.add_news(record))
        if added:
            print(f"[vector] synced {record['news_id']}")
        return added
    except Exception as e:
        print(f"[vector] sync failed for {record['news_id']}: {e}")
        return False


def persist_items(
    items: Iterable[NewsItem],
    db: DB,
    seen: Dict[str, float],
    vector_db: Optional[object] = None,
) -> tuple[int, int, int]:
    inserted_count = 0
    skipped_count = 0
    vector_synced_count = 0

    for item in items:
        news_id = item.article_id or f"jin10_{int(item.time.timestamp())}"
        if news_id in seen:
            skipped_count += 1
            continue

        record = build_news_record(item)
        db.news_insert(record)
        if hasattr(db, "news_asset_links_replace"):
            db.news_asset_links_replace(
                record.get("news_id"),
                build_asset_link_rows_safe(record),
            )
        if sync_record_to_vector(record, vector_db):
            vector_synced_count += 1
        print(f"[db] {record['published_at']} {record['title']}")
        seen[news_id] = item.time.timestamp()
        inserted_count += 1

    return inserted_count, skipped_count, vector_synced_count


def sync_jin10_news_once(
    db: DB,
    url: str,
    state_path: Path,
    max_items: int,
) -> tuple[int, int, int]:
    seen = load_seen(state_path)
    items = fetch_flash_from_homepage(url=url)
    if max_items > 0:
        items = items[:max_items]

    vector_db = get_vector_db_safe()
    inserted_count, skipped_count, vector_synced_count = persist_items(
        reversed(items),
        db,
        seen,
        vector_db=vector_db,
    )
    save_seen(state_path, seen)
    return inserted_count, skipped_count, vector_synced_count


def main() -> int:
    p = argparse.ArgumentParser(description="轮询抓取金十首页快讯并定时写入数据库")
    p.add_argument("--url", default="https://www.jin10.com/", help="金十页面URL")
    p.add_argument("--interval", type=int, default=30, help="轮询间隔（秒）")
    p.add_argument("--state", default=".jin10_seen.json", help="保存已读状态文件")
    p.add_argument("--max-items", type=int, default=50, help="每次最多处理的新闻数量")
    p.add_argument("--once", action="store_true", help="只抓取并入库一次")
    args = p.parse_args()

    state_path = Path(args.state).expanduser().resolve()
    db = DB()

    print(
        f"[watch] url={args.url} interval={args.interval}s state={state_path} "
        f"db={os.getenv('CHANLUN_DB', 'default')}"
    )

    while True:
        try:
            inserted_count, skipped_count, vector_synced_count = sync_jin10_news_once(
                db=db,
                url=args.url,
                state_path=state_path,
                max_items=args.max_items,
            )
            print(
                f"[watch] inserted={inserted_count} skipped={skipped_count} "
                f"vector_synced={vector_synced_count}"
            )
            if args.once:
                break
        except KeyboardInterrupt:
            print("\n[watch] stopped")
            break
        except Exception as e:
            print(f"[watch] error: {e}")

        if args.once:
            break
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
