#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from news import NewsItem

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from chanlun.db import DB
from watch_jin10 import get_vector_db_safe, persist_items

_BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))
Fetcher = Callable[[dt.datetime, dt.datetime, Optional[str], int], Any]


def parse_datetime_value(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(_BEIJING_TZ).replace(tzinfo=None)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=_BEIJING_TZ).replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty datetime value")
    normalized = text.replace("Z", "+00:00").replace("/", "-")
    for candidate in (normalized, normalized.replace(" ", "T")):
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone(_BEIJING_TZ).replace(tzinfo=None)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d", "%Y%m%d%H%M%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"unsupported datetime value: {value}")


def parse_cli_datetime(text: str, end_of_day: bool = False) -> dt.datetime:
    value = parse_datetime_value(text)
    if len(text.strip()) <= 10:
        if end_of_day:
            return value.replace(hour=23, minute=59, second=59, microsecond=999999)
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value


def split_time_windows(
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    batch_days: int,
) -> list[tuple[dt.datetime, dt.datetime]]:
    if batch_days <= 0:
        raise ValueError("batch_days must be positive")
    if end_dt <= start_dt:
        raise ValueError("end_dt must be later than start_dt")
    windows: list[tuple[dt.datetime, dt.datetime]] = []
    cursor = start_dt
    step = dt.timedelta(days=batch_days)
    while cursor < end_dt:
        next_cursor = min(cursor + step, end_dt)
        windows.append((cursor, next_cursor))
        cursor = next_cursor
    return windows


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def coerce_fetch_result(result: Any) -> tuple[list[NewsItem], Optional[str]]:
    if isinstance(result, tuple):
        if len(result) == 2:
            items, cursor = result
            return list(items or []), str(cursor) if cursor not in (None, "") else None
        raise ValueError("fetcher tuple result must be (items, next_cursor)")
    return list(result or []), None


def build_news_item_from_payload(payload: dict[str, Any], default_provider: str = "jin10_history") -> NewsItem:
    article_id = (
        payload.get("article_id")
        or payload.get("news_id")
        or payload.get("story_id")
        or payload.get("id")
        or payload.get("flash_id")
        or ""
    )
    headline = (
        payload.get("headline")
        or payload.get("title")
        or payload.get("body")
        or payload.get("content")
        or ""
    )
    published_at = (
        payload.get("published_at")
        or payload.get("time")
        or payload.get("created_at")
        or payload.get("datetime")
    )
    if not article_id or not headline or published_at is None:
        raise ValueError("payload missing article_id/headline/published_at")
    return NewsItem(
        time=parse_datetime_value(published_at),
        provider=str(payload.get("provider") or payload.get("source") or default_provider),
        headline=str(headline),
        article_id=str(article_id),
    )


class FileArchiveFetcher:
    def __init__(self, archive_path: Path) -> None:
        self.archive_path = archive_path
        self._items: Optional[list[NewsItem]] = None

    def _load(self) -> list[NewsItem]:
        if self._items is not None:
            return self._items
        content = self.archive_path.read_text(encoding="utf-8")
        stripped = content.lstrip()
        raw_items: list[dict[str, Any]]
        if stripped.startswith("["):
            raw_items = list(json.loads(content))
        else:
            raw_items = []
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                raw_items.append(json.loads(line))
        items = [build_news_item_from_payload(item) for item in raw_items]
        items.sort(key=lambda item: item.time)
        self._items = items
        return items

    def __call__(
        self,
        start_dt: dt.datetime,
        end_dt: dt.datetime,
        cursor: Optional[str],
        max_items: int,
    ) -> tuple[list[NewsItem], Optional[str]]:
        items = [item for item in self._load() if start_dt <= parse_datetime_value(item.time) < end_dt]
        offset = int(cursor or "0")
        if max_items <= 0:
            batch = items[offset:]
            next_cursor = None
        else:
            batch = items[offset: offset + max_items]
            next_cursor = str(offset + max_items) if offset + max_items < len(items) else None
        return batch, next_cursor


def load_fetcher(target: str) -> Fetcher:
    module_name, _, func_name = target.partition(":")
    if not module_name or not func_name:
        raise ValueError("fetcher target must be in module:function format")
    module = importlib.import_module(module_name)
    fetcher = getattr(module, func_name, None)
    if fetcher is None or not callable(fetcher):
        raise ValueError(f"fetcher not found: {target}")
    return fetcher


def resolve_resume_state(
    start_dt: dt.datetime,
    checkpoint_path: Optional[Path],
    resume: bool,
) -> tuple[dt.datetime, Optional[str], dict[str, Any]]:
    if not resume or checkpoint_path is None:
        return start_dt, None, {}
    payload = load_checkpoint(checkpoint_path)
    next_window_start = payload.get("next_window_start")
    page_cursor = payload.get("page_cursor")
    if not next_window_start:
        return start_dt, None, payload
    checkpoint_start = parse_datetime_value(next_window_start)
    if checkpoint_start < start_dt:
        return start_dt, None, payload
    return checkpoint_start, str(page_cursor) if page_cursor not in (None, "") else None, payload


