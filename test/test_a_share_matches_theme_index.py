from pathlib import Path
import sys
import types


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.a_share_matches_catalog import (
    build_theme_index_live_snapshot,
    build_theme_index_reference_closes,
    build_theme_index_history_series,
    build_theme_index_history,
    merge_theme_index_live_snapshot,
    get_theme_a_share_index,
)
import cl_app.a_share_matches_catalog as catalog


def test_get_theme_a_share_index_returns_theme_metadata():
    index_meta = get_theme_a_share_index("光模块-CPO-光子器件")

    assert index_meta["slug"] == "光模块-CPO-光子器件"
    assert index_meta["name"].endswith("A股指数")
    assert index_meta["chart_title"].endswith("历史价格图")
    assert index_meta["default_lookback_days"] == "max"
    assert index_meta["constituents"]


def test_build_theme_index_history_series_aggregates_weighted_constituents():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 2.0, "source_type": "main_match"},
            {"code": "000002", "name": "乙", "weight": 1.0, "source_type": "theme_related"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2026-06-10", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.0},
            {"date": "2026-06-11", "open": 10.0, "high": 10.7, "low": 10.0, "close": 10.5},
            {"date": "2026-06-12", "open": 10.5, "high": 11.2, "low": 10.4, "close": 11.0},
        ],
        "000002": [
            {"date": "2026-06-10", "open": 20.0, "high": 20.5, "low": 19.8, "close": 20.0},
            {"date": "2026-06-11", "open": 20.0, "high": 20.2, "low": 19.5, "close": 19.6},
            {"date": "2026-06-12", "open": 19.6, "high": 20.1, "low": 19.4, "close": 20.0},
        ],
    }

    result = build_theme_index_history_series(index_meta, histories)

    assert result["theme_slug"] == "demo-theme"
    assert result["base_value"] == 1000.0
    assert result["coverage"]["used_constituents"] == 2
    assert len(result["series"]) == 3
    assert result["series"][0]["close"] == 1000.0
    assert result["series"][-1]["close"] > result["series"][0]["close"]


def test_build_theme_index_history_series_allows_partial_coverage():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 2.0, "source_type": "main_match"},
            {"code": "000002", "name": "乙", "weight": 1.0, "source_type": "theme_related"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2026-06-10", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.0},
            {"date": "2026-06-11", "open": 10.0, "high": 10.7, "low": 10.0, "close": 10.5},
        ],
    }

    result = build_theme_index_history_series(index_meta, histories)

    assert result["coverage"]["used_constituents"] == 1
    assert result["coverage"]["total_constituents"] == 2
    assert len(result["series"]) == 2


def test_build_theme_index_history_series_marks_max_range_metadata():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 1.0, "source_type": "main_match"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2026-06-10", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.0},
            {"date": "2026-06-11", "open": 10.0, "high": 10.6, "low": 9.8, "close": 10.2},
            {"date": "2026-06-12", "open": 10.2, "high": 10.7, "low": 10.1, "close": 10.5},
        ],
    }

    result = build_theme_index_history_series(index_meta, histories, range_mode="max")

    assert result["is_max_range"] is True
    assert result["lookback_label"] == "最长历史"
    assert len(result["series"]) == 3


def test_build_theme_index_live_snapshot_matches_weighted_realtime_index():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 2.0, "source_type": "main_match"},
            {"code": "000002", "name": "乙", "weight": 1.0, "source_type": "theme_related"},
        ],
    }
    tick_map = {
        "000001": {"price": 10.8},
        "000002": {"price": 19.0},
    }
    reference_closes = {"000001": 10.0, "000002": 20.0}

    result = build_theme_index_live_snapshot(index_meta, tick_map, reference_closes, as_of_date="2026-06-13")

    assert result["date"] == "2026-06-13"
    assert result["used_constituents"] == 2
    expected_change = (((10.8 / 10.0) - 1.0) * 2.0 + ((19.0 / 20.0) - 1.0) * 1.0) / 3.0 * 100.0
    assert round(result["change_pct"], 4) == round(expected_change, 4)
    assert round(result["index_value"], 4) == round(1000.0 * (1 + result["change_pct"] / 100), 4)


