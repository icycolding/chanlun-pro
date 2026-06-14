import datetime as dt
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "news"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from backfill_jin10 import FileArchiveFetcher, backfill_jin10_history, split_time_windows
from news import NewsItem
from watch_jin10 import build_news_record, sync_jin10_news_once


class FakeDB:
    def __init__(self) -> None:
        self.records = []

    def news_insert(self, record: dict) -> bool:
        self.records.append(record)
        return True


class FakeVectorDB:
    def __init__(self) -> None:
        self.records = []

    def add_news(self, record: dict) -> bool:
        self.records.append(record)
        return True


def test_build_news_record_normalizes_beijing_time():
    item = NewsItem(
        time=dt.datetime(2026, 4, 4, 6, 46, 18, tzinfo=dt.timezone.utc),
        provider="jin10_web",
        headline="测试快讯",
        article_id="flash20260404064618900800",
    )

    record = build_news_record(item)

    assert record["news_id"] == "flash20260404064618900800"
    assert record["story_id"] == "flash20260404064618900800"
    assert record["published_at"] == dt.datetime(2026, 4, 4, 14, 46, 18)
    assert record["category"] == "jin10_flash"


def test_sync_jin10_news_once_persists_only_unseen_items(monkeypatch, tmp_path):
    now = dt.datetime(2026, 4, 4, 14, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    items = [
        NewsItem(
            time=now,
            provider="jin10_web",
            headline="第二条快讯",
            article_id="flash_2",
        ),
        NewsItem(
            time=now - dt.timedelta(minutes=1),
            provider="jin10_web",
            headline="第一条快讯",
            article_id="flash_1",
        ),
    ]

    monkeypatch.setattr("watch_jin10.fetch_flash_from_homepage", lambda url: items)
    vector_db = FakeVectorDB()
    monkeypatch.setattr("watch_jin10.get_vector_db_safe", lambda: vector_db)

    db = FakeDB()
    state_path = tmp_path / "jin10_seen.json"

    inserted_count, skipped_count, vector_synced_count = sync_jin10_news_once(
        db=db,
        url="https://www.jin10.com/",
        state_path=state_path,
        max_items=50,
    )

    assert inserted_count == 2
    assert skipped_count == 0
    assert vector_synced_count == 2
    assert [record["title"] for record in db.records] == ["第一条快讯", "第二条快讯"]
    assert [record["title"] for record in vector_db.records] == ["第一条快讯", "第二条快讯"]

    inserted_count, skipped_count, vector_synced_count = sync_jin10_news_once(
        db=db,
        url="https://www.jin10.com/",
        state_path=state_path,
        max_items=50,
    )

    assert inserted_count == 0
    assert skipped_count == 2
    assert vector_synced_count == 0
    assert len(db.records) == 2

    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(saved_state.keys()) == {"flash_1", "flash_2"}


def test_split_time_windows_covers_full_range():
    start = dt.datetime(2026, 4, 1, 0, 0, 0)
    end = dt.datetime(2026, 4, 3, 12, 0, 0)

    windows = split_time_windows(start, end, batch_days=1)

    assert windows == [
        (dt.datetime(2026, 4, 1, 0, 0, 0), dt.datetime(2026, 4, 2, 0, 0, 0)),
        (dt.datetime(2026, 4, 2, 0, 0, 0), dt.datetime(2026, 4, 3, 0, 0, 0)),
        (dt.datetime(2026, 4, 3, 0, 0, 0), dt.datetime(2026, 4, 3, 12, 0, 0)),
    ]


def test_backfill_jin10_history_reads_archive_and_saves_checkpoint(tmp_path):
    archive_path = tmp_path / "jin10_history.jsonl"
    archive_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "article_id": "flash_1",
                        "headline": "第一条历史快讯",
                        "published_at": "2026-04-01T09:00:00+08:00",
                        "provider": "jin10_archive",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "article_id": "flash_2",
                        "headline": "第二条历史快讯",
                        "published_at": "2026-04-01T10:00:00+08:00",
                        "provider": "jin10_archive",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "article_id": "flash_3",
                        "headline": "第三条历史快讯",
                        "published_at": "2026-04-02T11:00:00+08:00",
                        "provider": "jin10_archive",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    checkpoint_path = tmp_path / "jin10_backfill_checkpoint.json"
    db = FakeDB()
    vector_db = FakeVectorDB()
    totals = backfill_jin10_history(
        db=db,
        fetcher=FileArchiveFetcher(archive_path),
        start_dt=dt.datetime(2026, 4, 1, 0, 0, 0),
        end_dt=dt.datetime(2026, 4, 3, 0, 0, 0),
        batch_days=1,
        checkpoint_path=checkpoint_path,
        resume=True,
        sleep_seconds=0,
        max_items=1,
        vector_db=vector_db,
    )

    saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert totals["inserted"] == 3
    assert totals["vector_synced"] == 3
    assert totals["completed"] is True
    assert totals["windows_processed"] == 2
    assert totals["pages_processed"] == 3
    assert [record["title"] for record in db.records] == ["第一条历史快讯", "第二条历史快讯", "第三条历史快讯"]
    assert saved_checkpoint["completed"] is True
    assert saved_checkpoint["next_window_start"] == dt.datetime(2026, 4, 3, 0, 0, 0).isoformat()


def test_backfill_jin10_history_resumes_from_checkpoint_cursor(tmp_path):
    archive_path = tmp_path / "jin10_history_resume.jsonl"
    archive_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "article_id": "flash_a",
                        "headline": "第一条回补快讯",
                        "published_at": "2026-04-01T09:00:00+08:00",
                        "provider": "jin10_archive",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "article_id": "flash_b",
                        "headline": "第二条回补快讯",
                        "published_at": "2026-04-01T10:00:00+08:00",
                        "provider": "jin10_archive",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "jin10_backfill_resume_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "next_window_start": dt.datetime(2026, 4, 1, 0, 0, 0).isoformat(),
                "page_cursor": "1",
                "window_end": dt.datetime(2026, 4, 2, 0, 0, 0).isoformat(),
                "completed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = FakeDB()
    totals = backfill_jin10_history(
        db=db,
        fetcher=FileArchiveFetcher(archive_path),
        start_dt=dt.datetime(2026, 4, 1, 0, 0, 0),
        end_dt=dt.datetime(2026, 4, 2, 0, 0, 0),
        batch_days=1,
        checkpoint_path=checkpoint_path,
        resume=True,
        sleep_seconds=0,
        max_items=1,
        vector_db=None,
    )

    assert totals["resume_used"] is True
    assert totals["inserted"] == 1
    assert [record["title"] for record in db.records] == ["第二条回补快讯"]