def backfill_jin10_history(
    db: DB,
    fetcher: Fetcher,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    batch_days: int = 1,
    checkpoint_path: Optional[Path] = None,
    resume: bool = True,
    sleep_seconds: float = 0.0,
    max_items: int = 200,
    vector_db: Optional[object] = None,
) -> dict[str, Any]:
    current_start, initial_cursor, checkpoint_payload = resolve_resume_state(start_dt, checkpoint_path, resume)
    seen_in_run: dict[str, float] = {}
    totals = {
        "inserted": 0,
        "skipped": 0,
        "vector_synced": 0,
        "windows_processed": 0,
        "pages_processed": 0,
        "resume_used": bool(initial_cursor or checkpoint_payload),
        "completed": False,
        "start_dt": start_dt.isoformat(),
        "end_dt": end_dt.isoformat(),
    }
    if vector_db is None:
        vector_db = get_vector_db_safe()

    batch_delta = dt.timedelta(days=batch_days)
    page_cursor = initial_cursor
    while current_start < end_dt:
        window_end = min(current_start + batch_delta, end_dt)
        while True:
            fetched_items, next_cursor = coerce_fetch_result(fetcher(current_start, window_end, page_cursor, max_items))
            ordered_items = sorted(fetched_items, key=lambda item: parse_datetime_value(item.time))
            inserted_count, skipped_count, vector_synced_count = persist_items(
                ordered_items,
                db,
                seen_in_run,
                vector_db=vector_db,
            )
            totals["inserted"] += inserted_count
            totals["skipped"] += skipped_count
            totals["vector_synced"] += vector_synced_count
            totals["pages_processed"] += 1

            if checkpoint_path is not None:
                save_checkpoint(
                    checkpoint_path,
                    {
                        "next_window_start": current_start.isoformat(),
                        "page_cursor": next_cursor,
                        "window_end": window_end.isoformat(),
                        "requested_end": end_dt.isoformat(),
                        "inserted": totals["inserted"],
                        "skipped": totals["skipped"],
                        "vector_synced": totals["vector_synced"],
                        "completed": False,
                    },
                )

            if not next_cursor:
                totals["windows_processed"] += 1
                current_start = window_end
                page_cursor = None
                if checkpoint_path is not None:
                    save_checkpoint(
                        checkpoint_path,
                        {
                            "next_window_start": current_start.isoformat(),
                            "page_cursor": None,
                            "window_end": None,
                            "requested_end": end_dt.isoformat(),
                            "inserted": totals["inserted"],
                            "skipped": totals["skipped"],
                            "vector_synced": totals["vector_synced"],
                            "completed": current_start >= end_dt,
                        },
                    )
                break

            page_cursor = next_cursor
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        if sleep_seconds > 0 and current_start < end_dt:
            time.sleep(sleep_seconds)

    totals["completed"] = True
    if checkpoint_path is not None:
        save_checkpoint(
            checkpoint_path,
            {
                "next_window_start": end_dt.isoformat(),
                "page_cursor": None,
                "window_end": None,
                "requested_end": end_dt.isoformat(),
                "inserted": totals["inserted"],
                "skipped": totals["skipped"],
                "vector_synced": totals["vector_synced"],
                "completed": True,
            },
        )
    return totals


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="回补金十历史快讯")
    parser.add_argument("--start-date", required=True, help="开始日期，支持 YYYY-MM-DD 或 ISO 时间")
    parser.add_argument("--end-date", required=True, help="结束日期，支持 YYYY-MM-DD 或 ISO 时间")
    parser.add_argument("--batch-days", type=int, default=1, help="按多少天为一批回补")
    parser.add_argument("--max-items", type=int, default=200, help="每页或每批最大处理条数")
    parser.add_argument("--sleep-seconds", type=float, default=0.2, help="分页和批次之间的等待秒数")
    parser.add_argument("--checkpoint", default=".jin10_backfill_checkpoint.json", help="checkpoint 文件")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有 checkpoint，从头开始")
    parser.add_argument("--no-vector-sync", action="store_true", help="回补时不写入向量库")
    parser.add_argument("--fetcher", help="历史抓取函数，格式 module:function")
    parser.add_argument("--archive-file", help="历史导出文件，支持 json 或 jsonl")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.fetcher and not args.archive_file:
        parser.error("必须提供 --fetcher 或 --archive-file")

    start_dt = parse_cli_datetime(args.start_date, end_of_day=False)
    end_dt = parse_cli_datetime(args.end_date, end_of_day=True)
    checkpoint_path = Path(args.checkpoint).expanduser().resolve() if args.checkpoint else None

    if args.archive_file:
        fetcher: Fetcher = FileArchiveFetcher(Path(args.archive_file).expanduser().resolve())
    else:
        fetcher = load_fetcher(args.fetcher)

    db = DB()
    vector_db = None if args.no_vector_sync else get_vector_db_safe()
    totals = backfill_jin10_history(
        db=db,
        fetcher=fetcher,
        start_dt=start_dt,
        end_dt=end_dt,
        batch_days=args.batch_days,
        checkpoint_path=checkpoint_path,
        resume=not args.no_resume,
        sleep_seconds=max(args.sleep_seconds, 0.0),
        max_items=args.max_items,
        vector_db=vector_db,
    )
    print(
        "[backfill] "
        f"inserted={totals['inserted']} skipped={totals['skipped']} "
        f"vector_synced={totals['vector_synced']} windows={totals['windows_processed']} "
        f"pages={totals['pages_processed']} completed={totals['completed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