def test_merge_theme_index_live_snapshot_aligns_latest_chart_value_with_realtime_index():
    history_result = {
        "theme_slug": "demo-theme",
        "title": "示例主题历史价格图",
        "base_value": 1000.0,
        "series": [
            {"date": "2026-06-11", "open": 1000.0, "high": 1010.0, "low": 995.0, "close": 1005.0},
            {"date": "2026-06-12", "open": 1005.0, "high": 1018.0, "low": 1001.0, "close": 1012.0},
        ],
    }
    live_snapshot = {
        "date": "2026-06-13",
        "index_value": 1026.5,
        "change_pct": 2.65,
    }

    merged = merge_theme_index_live_snapshot(history_result, live_snapshot)

    assert merged["series"][-1]["date"] == "2026-06-13"
    assert merged["series"][-1]["close"] == 1026.5
    assert merged["live_index"]["index_value"] == 1026.5


def test_build_theme_index_reference_closes_uses_fixed_reference_date():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 2.0, "source_type": "main_match"},
            {"code": "000002", "name": "乙", "weight": 1.0, "source_type": "theme_related"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2026-06-01", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0},
            {"date": "2026-06-10", "open": 10.0, "high": 10.7, "low": 10.0, "close": 10.5},
        ],
        "000002": [
            {"date": "2026-06-01", "open": 19.8, "high": 20.4, "low": 19.7, "close": 20.0},
            {"date": "2026-06-10", "open": 20.0, "high": 20.2, "low": 19.5, "close": 19.6},
        ],
    }

    reference_date, reference_closes = build_theme_index_reference_closes(index_meta, histories)

    assert reference_date == "2026-06-01"
    assert reference_closes == {"000001": 10.0, "000002": 20.0}


def test_build_theme_index_history_series_keeps_same_reference_when_zoom_changes():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 2.0, "source_type": "main_match"},
            {"code": "000002", "name": "乙", "weight": 1.0, "source_type": "theme_related"},
        ],
    }
    full_histories = {
        "000001": [
            {"date": "2026-06-01", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0},
            {"date": "2026-06-10", "open": 10.0, "high": 10.7, "low": 10.0, "close": 10.5},
            {"date": "2026-06-12", "open": 10.5, "high": 11.2, "low": 10.4, "close": 11.0},
        ],
        "000002": [
            {"date": "2026-06-01", "open": 19.8, "high": 20.4, "low": 19.7, "close": 20.0},
            {"date": "2026-06-10", "open": 20.0, "high": 20.2, "low": 19.5, "close": 19.6},
            {"date": "2026-06-12", "open": 19.6, "high": 20.1, "low": 19.4, "close": 20.0},
        ],
    }
    reference_date, reference_closes = build_theme_index_reference_closes(index_meta, full_histories)
    short_histories = {
        "000001": full_histories["000001"][1:],
        "000002": full_histories["000002"][1:],
    }

    full_result = build_theme_index_history_series(
        index_meta,
        full_histories,
        reference_date=reference_date,
        reference_closes=reference_closes,
    )
    short_result = build_theme_index_history_series(
        index_meta,
        short_histories,
        lookback_days=20,
        reference_date=reference_date,
        reference_closes=reference_closes,
    )

    assert full_result["reference_date"] == "2026-06-01"
    assert short_result["reference_date"] == "2026-06-01"
    assert full_result["series"][1]["close"] == short_result["series"][0]["close"]


def test_build_theme_index_history_series_uses_custom_reference_date_when_provided():
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 1.0, "source_type": "main_match"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2026-06-01", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0},
            {"date": "2026-06-10", "open": 10.0, "high": 10.6, "low": 9.9, "close": 10.5},
            {"date": "2026-06-12", "open": 10.5, "high": 11.1, "low": 10.4, "close": 11.0},
        ],
    }

    result = build_theme_index_history_series(
        index_meta,
        histories,
        reference_date="2026-06-10",
    )

    assert result["reference_date"] == "2026-06-10"
    assert result["series"][1]["close"] == 1000.0
    assert result["series"][2]["close"] > 1000.0


