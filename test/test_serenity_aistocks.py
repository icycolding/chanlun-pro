from pathlib import Path
import sys

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

import cl_app.serenity_aistocks as serenity_aistocks
from cl_app.serenity_aistocks import (
    _infer_row_quote_target,
    fetch_serenity_aistocks_recent_three_buy_times,
    get_serenity_aistocks_sheet,
    load_serenity_aistocks_workbook,
    register_serenity_aistocks_routes,
    sync_serenity_aistocks_latest_prices,
)


class _TestUser(UserMixin):
    def __init__(self, user_id: str = "test-user") -> None:
        self.id = user_id


@pytest.fixture
def app_client():
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.secret_key = "test-secret"
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.user_loader(lambda user_id: _TestUser(user_id))
    register_serenity_aistocks_routes(
        app,
        status_provider=lambda: {
            "running": True,
            "interval_seconds": 60,
            "last_run_at": "2026-06-17T10:00:00",
            "last_success_count": 18,
            "last_unsupported_count": 2,
            "last_error_count": 0,
            "last_total_candidates": 20,
            "last_error": "",
        },
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "test-user"
        session["_fresh"] = True
    yield app, client


def _render_serenity_aistocks_index(context):
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("serenity_aistocks_index.html")
    return template.render(**context)


def _render_serenity_aistocks_sheet(context):
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("serenity_aistocks_sheet.html")
    return template.render(**context)


def test_load_serenity_aistocks_workbook_returns_sheet_summaries():
    workbook = load_serenity_aistocks_workbook()

    assert workbook["workbook_name"] == "aistocks.xlsx"
    assert workbook["sheet_count"] >= 10
    assert workbook["total_row_count"] > 0
    assert workbook["sheets"]
    assert any(sheet["sheet_name"] == "科技线短缺材料总表" for sheet in workbook["sheets"])
    assert any(sheet["sheet_name"] == "芯片半导体" for sheet in workbook["sheets"])


def test_sheet_detail_preserves_original_columns_and_appends_price(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")

    assert sheet["sheet_name"] == "科技线短缺材料总表"
    assert sheet["columns"][-1] == "价格"
    assert sheet["columns"][:-1] == ["所属分类", "代码", "名称", "核心概念 / 备注"]
    assert sheet["row_count"] > 0
    first_row = sheet["rows"][0]
    assert first_row["cells"]["所属分类"] == "覆铜板（CCL）及HVLP铜箔"
    assert first_row["cells"]["代码"] == "sh600183"
    assert first_row["cells"]["名称"] == "生益科技"
    assert first_row["price_text"] == "--"
    assert "chart_url" in first_row
    assert "chart_unavailable_reason" in first_row
    assert first_row["recent_three_buy_time_text"] == "--"


def test_sheet_detail_hydrates_price_from_database(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            assert items
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "price_text": "23.450",
                    "rate_text": "+1.23%",
                    "status": "ok",
                    "updated_at_text": "2026-06-17 10:00:00",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    first_row = sheet["rows"][0]

    assert first_row["quote_target"]["market"] == "a"
    assert first_row["quote_target"]["normalized_code"] == "SH.600183"
    assert first_row["price_text"] == "23.450"
    assert first_row["rate_text"] == "+1.23%"
    assert first_row["price_status"] == "ok"
    assert first_row["updated_at_text"] == "2026-06-17 10:00:00"


def test_sheet_detail_hydrates_recent_three_buy_from_database(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            assert items
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "recent_three_buy_time_text": "2026-06-08",
                    "label": "最近 3买",
                    "status": "ok",
                    "updated_at_text": "2026-06-26 10:00:00",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    first_row = sheet["rows"][0]

    assert first_row["recent_three_buy_time_text"] == "2026-06-08"
    assert first_row["recent_three_buy_label"] == "最近 3买"
    assert first_row["recent_three_buy_status"] == "ok"
    assert first_row["recent_three_buy_updated_at_text"] == "2026-06-26 10:00:00"


def test_infer_row_quote_target_handles_us_a_hk_and_unknown():
    a_target = _infer_row_quote_target({"代码": "sh600183", "名称": "生益科技"}, ["代码", "名称"])
    us_target = _infer_row_quote_target({"代码": "NVDA", "名称": "英伟达"}, ["代码", "名称"])
    hk_target = _infer_row_quote_target({"代码": "09868", "名称": "小鹏汽车"}, ["代码", "名称"])
    unknown_target = _infer_row_quote_target({"名称": "无代码样本"}, ["名称"])

    assert a_target["market"] == "a"
    assert a_target["code"] == "sh600183"
    assert a_target["normalized_code"] == "SH.600183"
    assert us_target["market"] == "us"
    assert us_target["code"] == "NVDA"
    assert us_target["normalized_code"] == "NVDA"
    assert hk_target["market"] == "hk"
    assert hk_target["code"] == "09868"
    assert hk_target["normalized_code"] == "KH.09868"
    assert unknown_target["status"] == "unsupported"


def test_serenity_aistocks_index_template_renders_sheet_cards(monkeypatch):
    workbook = load_serenity_aistocks_workbook()
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    selected_sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": selected_sheet,
            "selected_sheet_slug": selected_sheet["sheet_slug"],
            "selected_sheet_summary": workbook["sheets"][0],
            "sync_status": {
                "running": True,
                "interval_seconds": 60,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [sheet["sheet_slug"] for sheet in workbook["sheets"]],
        }
    )

    assert "<h1>Serenity AI Stocks</h1>" not in html
    assert "Sheet 总览" in html
    assert "科技线短缺材料总表" in html
    assert "芯片半导体" in html
    assert "后台同步" in html
    assert "价格" in html
    assert "active" in html
    assert "/serenity/aistocks/" in html
    assert ".sidebar {\n            position: static;" in html
    assert "overflow-y: auto" not in html


def test_serenity_aistocks_index_template_includes_price_cells_and_restore_hooks(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    workbook = load_serenity_aistocks_workbook()
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": sheet,
            "selected_sheet_slug": sheet["sheet_slug"],
            "selected_sheet_summary": workbook["sheets"][0],
            "sync_status": {
                "running": True,
                "interval_seconds": 60,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "科技线短缺材料总表" in html
    assert "所属分类" in html
    assert "核心概念 / 备注" in html
    assert "价格" in html
    assert "data-row-id=" in html
    assert "data-market=" in html
    assert "data-code=" in html
    assert "/serenity/aistocks/prices" in html
    assert "setInterval" in html
    assert "价格加载中" in html
    assert "status-pending" in html
    assert "status-up" in html
    assert "status-down" in html
    assert "applyPriceDirectionState" in html
    assert "数据库最新同步价格" in html
    assert "后台同步" in html
    assert "/serenity/aistocks/status" in html
    assert "refreshSyncStatus" in html
    assert "2026-06-17 10:00:00" in html
    assert "lastSerenityAIStocksSheetSlug" in html
    assert "window.location.replace" in html
    assert "查找 3买时间" in html
    assert "/serenity/aistocks/recent-three-buy-times" in html
    assert "recent-three-buy-time" in html
    assert "扫描异常" in html


def test_serenity_aistocks_index_template_renders_cached_recent_three_buy(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "recent_three_buy_time_text": "2026-06-08",
                    "label": "最近 3买",
                    "status": "ok",
                    "updated_at_text": "2026-06-26 10:00:00",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    workbook = load_serenity_aistocks_workbook()
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": sheet,
            "selected_sheet_slug": sheet["sheet_slug"],
            "selected_sheet_summary": workbook["sheets"][0],
            "sync_status": {
                "running": True,
                "interval_seconds": 60,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "2026-06-08" in html
    assert "最近 3买" in html


def test_serenity_aistocks_index_template_includes_rate_sort_controls(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    workbook = load_serenity_aistocks_workbook()
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": sheet,
            "selected_sheet_slug": sheet["sheet_slug"],
            "selected_sheet_summary": workbook["sheets"][0],
            "sync_status": {
                "running": True,
                "interval_seconds": 60,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert 'id="rate-sort-button"' in html
    assert "data-original-index=" in html
    assert "data-rate-value=" in html
    assert "applyRateSort" in html
    assert "getNextRateSortState" in html
    assert 'currentRateSortState = "none"' in html
    assert "data-sort-state=" in html
    assert 'id="three-buy-sort-button"' in html
    assert "data-three-buy-value=" in html
    assert "currentThreeBuySortState" in html
    assert "applyThreeBuySort" in html


def test_serenity_aistocks_index_template_includes_chart_trigger_on_stock_name(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    workbook = load_serenity_aistocks_workbook()
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": sheet,
            "selected_sheet_slug": sheet["sheet_slug"],
            "selected_sheet_summary": workbook["sheets"][0],
            "sync_status": {
                "running": True,
                "interval_seconds": 60,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "data-chart-trigger" in html
    assert "data-chart-url" in html
    assert "data-chart-unavailable-reason" in html
    assert 'id="chart-modal"' in html
    assert 'id="chart-modal-frame"' in html
    assert 'id="chart-modal-open-new-tab"' in html
    assert "showChartLoading" in html
    assert "hideChartLoading" in html
    assert "preloadChartUrl" in html
    assert "chartModalState.currentUrl" in html


def test_fetch_serenity_aistocks_recent_three_buy_times_uses_daily_d_and_prefers_bi_3b(monkeypatch):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        },
        {
            "row_id": "sheet-2",
            "market": "us",
            "code": "NVDA",
            "symbol": "NVDA",
        },
    ]

    requested_frequencies = []

    def fake_load_recent_three_buy_markers(market, code, frequency="d"):
        requested_frequencies.append(frequency)
        if code == "SH.600183":
            return [
                {"points": {"time": 1717200000}, "text": "BI:3B"},
                {"points": {"time": 1717286400}, "text": "XD:3B"},
            ]
        return [{"points": {"time": 1717372800}, "text": "BI:L3B"}]

    monkeypatch.setattr(
        serenity_aistocks,
        "_load_recent_three_buy_markers",
        fake_load_recent_three_buy_markers,
    )

    payload = fetch_serenity_aistocks_recent_three_buy_times(items)

    assert payload["hits"][0]["row_id"] == "sheet-1"
    assert payload["hits"][0]["recent_three_buy_time_text"] == "2024-06-01"
    assert payload["hits"][1]["recent_three_buy_time_text"] == "2024-06-03"
    assert payload["misses"] == []
    assert requested_frequencies == ["d", "d"]


def test_fetch_serenity_aistocks_recent_three_buy_times_replaces_rows_in_database(monkeypatch):
    items = [
        {"row_id": "sheet-1", "market": "a", "code": "SH.600183", "symbol": "sh600183"},
        {"row_id": "sheet-2", "market": "us", "code": "NVDA", "symbol": "NVDA"},
        {"row_id": "sheet-3", "market": "", "code": "", "symbol": ""},
    ]
    captured_rows = []

    class FakeDB:
        def serenity_aistocks_recent_three_buy_replace(self, rows):
            captured_rows.extend(rows)
            return True

    def fake_load_recent_three_buy_markers(market, code, frequency="d"):
        if code == "SH.600183":
            return [{"points": {"time": 1717200000}, "text": "BI:3B"}]
        if code == "NVDA":
            return []
        raise AssertionError("unexpected code")

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_recent_three_buy_markers",
        fake_load_recent_three_buy_markers,
    )

    payload = fetch_serenity_aistocks_recent_three_buy_times(items)

    assert payload["hits"][0]["row_id"] == "sheet-1"
    assert payload["misses"][0]["row_id"] == "sheet-2"
    assert payload["misses"][0]["status"] == "not_found"
    assert payload["misses"][1]["row_id"] == "sheet-3"
    assert payload["misses"][1]["status"] == "unsupported"
    assert len(captured_rows) == 2
    assert captured_rows[0]["code"] == "SH.600183"
    assert captured_rows[0]["recent_three_buy_time_text"] == "2024-06-01"
    assert captured_rows[0]["status"] == "ok"
    assert captured_rows[1]["code"] == "NVDA"
    assert captured_rows[1]["status"] == "not_found"
    assert captured_rows[1]["recent_three_buy_time_text"] == "--"


def test_load_recent_three_buy_markers_uses_non_fq_daily_klines(monkeypatch):
    requested = {}

    class FakeExchange:
        def klines(self, code, frequency, args=None):
            requested["code"] = code
            requested["frequency"] = frequency
            requested["args"] = dict(args or {})
            return "fake-klines"

    monkeypatch.setattr(serenity_aistocks, "get_exchange", lambda market: FakeExchange())
    monkeypatch.setattr(serenity_aistocks, "query_cl_chart_config", lambda market, code: {})
    monkeypatch.setattr(
        serenity_aistocks,
        "apply_lite_chart_config_override",
        lambda cl_config, lite_chart: dict(cl_config),
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "web_batch_get_cl_datas",
        lambda market, code, klines, cl_config: ["fake-cd"],
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "cl_data_to_tv_chart",
        lambda cd, cl_config: {"mmds": [{"points": {"time": 1717200000}, "text": "BI:3B"}]},
    )

    markers = serenity_aistocks._load_recent_three_buy_markers("a", "SH.600183", frequency="d")

    assert requested["code"] == "SH.600183"
    assert requested["frequency"] == "d"
    assert requested["args"]["fq"] == ""
    assert markers[0]["text"] == "BI:3B"


def test_serenity_aistocks_routes_exist(app_client):
    _, client = app_client
    workbook = load_serenity_aistocks_workbook()
    first_sheet_slug = workbook["sheets"][0]["sheet_slug"]

    overview = client.get("/serenity/aistocks")
    detail = client.get(f"/serenity/aistocks/{first_sheet_slug}")
    prices = client.post(
        "/serenity/aistocks/prices",
        json={
            "items": [
                {
                    "row_id": "test-1",
                    "market": "us",
                    "code": "NVDA",
                    "symbol": "NVDA",
                }
            ]
        },
    )
    three_buy_times = client.post(
        "/serenity/aistocks/recent-three-buy-times",
        json={
            "items": [
                {
                    "row_id": "test-1",
                    "market": "us",
                    "code": "NVDA",
                    "symbol": "NVDA",
                }
            ]
        },
    )
    status = client.get("/serenity/aistocks/status")

    assert overview.status_code == 200
    assert detail.status_code == 200
    assert prices.status_code == 200
    assert three_buy_times.status_code == 200
    assert status.status_code == 200
    assert "Sheet 总览" in overview.get_data(as_text=True)
    assert "后台同步" in overview.get_data(as_text=True)
    assert "Sheet 总览" in detail.get_data(as_text=True)
    assert "后台同步" in detail.get_data(as_text=True)
    assert 'id="rate-sort-button"' in detail.get_data(as_text=True)
    assert 'id="chart-modal"' in detail.get_data(as_text=True)
    assert "quotes" in prices.get_json()
    assert "hits" in three_buy_times.get_json()
    assert status.get_json()["running"] is True
    assert status.get_json()["last_success_count"] == 18


def test_serenity_aistocks_prices_reads_from_database(app_client, monkeypatch):
    _, client = app_client

    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            assert items == [
                {
                    "row_id": "a-1",
                    "market": "a",
                    "code": "sh600183",
                    "symbol": "sh600183",
                }
            ]
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "price_text": "23.450",
                    "rate_text": "+1.23%",
                    "status": "ok",
                    "updated_at_text": "2026-06-17 10:00:00",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    response = client.post(
        "/serenity/aistocks/prices",
        json={
            "items": [
                {
                    "row_id": "a-1",
                    "market": "a",
                    "code": "sh600183",
                    "symbol": "sh600183",
                }
            ]
        },
    )

    payload = response.get_json()

    assert response.status_code == 200
    assert payload["quotes"]
    assert payload["quotes"][0]["row_id"] == "a-1"
    assert payload["quotes"][0]["price_text"] == "23.450"
    assert payload["quotes"][0]["rate_text"] == "+1.23%"
    assert payload["quotes"][0]["status"] == "ok"
    assert payload["unsupported"] == []


def test_sync_serenity_aistocks_latest_prices_deduplicates_targets_and_replaces_rows(monkeypatch):
    captured = {}

    class FakeDB:
        def serenity_aistocks_latest_prices_replace(self, rows):
            captured["rows"] = rows
            return True

    monkeypatch.setattr(
        serenity_aistocks,
        "_load_workbook_payload",
        lambda: {
            "sheet_details": {
                "sheet-a": {
                    "rows": [
                        {
                            "row_id": "sheet-a-1",
                            "quote_target": {
                                "market": "a",
                                "code": "sh600183",
                                "normalized_code": "SH.600183",
                                "symbol": "sh600183",
                                "status": "ok",
                            },
                        },
                        {
                            "row_id": "sheet-a-2",
                            "quote_target": {
                                "market": "a",
                                "code": "sh600183",
                                "normalized_code": "SH.600183",
                                "symbol": "sh600183",
                                "status": "ok",
                            },
                        },
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(serenity_aistocks, "get_exchange", lambda market: object())

    def fake_fetch_tick_snapshots(ex, codes):
        assert codes == ["SH.600183"]
        return {"SH.600183": {"price": 23.45, "rate": 1.23}}

    monkeypatch.setattr(serenity_aistocks, "fetch_tick_snapshots", fake_fetch_tick_snapshots)

    result = sync_serenity_aistocks_latest_prices(db_instance=FakeDB())

    assert result["total_candidates"] == 1
    assert result["success_count"] == 1
    assert result["unsupported_count"] == 0
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["market"] == "a"
    assert captured["rows"][0]["code"] == "SH.600183"
    assert captured["rows"][0]["price_text"] == "23.450"