def test_build_theme_index_history_uses_custom_reference_date_when_requested(monkeypatch):
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 1.0, "source_type": "main_match"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2026-06-01", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0},
            {"date": "2026-06-10", "open": 10.0, "high": 10.6, "low": 9.9, "close": 10.5},
            {"date": "2026-06-12", "open": 10.5, "high": 11.1, "low": 10.4, "close": 11.0},
        ],
    }

    monkeypatch.setattr(catalog, "get_theme_a_share_index", lambda slug: index_meta if slug == "demo-theme" else None)
    monkeypatch.setattr(catalog, "_load_theme_index_constituent_histories", lambda *args, **kwargs: histories)
    monkeypatch.setattr(
        catalog,
        "_load_theme_index_live_snapshot",
        lambda index_meta, reference_closes=None: build_theme_index_live_snapshot(
            index_meta,
            {"000001": {"price": 11.2}},
            reference_closes or {"000001": 10.0},
            as_of_date="2026-06-13",
        ),
    )

    result = build_theme_index_history(
        "demo-theme",
        lookback_days=20,
        range_mode="",
        reference_date="2026-06-10",
    )

    assert result["reference_date"] == "2026-06-10"
    assert result["series"][1]["close"] == 1000.0
    assert result["live_index"]["index_value"] == 1066.667


def test_build_theme_index_performance_metrics_reads_live_day_and_current_year():
    series = [
        {"date": "2025-12-31", "open": 980.0, "high": 990.0, "low": 970.0, "close": 980.0},
        {"date": "2026-01-02", "open": 1000.0, "high": 1010.0, "low": 995.0, "close": 1000.0},
        {"date": "2026-06-12", "open": 1100.0, "high": 1110.0, "low": 1090.0, "close": 1100.0},
    ]
    live_index = {
        "date": "2026-06-13",
        "index_value": 1120.0,
        "daily_change_pct": 1.82,
        "daily_amplitude_pct": 7.27,
    }

    metrics = catalog._build_theme_index_performance_metrics(series, live_index)

    assert metrics["daily_change_pct"] == 1.82
    assert metrics["daily_amplitude_pct"] == 7.27
    assert metrics["ytd_change_pct"] == 12.0
    assert metrics["ytd_amplitude_pct"] == 12.5
    assert metrics["year_start_date"] == "2026-01-02"


def test_build_theme_index_history_exposes_daily_and_yearly_metrics(monkeypatch):
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 1.0, "source_type": "main_match"},
        ],
    }
    histories = {
        "000001": [
            {"date": "2025-12-31", "open": 7.9, "high": 8.1, "low": 7.8, "close": 8.0},
            {"date": "2026-01-02", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
            {"date": "2026-06-12", "open": 10.8, "high": 11.1, "low": 10.7, "close": 11.0},
        ],
    }

    monkeypatch.setattr(catalog, "get_theme_a_share_index", lambda slug: index_meta if slug == "demo-theme" else None)
    monkeypatch.setattr(catalog, "_load_theme_index_constituent_histories", lambda *args, **kwargs: histories)
    monkeypatch.setattr(
        catalog,
        "_load_theme_index_live_snapshot",
        lambda index_meta, reference_closes=None: {
            "date": "2026-06-13",
            "index_value": 1400.0,
            "change_pct": 40.0,
            "daily_change_pct": 1.82,
            "daily_amplitude_pct": 7.27,
        },
    )

    result = build_theme_index_history("demo-theme", lookback_days=20, range_mode="")

    assert result["metrics"]["daily_change_pct"] == 1.82
    assert result["metrics"]["daily_amplitude_pct"] == 7.27
    assert result["metrics"]["ytd_change_pct"] == 12.0
    assert result["metrics"]["ytd_amplitude_pct"] == 13.0


def test_build_theme_index_history_uses_db_cache_without_calling_exchange(monkeypatch):
    today_text = catalog.dt.date.today().isoformat()
    catalog._THEME_INDEX_REFERENCE_STATE_CACHE.pop("demo-theme", None)
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 1.0, "source_type": "main_match"},
        ],
    }
    db_rows = [
        types.SimpleNamespace(dt="2026-06-01", o=9.8, h=10.2, l=9.7, c=10.0, v=1000),
        types.SimpleNamespace(dt="2026-06-10", o=10.0, h=10.6, l=9.9, c=10.3, v=1100),
        types.SimpleNamespace(dt=today_text, o=10.3, h=10.7, l=10.1, c=10.5, v=1200),
    ]
    called = {"exchange": 0}

    monkeypatch.setattr(catalog, "get_theme_a_share_index", lambda slug: index_meta if slug == "demo-theme" else None)
    monkeypatch.setattr(
        catalog,
        "db",
        types.SimpleNamespace(
            klines_query=lambda **kwargs: db_rows,
            klines_last_datetime=lambda *args, **kwargs: today_text,
            klines_insert=lambda *args, **kwargs: True,
            cache_get=lambda key: {"full_history": True},
            cache_set=lambda key, val, expire=0: True,
        ),
    )

    class FakeExchange:
        def klines(self, code, frequency, args=None):
            called["exchange"] += 1
            raise AssertionError("database cache hit should not call exchange")

    monkeypatch.setattr(catalog, "get_exchange", lambda market: FakeExchange())
    monkeypatch.setattr(
        catalog,
        "fetch_tick_snapshots",
        lambda ex, codes: {"SH.000001": {"price": 10.6}},
    )

    result = build_theme_index_history("demo-theme", lookback_days=3, range_mode="")

    assert called["exchange"] == 0
    assert result["reference_date"] == "2026-06-01"
    assert result["series"]


def test_build_theme_index_history_backfills_only_incremental_gap_and_persists(monkeypatch):
    catalog._THEME_INDEX_REFERENCE_STATE_CACHE.pop("demo-theme", None)
    index_meta = {
        "slug": "demo-theme",
        "name": "示例主题 A股指数",
        "chart_title": "示例主题历史价格图",
        "base_value": 1000.0,
        "constituents": [
            {"code": "000001", "name": "甲", "weight": 1.0, "source_type": "main_match"},
        ],
    }
    persisted = {}
    db_rows = [
        types.SimpleNamespace(dt="2026-06-01", o=9.8, h=10.2, l=9.7, c=10.0, v=1000),
        types.SimpleNamespace(dt="2026-06-10", o=10.0, h=10.6, l=9.9, c=10.3, v=1100),
    ]

    monkeypatch.setattr(catalog, "get_theme_a_share_index", lambda slug: index_meta if slug == "demo-theme" else None)
    monkeypatch.setattr(
        catalog,
        "db",
        types.SimpleNamespace(
            klines_query=lambda **kwargs: db_rows,
            klines_last_datetime=lambda *args, **kwargs: "2026-06-10",
            klines_insert=lambda market, code, frequency, klines: persisted.setdefault("rows", klines) or True,
        ),
    )

    class FakeFrame:
        empty = False

        def to_dict(self, orient):
            return [
                {"date": "2026-06-11", "open": 10.3, "high": 10.7, "low": 10.2, "close": 10.4, "volume": 1200},
                {"date": "2026-06-12", "open": 10.4, "high": 10.8, "low": 10.3, "close": 10.6, "volume": 1300},
            ]

    class FakeExchange:
        def klines(self, code, frequency, args=None):
            return FakeFrame()

    monkeypatch.setattr(catalog, "get_exchange", lambda market: FakeExchange())
    monkeypatch.setattr(
        catalog,
        "fetch_tick_snapshots",
        lambda ex, codes: {"SH.000001": {"price": 10.6}},
    )

    result = build_theme_index_history("demo-theme", lookback_days=20, range_mode="")

    assert "rows" in persisted
    assert result["reference_date"] == "2026-06-01"
    assert result["series"][-1]["close"] >= result["series"][0]["close"]
