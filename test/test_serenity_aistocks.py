import json
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
from cl_app.serenity_aistocks_serenity_fit import get_serenity_aistock_fit_entry
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


@pytest.fixture(autouse=True)
def isolate_aistocks_scan_task_cache(monkeypatch):
    cache_store = {}

    def fake_cache_get(key):
        return cache_store.get(key)

    def fake_cache_set(key, val, expire=0):
        cache_store[key] = json.loads(json.dumps(val))
        return True

    def fake_cache_del(key):
        cache_store.pop(key, None)
        return True

    serenity_aistocks._AISTOCKS_SCAN_TASKS.clear()
    serenity_aistocks._AISTOCKS_ACTIVE_SCAN_TASKS.clear()
    monkeypatch.setattr(serenity_aistocks.db, "cache_get", fake_cache_get)
    monkeypatch.setattr(serenity_aistocks.db, "cache_set", fake_cache_set)
    monkeypatch.setattr(serenity_aistocks.db, "cache_del", fake_cache_del)
    yield
    serenity_aistocks._AISTOCKS_SCAN_TASKS.clear()
    serenity_aistocks._AISTOCKS_ACTIVE_SCAN_TASKS.clear()


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
            "interval_seconds": 180,
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


def test_sheet_detail_hydrates_recent_beichi_from_database(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            return []

        def serenity_aistocks_recent_beichi_query(self, items):
            assert items
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "recent_beichi_time_text": "2026-06-18",
                    "current_beichi_status_text": "当前背驰",
                    "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                    "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                    "status": "ok",
                    "updated_at_text": "2026-06-26 10:00:00",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    first_row = sheet["rows"][0]

    assert first_row["recent_beichi_time_text"] == "2026-06-18"
    assert first_row["current_beichi_status_text"] == "当前背驰"
    assert first_row["current_beichi_types_text"] == "笔:背驰,盘整背驰 / 线段:趋势背驰"
    assert first_row["recent_beichi_status"] == "ok"
    assert first_row["recent_beichi_updated_at_text"] == "2026-06-26 10:00:00"


def test_sheet_detail_corrects_known_symbol_for_guoci_materials(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("科技线短缺材料总表")
    row = next(item for item in sheet["rows"] if item["cells"].get("名称") == "国瓷材料")

    assert row["cells"]["代码"] == "sz300285"
    assert row["quote_target"]["normalized_code"] == "SZ.300285"


def test_sheet_detail_corrects_known_symbol_for_defu_technology(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    row = next(item for item in sheet["rows"] if item["cells"].get("名称") == "德福科技")

    assert row["cells"]["代码"] == "sz301511"
    assert row["quote_target"]["normalized_code"] == "SZ.301511"
    assert row["quote_target"]["normalized_code"] != "SH.688728"


def test_sheet_detail_includes_serenity_fit_view_and_detail_url(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光模块及关键材料")
    row = next(item for item in sheet["rows"] if item["cells"].get("名称") == "云南锗业")

    assert row["serenity_fit_status"] in {"fit", "partial_fit", "not_fit", "watch"}
    assert row["serenity_fit_label"] in {"符合", "部分符合", "不符合", "待观察"}
    assert row["serenity_fit_reason_short"]
    assert row["serenity_fit_detail_url"].startswith("/a_share_matches/stock-analysis/serenity_aistock/")


def test_sheet_detail_uses_per_stock_serenity_research_for_optics_sheet(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光模块及关键材料")
    yunnan = next(item for item in sheet["rows"] if item["cells"].get("名称") == "云南锗业")
    youyan = next(item for item in sheet["rows"] if item["cells"].get("名称") == "有研新材")
    huagong = next(item for item in sheet["rows"] if item["cells"].get("名称") == "华工科技")

    assert yunnan["serenity_fit_status"] == "partial_fit"
    assert "锗产品产销量全国第一" in yunnan["serenity_fit_reason_short"]
    assert youyan["serenity_fit_status"] == "fit"
    assert "国内唯一、全球第二家" in youyan["serenity_fit_reason_short"]
    assert huagong["serenity_fit_status"] == "not_fit"
    assert "高景气交付层" in huagong["serenity_fit_reason_short"]
    assert yunnan["serenity_fit_detail_url"].startswith("/a_share_matches/stock-analysis/serenity_aistock/")


def test_sheet_detail_exposes_industry_chain_market_cap_and_evidence_for_optics_sheet(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光模块及关键材料")
    fujing = next(item for item in sheet["rows"] if item["cells"].get("名称") == "福晶科技")
    fit_entry = get_serenity_aistock_fit_entry(fujing["row_id"])

    assert fujing["serenity_fit_reason_short"]
    assert fujing["serenity_fit_detail_url"].startswith("/a_share_matches/stock-analysis/serenity_aistock/")
    assert fit_entry["industry_chain_view"]["upstream"]
    assert fit_entry["industry_chain_view"]["company_link_position"]
    assert fit_entry["market_cap_research"]["current_text"]
    assert fit_entry["market_cap_research"]["rationale"]
    assert fit_entry["evidence_sources"]
    assert fit_entry["evidence_sources"][0]["url"].startswith("http")


def test_sheet_detail_exposes_structured_research_for_target_optics_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光模块及关键材料")
    target_names = ["海特高新", "天通股份", "福晶科技", "东山精密"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"]
        assert fit_entry["industry_chain_view"]["midstream"]
        assert fit_entry["industry_chain_view"]["downstream"]
        assert fit_entry["industry_chain_view"]["company_link_position"]
        assert fit_entry["industry_chain_view"]["choke_point_note"]
        assert fit_entry["market_cap_research"]["current_text"]
        assert fit_entry["market_cap_research"]["upside_text"]
        assert fit_entry["market_cap_research"]["downside_text"]
        assert fit_entry["market_cap_research"]["rationale"]
        assert len(fit_entry["evidence_sources"]) >= 2
        assert all(source["title"] for source in fit_entry["evidence_sources"])
        assert all(source["summary"] for source in fit_entry["evidence_sources"])
        assert all(source["url"].startswith("http") for source in fit_entry["evidence_sources"])
        assert all(source["source_type"] for source in fit_entry["evidence_sources"])


def test_sheet_detail_exposes_structured_research_for_four_target_a_shares():
    target_rows = ["gmkjgjcl-1", "gmkjgjcl-2", "gmkjgjcl-3", "gmkjgjcl-4"]

    for row_id in target_rows:
        fit_entry = get_serenity_aistock_fit_entry(row_id)

        assert fit_entry["industry_chain_view"]["upstream"]
        assert fit_entry["industry_chain_view"]["midstream"]
        assert fit_entry["industry_chain_view"]["downstream"]
        assert fit_entry["industry_chain_view"]["company_link_position"]
        assert fit_entry["industry_chain_view"]["choke_point_note"]
        assert fit_entry["market_cap_research"]["current_text"]
        assert fit_entry["market_cap_research"]["upside_text"]
        assert fit_entry["market_cap_research"]["downside_text"]
        assert fit_entry["market_cap_research"]["rationale"]
        assert len(fit_entry["evidence_sources"]) >= 3
        assert all(source["title"] for source in fit_entry["evidence_sources"])
        assert all(source["summary"] for source in fit_entry["evidence_sources"])
        assert all(source["url"].startswith("http") for source in fit_entry["evidence_sources"])
        assert all(source["source_type"] for source in fit_entry["evidence_sources"])


def test_sheet_detail_exposes_structured_research_for_last_seven_optics_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光模块及关键材料")
    target_names = ["源杰科技", "长光华芯", "华工科技", "光迅科技", "仕佳光子", "长光博创", "腾景科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"]
        assert fit_entry["industry_chain_view"]["midstream"]
        assert fit_entry["industry_chain_view"]["downstream"]
        assert fit_entry["industry_chain_view"]["company_link_position"]
        assert fit_entry["industry_chain_view"]["choke_point_note"]
        assert fit_entry["market_cap_research"]["current_text"]
        assert fit_entry["market_cap_research"]["upside_text"]
        assert fit_entry["market_cap_research"]["downside_text"]
        assert fit_entry["market_cap_research"]["rationale"]
        assert len(fit_entry["evidence_sources"]) >= 2
        assert all(source["title"] for source in fit_entry["evidence_sources"])
        assert all(source["summary"] for source in fit_entry["evidence_sources"])
        assert all(source["url"].startswith("http") for source in fit_entry["evidence_sources"])


def test_sheet_detail_exposes_non_placeholder_serenity_research_for_electronics_key_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("电子元器件")
    target_names = ["三环集团", "顺络电子"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 2


def test_sheet_detail_exposes_non_placeholder_serenity_research_for_fiber_key_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光纤光缆及上游材料")
    target_names = ["长飞光纤", "中天科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 2


def test_sheet_detail_exposes_deep_serenity_research_for_additional_electronics_and_fiber_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    targets = [
        ("电子元器件", "国瓷材料"),
        ("电子元器件", "博迁新材"),
        ("光纤光缆及上游材料", "亨通光电"),
        ("光纤光缆及上游材料", "烽火通信"),
    ]

    for sheet_name, name in targets:
        sheet = get_serenity_aistocks_sheet(sheet_name)
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 2


def test_sheet_detail_exposes_deep_serenity_research_for_chip_key_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["神工股份", "中船特气", "江丰电子", "富创精密"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_chip_batch2_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["沪硅产业", "立昂微", "昊华科技", "隆华科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_chip_batch3_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["中巨芯", "南大光电", "阿石创", "欧莱新材"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_chip_batch4_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["西安奕材", "有研硅", "和远气体", "正帆科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_chip_batch5_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["TCL中环", "上海合晶", "有研新材", "中瓷电子"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_chip_batch6_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["先锋精科", "珂玛科技", "华亚智能", "旭光电子"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_chip_batch7_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("芯片半导体")
    target_names = ["中晶科技", "金博股份"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_electronics_batch2_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("电子元器件")
    target_names = ["风华高科", "鸿远电子", "红星发展", "洁美科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_electronics_batch3_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("电子元器件")
    target_names = ["火炬电子", "双星新材", "海星股份", "新疆众和"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_electronics_batch4_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("电子元器件")
    target_names = ["博杰股份", "江海股份", "东阳光", "麦捷科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_electronics_batch5_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("电子元器件")
    target_names = ["中国中车", "美锦能源", "元力股份", "艾华集团"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_fiber_batch1_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光纤光缆及上游材料")
    target_names = ["三孚股份", "新安股份", "宏柏新材", "江瀚新材"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_fiber_batch2_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光纤光缆及上游材料")
    target_names = ["通鼎互联", "特发信息", "金信诺", "永鼎股份"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_fiber_batch3_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光纤光缆及上游材料")
    target_names = ["长江通信", "通光线缆", "杭电股份", "华脉科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_fiber_batch4_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("光纤光缆及上游材料")
    target_names = ["远东股份", "汇源通信", "万隆光电"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_ccl_batch1_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    target_names = ["生益科技", "华正新材", "宏和科技", "铜冠铜箔"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_ccl_batch2_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    target_names = ["东材科技", "宏昌电子", "圣泉集团", "中国巨石"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_ccl_batch3_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    target_names = ["南亚新材", "诺德股份", "德福科技", "嘉元科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_ccl_batch4_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    target_names = ["中一科技", "宝鼎科技", "光华科技", "天承科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_exposes_deep_serenity_research_for_ccl_batch5_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    target_names = ["金安国纪", "焕新材", "同宇新材", "中材科技"]

    for name in target_names:
        row = next(item for item in sheet["rows"] if item["cells"].get("名称") == name)
        fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert len(fit_entry["evidence_sources"]) >= 3


def test_sheet_detail_category_fallback_builds_non_placeholder_research_for_generic_names(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    generic_row_ids = ["dzyqj-2", "gxgljsycl-3"]

    for row_id in generic_row_ids:
        fit_entry = get_serenity_aistock_fit_entry(row_id)

        assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
        assert fit_entry["industry_chain_view"]["company_link_position"] != "公司环节待补充"
        assert fit_entry["industry_chain_view"]["choke_point_note"] != "真正 choke point 待补充"
        assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
        assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
        assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
        assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
        assert all(source["source_type"] for source in fit_entry["evidence_sources"])


def test_all_aistocks_rows_build_methodology_aligned_serenity_research(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    workbook = load_serenity_aistocks_workbook()

    for summary in workbook["sheets"]:
        sheet = get_serenity_aistocks_sheet(summary["sheet_name"])
        for row in sheet["rows"]:
            fit_entry = get_serenity_aistock_fit_entry(row["row_id"])

            assert fit_entry["fit_reason_short"]
            assert fit_entry["fit_reason_detail"]
            assert fit_entry["fit_basis"]
            assert fit_entry["industry_chain_view"]["upstream"] != "待补充"
            assert fit_entry["industry_chain_view"]["midstream"] != "待补充"
            assert fit_entry["industry_chain_view"]["downstream"] != "待补充"
            assert fit_entry["market_cap_research"]["current_text"] != "研究市值待补充"
            assert fit_entry["market_cap_research"]["upside_text"] != "上行情形待补充"
            assert fit_entry["market_cap_research"]["downside_text"] != "下行情形待补充"
            assert fit_entry["market_cap_research"]["rationale"] != "研究逻辑待补充"
            assert len(fit_entry["evidence_sources"]) >= 2
            assert all(source["title"] for source in fit_entry["evidence_sources"])
            assert all(source["summary"] for source in fit_entry["evidence_sources"])
            assert all(source["url"].startswith("http") for source in fit_entry["evidence_sources"])
            assert all(source["source_type"] for source in fit_entry["evidence_sources"])


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


def test_workbook_a_share_rows_match_unique_local_name_lookup(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    ex = serenity_aistocks.get_exchange(serenity_aistocks.Market.A)
    all_stocks = ex.all_stocks() or []
    name_to_symbols: dict[str, set[str]] = {}
    for stock in all_stocks:
        name = str(stock.get("name") or "").strip()
        normalized_code = str(stock.get("code") or "").strip()
        if not name or not normalized_code:
            continue
        excel_symbol = normalized_code.split(".")
        if len(excel_symbol) == 2:
            excel_symbol_text = f"{excel_symbol[0].lower()}{excel_symbol[1]}"
        else:
            excel_symbol_text = normalized_code.lower()
        name_to_symbols.setdefault(name, set()).add(excel_symbol_text)

    workbook = load_serenity_aistocks_workbook()
    mismatches: list[str] = []
    for summary in workbook["sheets"]:
        sheet = get_serenity_aistocks_sheet(summary["sheet_slug"])
        for row in sheet["rows"]:
            quote_target = row.get("quote_target") or {}
            if quote_target.get("market") != "a":
                continue
            name = str((row.get("cells") or {}).get("名称") or "").strip()
            if not name:
                continue
            candidates = sorted(name_to_symbols.get(name) or [])
            if len(candidates) != 1:
                continue
            actual_symbol = str(quote_target.get("symbol") or "").strip().lower()
            expected_symbol = candidates[0]
            if actual_symbol != expected_symbol:
                mismatches.append(f"{name}: {actual_symbol} != {expected_symbol}")

    assert not mismatches, "名称唯一匹配但代码不一致:\n" + "\n".join(mismatches[:20])


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
                "interval_seconds": 180,
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
    assert "主题" in html
    assert "搜索" in html
    assert "新增" in html
    assert "扫描" in html
    assert "科技线短缺材料总表" in html
    assert "芯片半导体" in html
    assert "后台同步" in html
    assert "Serenity 标准" in html
    assert "价格" in html
    assert "active" in html
    assert "/serenity/aistocks/" in html
    assert 'class="toolbar-toggle-bar"' in html
    assert 'class="toolbar-panels"' in html
    assert "toggleToolbarPanel" in html
    assert 'data-panel-target="themes"' in html
    assert 'data-panel-target="search"' in html
    assert 'data-panel-target="custom-stock"' in html
    assert 'data-panel-target="scan"' in html


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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
            "active_scan_tasks": {},
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
    assert "查看详情" in html
    assert "/a_share_matches/stock-analysis/serenity_aistock/" in html
    assert "const REFRESH_INTERVAL_MS = 180000;" in html
    assert "pollRecentThreeBuyTask" in html
    assert "partial_hits" in html
    assert "ACTIVE_SCAN_TASKS" in html
    assert "resumeActiveScanTasks" in html
    assert 'id="active-scan-tasks-json"' in html
    assert 'id="sheet-slugs-json"' in html
    assert 'JSON.parse(document.getElementById("active-scan-tasks-json")?.textContent || "{}")' in html


def test_serenity_aistocks_index_template_reorders_columns_for_readability(monkeypatch):
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
            "sync_status": {},
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
            "active_scan_tasks": {},
        }
    )

    assert html.index(">名称</th>") < html.index(">价格</span>")
    assert html.index(">价格</span>") < html.index(">最近 3买</span>")
    assert html.index(">背驰</span>") < html.index(">核心概念 / 备注</th>")
    assert html.index(">核心概念 / 备注</th>") < html.index(">Serenity 标准</th>")


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
                "interval_seconds": 180,
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
    assert 'data-three-buy-value="20260608"' in html


def test_serenity_aistocks_index_template_uses_compact_three_buy_layout(monkeypatch):
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
                    "recent_three_buy_scan_history_text": "2026-06-20=>2026-06-08 | 2026-06-21=>2026-06-08",
                    "recent_three_buy_scan_history_json": '[{"scan_date":"2026-06-20","three_buy_date":"2026-06-08"},{"scan_date":"2026-06-21","three_buy_date":"2026-06-08"}]',
                    "recent_three_buy_scan_start_date_text": "2026-06-20",
                    "recent_three_buy_scan_end_date_text": "2026-06-21",
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "three-buy-history" not in html
    assert 'data-tech-kind="three-buy"' in html
    assert "three-buy-cell is-clickable" in html
    assert 'data-tech-history="2026-06-20=&gt;2026-06-08 | 2026-06-21=&gt;2026-06-08"' in html
    assert 'data-tech-history-json=' in html
    assert "three_buy_date" in html
    assert 'data-tech-range="2026-06-20 ~ 2026-06-21"' in html


def test_serenity_aistocks_index_template_renders_cached_recent_beichi(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            return []

        def serenity_aistocks_recent_beichi_query(self, items):
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "recent_beichi_time_text": "2026-06-18",
                    "current_beichi_status_text": "当前背驰",
                    "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                    "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                    "recent_beichi_scan_history_text": "2026-06-21=>无 | 2026-06-22=>笔:背驰,盘整背驰@2026-06-18",
                    "recent_beichi_scan_history_json": '[{"scan_date":"2026-06-21","beichi_date":"","status_text":"当前无背驰","types_text":""},{"scan_date":"2026-06-22","beichi_date":"2026-06-18","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
                    "recent_beichi_scan_start_date_text": "2026-06-20",
                    "recent_beichi_scan_end_date_text": "2026-06-22",
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "查找背驰时间" in html
    assert "当前背驰" in html
    assert "2026-06-18" in html
    assert 'data-beichi-value="20260618"' in html


def test_serenity_aistocks_index_template_uses_compact_beichi_layout(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            return []

        def serenity_aistocks_recent_beichi_query(self, items):
            return [
                {
                    "market": "a",
                    "code": "SH.600183",
                    "recent_beichi_time_text": "2026-06-18",
                    "current_beichi_status_text": "当前背驰",
                    "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                    "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                    "recent_beichi_scan_history_text": "2026-06-21=>无 | 2026-06-22=>笔:背驰,盘整背驰@2026-06-18",
                    "recent_beichi_scan_history_json": '[{"scan_date":"2026-06-21","beichi_date":"","status_text":"当前无背驰","types_text":""},{"scan_date":"2026-06-22","beichi_date":"2026-06-18","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
                    "recent_beichi_scan_start_date_text": "2026-06-20",
                    "recent_beichi_scan_end_date_text": "2026-06-22",
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "beichi-history" not in html
    assert 'data-tech-kind="beichi"' in html
    assert "beichi-cell is-clickable" in html
    assert 'data-tech-history="2026-06-21=&gt;无 | 2026-06-22=&gt;笔:背驰,盘整背驰@2026-06-18"' in html
    assert 'data-tech-history-json=' in html
    assert "beichi_date" in html
    assert 'data-tech-range="2026-06-20 ~ 2026-06-22"' in html


def test_serenity_aistocks_index_template_includes_beichi_controls_and_sort(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert 'id="recent-beichi-button"' in html
    assert "/serenity/aistocks/recent-beichi-times" in html
    assert 'id="beichi-sort-button"' in html
    assert "data-beichi-value=" in html
    assert "applyBeichiSort" in html
    assert "currentBeichiSortState" in html
    assert "pollRecentBeichiTask" in html
    assert "partial_misses" in html
    assert "resumeRecentBeichiTaskIfNeeded" in html


def test_serenity_aistocks_index_template_includes_tech_detail_modal(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert 'id="tech-detail-modal"' in html
    assert 'id="tech-detail-title"' in html
    assert 'id="tech-detail-range"' in html
    assert 'id="tech-detail-history-body"' in html
    assert "背驰日期" in html


def test_serenity_aistocks_index_template_includes_tech_detail_modal_js(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "initTechDetailModal" in html
    assert "openTechDetailModal" in html
    assert "buildTechDetailPayloadFromCell" in html
    assert "updateTechCellDataset" in html
    assert "renderTechHistoryTable" in html
    assert "parseTechHistoryRows" in html


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
                "interval_seconds": 180,
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
                "interval_seconds": 180,
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
    assert 'data-stock-search-query=' in html
    assert "/serenity/aistocks/stock-search" in html
    assert "/tv/search" not in html
    assert "searchAndOpenChartModal" in html
    assert "STOCK_SEARCH_API_URL" in html


def test_serenity_aistocks_index_template_expands_name_and_notes_columns(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert ".name-column" in html
    assert ".notes-column" in html
    assert 'class="name-column"' in html
    assert 'class="notes-column"' in html


def test_serenity_aistocks_index_template_includes_stock_filter_controls(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    workbook = load_serenity_aistocks_workbook()
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": sheet,
            "selected_sheet_slug": sheet["sheet_slug"],
            "selected_sheet_summary": next(
                item for item in workbook["sheets"] if item["sheet_slug"] == sheet["sheet_slug"]
            ),
            "sync_status": {
                "running": True,
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert 'id="stock-filter-input"' in html
    assert "搜索股票" in html
    assert "名称 / 代码 / 拼音首字母" in html
    assert 'data-stock-filter-key="' in html
    assert "applyStockFilter" in html
    assert 'id="stock-filter-summary"' in html


def test_serenity_aistocks_index_template_removes_redundant_top_summary_panel(monkeypatch):
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
                "interval_seconds": 180,
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
    assert ".sheet-summary-grid" not in html
    assert '<div class="summary-label">当前 Sheet</div>' not in html
    assert '<div class="summary-label">可抓价数量</div>' not in html
    assert "保留 Excel 原始列，并在最后新增价格列" not in html


def test_load_serenity_aistocks_workbook_includes_custom_theme_summary(monkeypatch):
    class FakeDB:
        def serenity_aistocks_custom_entries_query(self):
            return [
                {
                    "theme_name": "我的新主题",
                    "theme_slug": serenity_aistocks._slugify_sheet_name("我的新主题"),
                    "market": "a",
                    "code": "SZ.301511",
                    "symbol": "sz301511",
                    "stock_name": "德福科技",
                    "notes": "",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    workbook = load_serenity_aistocks_workbook()
    custom_sheet = next(
        (sheet for sheet in workbook["sheets"] if sheet["sheet_name"] == "我的新主题"),
        None,
    )

    assert custom_sheet is not None
    assert custom_sheet["row_count"] == 1
    assert custom_sheet["sheet_slug"] == serenity_aistocks._slugify_sheet_name("我的新主题")


def test_get_serenity_aistocks_sheet_appends_custom_rows_to_existing_theme(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            return []

        def serenity_aistocks_recent_beichi_query(self, items):
            return []

        def serenity_aistocks_custom_entries_query(self):
            return [
                {
                    "theme_name": "覆铜板（CCL）及HVLP铜箔",
                    "theme_slug": serenity_aistocks._slugify_sheet_name("覆铜板（CCL）及HVLP铜箔"),
                    "market": "a",
                    "code": "SZ.301511",
                    "symbol": "sz301511",
                    "stock_name": "自定义德福科技",
                    "notes": "自定义备注",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    custom_row = next((row for row in sheet["rows"] if row.get("is_custom_entry")), None)

    assert custom_row is not None
    assert custom_row["cells"]["名称"] == "自定义德福科技"
    assert custom_row["custom_theme_slug"] == serenity_aistocks._slugify_sheet_name("覆铜板（CCL）及HVLP铜箔")


def test_serenity_aistocks_index_template_includes_custom_stock_management_controls(monkeypatch):
    class FakeDB:
        def serenity_aistocks_latest_prices_query(self, items):
            return []

        def serenity_aistocks_recent_three_buy_query(self, items):
            return []

        def serenity_aistocks_recent_beichi_query(self, items):
            return []

        def serenity_aistocks_custom_entries_query(self):
            return [
                {
                    "theme_name": "覆铜板（CCL）及HVLP铜箔",
                    "theme_slug": serenity_aistocks._slugify_sheet_name("覆铜板（CCL）及HVLP铜箔"),
                    "market": "a",
                    "code": "SZ.301511",
                    "symbol": "sz301511",
                    "stock_name": "自定义德福科技",
                    "notes": "自定义备注",
                }
            ]

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    sheet = get_serenity_aistocks_sheet("覆铜板（CCL）及HVLP铜箔")
    workbook = load_serenity_aistocks_workbook()
    html = _render_serenity_aistocks_index(
        {
            "workbook": workbook,
            "selected_sheet": sheet,
            "selected_sheet_slug": sheet["sheet_slug"],
            "selected_sheet_summary": next(
                item for item in workbook["sheets"] if item["sheet_slug"] == sheet["sheet_slug"]
            ),
            "sync_status": {
                "running": True,
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "新增股票" in html
    assert 'id="custom-stock-code-input"' in html
    assert 'id="custom-stock-theme-input"' in html
    assert "custom-stock-delete-button" in html
    assert "submitCustomStockForm" in html
    assert 'data-toolbar-panel="custom-stock"' in html
    assert 'data-toolbar-panel="scan"' in html
    assert "技术扫描" in html
    assert 'id="custom-stock-suggestions"' in html
    assert 'id="custom-stock-selected-symbol"' in html
    assert 'id="custom-stock-selected-name"' in html
    assert 'id="custom-stock-selected-chip"' in html
    assert 'id="custom-stock-submit-button" disabled' in html
    assert "输入代码 / 名称 / 拼音首字母" in html
    assert "selectCustomStockCandidate" in html
    assert "updateCustomStockSubmitState" in html
    assert "clearSelectedCustomStock" in html


def test_serenity_aistocks_index_template_simplifies_left_sheet_navigation(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "Sheet 总览" in html
    assert 'class="sheet-badge"' in html
    assert "原始列数：" not in html
    assert "可尝试抓价：" not in html
    assert 'class="sample-list"' not in html
    assert "点击左侧任一 Sheet" not in html
    assert 'class="sidebar"' not in html
    assert 'class="layout"' not in html
    assert 'data-toolbar-panel="themes"' in html


def test_serenity_aistocks_index_template_hides_tool_panels_by_default(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
            "active_scan_tasks": {},
        }
    )

    assert 'class="toolbar-panel is-hidden"' in html
    assert "let currentToolbarPanel = \"\";" in html
    assert 'id="stock-filter-input"' in html
    assert 'id="custom-stock-form"' in html
    assert 'id="recent-three-buy-button"' in html
    assert 'id="recent-beichi-button"' in html


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

    preferred = serenity_aistocks._find_recent_three_buy_marker(
        [
            {"points": {"time": 1717200000}, "text": "BI:3B"},
            {"points": {"time": 1717286400}, "text": "XD:3B"},
        ]
    )
    assert preferred["timestamp"] == 1717200000

    def fake_scan_recent_three_buy_history(market, code, frequency="d"):
        requested_frequencies.append(frequency)
        if code == "SH.600183":
            return {
                "recent_three_buy_time": None,
                "recent_three_buy_time_text": "2024-06-01",
                "label": "最近 3买",
                "history": [],
                "history_text": "2024-06-10=>2024-06-01",
                "history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-01"}]',
                "scan_start_date_text": "2024-06-09",
                "scan_end_date_text": "2024-06-10",
                "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>2024-06-01",
            }
        return {
            "recent_three_buy_time": None,
            "recent_three_buy_time_text": "2024-06-03",
            "label": "最近 3买",
            "history": [],
            "history_text": "2024-06-10=>2024-06-03",
            "history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-03"}]',
            "scan_start_date_text": "2024-06-09",
            "scan_end_date_text": "2024-06-10",
            "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>2024-06-03",
        }

    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        fake_scan_recent_three_buy_history,
    )
    monkeypatch.setattr(serenity_aistocks, "_build_db_recent_three_buy_map", lambda items: {})
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "",
        raising=False,
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

    def fake_scan_recent_three_buy_history(market, code, frequency="d"):
        if code == "SH.600183":
            return {
                "recent_three_buy_time": None,
                "recent_three_buy_time_text": "2024-06-01",
                "label": "最近 3买",
                "history": [],
                "history_text": "2024-06-10=>2024-06-01",
                "history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-01"}]',
                "scan_start_date_text": "2024-06-09",
                "scan_end_date_text": "2024-06-10",
                "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>2024-06-01",
            }
        if code == "NVDA":
            return {
                "recent_three_buy_time": None,
                "recent_three_buy_time_text": "--",
                "label": "未找到 3买",
                "history": [],
                "history_text": "2024-06-10=>未找到",
                "history_json": '[{"scan_date":"2024-06-10","three_buy_date":""}]',
                "scan_start_date_text": "2024-06-09",
                "scan_end_date_text": "2024-06-10",
                "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>未找到",
            }
        raise AssertionError("unexpected code")

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        fake_scan_recent_three_buy_history,
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


def test_fetch_serenity_aistocks_recent_three_buy_times_returns_history_fields(monkeypatch):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]

    def fake_scan_recent_three_buy_history(market, code, frequency="d"):
        return {
            "recent_three_buy_time": None,
            "recent_three_buy_time_text": "2024-06-01",
            "label": "最近 3买",
            "history": [],
            "history_text": "2024-06-10=>2024-06-01",
            "history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-01"}]',
            "scan_start_date_text": "2024-06-09",
            "scan_end_date_text": "2024-06-10",
            "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>2024-06-01",
        }

    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        fake_scan_recent_three_buy_history,
    )

    payload = fetch_serenity_aistocks_recent_three_buy_times(items)

    first_hit = payload["hits"][0]
    assert first_hit["recent_three_buy_scan_history_text"]
    assert first_hit["recent_three_buy_scan_history_json"]
    history = json.loads(first_hit["recent_three_buy_scan_history_json"])
    assert history[0]["scan_date"]
    assert history[0]["three_buy_date"] == "2024-06-01"
    assert first_hit["recent_three_buy_scan_start_date_text"]
    assert first_hit["recent_three_buy_scan_end_date_text"]


def test_fetch_serenity_aistocks_recent_three_buy_times_uses_db_cache_when_scan_end_matches_latest_date(
    monkeypatch,
):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]

    class FakeDB:
        def serenity_aistocks_recent_three_buy_replace(self, rows):
            raise AssertionError("命中缓存时不应重复写库")

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_build_db_recent_three_buy_map",
        lambda items: {
            ("a", "SH.600183"): {
                "recent_three_buy_time_text": "2024-06-01",
                "status": "ok",
                "label": "最近 3买",
                "recent_three_buy_scan_history_text": "2024-06-10=>2024-06-01",
                "recent_three_buy_scan_history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-01"}]',
                "recent_three_buy_scan_start_date_text": "2024-06-09",
                "recent_three_buy_scan_end_date_text": "2024-06-10",
                "updated_at_text": "2024-06-10 15:00:00",
            }
        },
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "2024-06-10",
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("命中缓存时不应重算三买")
        ),
    )

    payload = fetch_serenity_aistocks_recent_three_buy_times(items)

    assert payload["hits"][0]["recent_three_buy_time_text"] == "2024-06-01"
    assert payload["hits"][0]["recent_three_buy_scan_end_date_text"] == "2024-06-10"
    assert payload["misses"] == []


def test_fetch_serenity_aistocks_recent_three_buy_times_rescans_when_cache_is_stale(monkeypatch):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]
    captured_rows = []

    class FakeDB:
        def serenity_aistocks_recent_three_buy_replace(self, rows):
            captured_rows.extend(rows)
            return True

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_build_db_recent_three_buy_map",
        lambda items: {
            ("a", "SH.600183"): {
                "recent_three_buy_time_text": "2024-06-01",
                "status": "ok",
                "label": "最近 3买",
                "recent_three_buy_scan_history_text": "2024-06-10=>2024-06-01",
                "recent_three_buy_scan_history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-01"}]',
                "recent_three_buy_scan_start_date_text": "2024-06-09",
                "recent_three_buy_scan_end_date_text": "2024-06-10",
            }
        },
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "2024-06-11",
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        lambda market, code, frequency="d": {
            "recent_three_buy_time": None,
            "recent_three_buy_time_text": "2024-06-03",
            "label": "最近 3买",
            "history": [],
            "history_text": "2024-06-11=>2024-06-03",
            "history_json": '[{"scan_date":"2024-06-11","three_buy_date":"2024-06-03"}]',
            "scan_start_date_text": "2024-06-10",
            "scan_end_date_text": "2024-06-11",
            "history_title": "2024-06-10 ~ 2024-06-11 | 2024-06-11=>2024-06-03",
        },
    )

    payload = fetch_serenity_aistocks_recent_three_buy_times(items)

    assert payload["hits"][0]["recent_three_buy_time_text"] == "2024-06-03"
    assert captured_rows[0]["recent_three_buy_scan_end_date_text"] == "2024-06-11"


def test_fetch_serenity_aistocks_recent_three_buy_times_rescans_when_latest_date_check_fails(
    monkeypatch,
):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]

    monkeypatch.setattr(
        serenity_aistocks,
        "_build_db_recent_three_buy_map",
        lambda items: {
            ("a", "SH.600183"): {
                "recent_three_buy_time_text": "2024-06-01",
                "status": "ok",
                "recent_three_buy_scan_end_date_text": "2024-06-10",
            }
        },
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "",
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        lambda market, code, frequency="d": {
            "recent_three_buy_time": None,
            "recent_three_buy_time_text": "2024-06-03",
            "label": "最近 3买",
            "history": [],
            "history_text": "2024-06-11=>2024-06-03",
            "history_json": '[{"scan_date":"2024-06-11","three_buy_date":"2024-06-03"}]',
            "scan_start_date_text": "2024-06-10",
            "scan_end_date_text": "2024-06-11",
            "history_title": "2024-06-10 ~ 2024-06-11 | 2024-06-11=>2024-06-03",
        },
    )

    payload = fetch_serenity_aistocks_recent_three_buy_times(items)

    assert payload["hits"][0]["recent_three_buy_time_text"] == "2024-06-03"


def test_fetch_serenity_aistocks_recent_beichi_times_returns_history_fields(monkeypatch):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]

    def fake_scan_recent_beichi_history(market, code, frequency="d"):
        return {
            "recent_beichi_time": None,
            "recent_beichi_time_text": "2024-06-01",
            "current_beichi_status_text": "当前背驰",
            "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
            "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
            "label": "最近背驰",
            "history": [],
            "history_text": "2024-06-10=>笔:背驰,盘整背驰@2024-06-01",
            "history_json": '[{"scan_date":"2024-06-10","beichi_date":"2024-06-01","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
            "scan_start_date_text": "2024-06-09",
            "scan_end_date_text": "2024-06-10",
            "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>笔:背驰,盘整背驰@2024-06-01",
        }

    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_beichi_history",
        fake_scan_recent_beichi_history,
        raising=False,
    )
    monkeypatch.setattr(serenity_aistocks, "_build_db_recent_beichi_map", lambda items: {})
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "",
        raising=False,
    )

    payload = serenity_aistocks.fetch_serenity_aistocks_recent_beichi_times(items)

    first_hit = payload["hits"][0]
    assert first_hit["recent_beichi_time_text"] == "2024-06-01"
    assert first_hit["current_beichi_status_text"] == "当前背驰"
    assert first_hit["current_beichi_types_text"]
    assert first_hit["recent_beichi_scan_history_text"]
    assert first_hit["recent_beichi_scan_history_json"]
    history = json.loads(first_hit["recent_beichi_scan_history_json"])
    assert history[0]["beichi_date"] == "2024-06-01"
    assert first_hit["recent_beichi_scan_start_date_text"]
    assert first_hit["recent_beichi_scan_end_date_text"]


def test_fetch_serenity_aistocks_recent_beichi_times_uses_db_cache_when_scan_end_matches_latest_date(
    monkeypatch,
):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]

    class FakeDB:
        def serenity_aistocks_recent_beichi_replace(self, rows):
            raise AssertionError("命中缓存时不应重复写库")

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_build_db_recent_beichi_map",
        lambda items: {
            ("a", "SH.600183"): {
                "recent_beichi_time_text": "2024-06-01",
                "current_beichi_status_text": "当前背驰",
                "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
                "status": "ok",
                "recent_beichi_scan_history_text": "2024-06-10=>笔:背驰,盘整背驰@2024-06-01",
                "recent_beichi_scan_history_json": '[{"scan_date":"2024-06-10","beichi_date":"2024-06-01","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
                "recent_beichi_scan_start_date_text": "2024-06-09",
                "recent_beichi_scan_end_date_text": "2024-06-10",
                "updated_at_text": "2024-06-10 15:00:00",
            }
        },
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "2024-06-10",
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_beichi_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("命中缓存时不应重算背驰")
        ),
        raising=False,
    )

    payload = serenity_aistocks.fetch_serenity_aistocks_recent_beichi_times(items)

    assert payload["hits"][0]["recent_beichi_time_text"] == "2024-06-01"
    assert payload["hits"][0]["current_beichi_status_text"] == "当前背驰"
    assert payload["misses"] == []


def test_fetch_serenity_aistocks_recent_beichi_times_rescans_when_cache_is_stale(monkeypatch):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]
    captured_rows = []

    class FakeDB:
        def serenity_aistocks_recent_beichi_replace(self, rows):
            captured_rows.extend(rows)
            return True

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_build_db_recent_beichi_map",
        lambda items: {
            ("a", "SH.600183"): {
                "recent_beichi_time_text": "2024-06-01",
                "current_beichi_status_text": "当前背驰",
                "current_beichi_types_text": "笔:背驰,盘整背驰",
                "recent_beichi_types_text": "笔:背驰,盘整背驰",
                "status": "ok",
                "recent_beichi_scan_history_text": "2024-06-10=>笔:背驰,盘整背驰@2024-06-01",
                "recent_beichi_scan_history_json": '[{"scan_date":"2024-06-10","beichi_date":"2024-06-01","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
                "recent_beichi_scan_start_date_text": "2024-06-09",
                "recent_beichi_scan_end_date_text": "2024-06-10",
            }
        },
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "2024-06-11",
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_beichi_history",
        lambda market, code, frequency="d": {
            "recent_beichi_time": None,
            "recent_beichi_time_text": "2024-06-03",
            "current_beichi_status_text": "当前背驰",
            "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
            "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
            "label": "最近背驰",
            "history": [],
            "history_text": "2024-06-11=>笔:背驰,盘整背驰@2024-06-03",
            "history_json": '[{"scan_date":"2024-06-11","beichi_date":"2024-06-03","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
            "scan_start_date_text": "2024-06-10",
            "scan_end_date_text": "2024-06-11",
            "history_title": "2024-06-10 ~ 2024-06-11 | 2024-06-11=>笔:背驰,盘整背驰@2024-06-03",
        },
        raising=False,
    )

    payload = serenity_aistocks.fetch_serenity_aistocks_recent_beichi_times(items)

    assert payload["hits"][0]["recent_beichi_time_text"] == "2024-06-03"
    assert captured_rows[0]["recent_beichi_scan_end_date_text"] == "2024-06-11"


def test_fetch_serenity_aistocks_recent_beichi_times_rescans_when_latest_date_check_fails(
    monkeypatch,
):
    items = [
        {
            "row_id": "sheet-1",
            "market": "a",
            "code": "SH.600183",
            "symbol": "sh600183",
        }
    ]

    monkeypatch.setattr(
        serenity_aistocks,
        "_build_db_recent_beichi_map",
        lambda items: {
            ("a", "SH.600183"): {
                "recent_beichi_time_text": "2024-06-01",
                "current_beichi_status_text": "当前背驰",
                "status": "ok",
                "recent_beichi_scan_end_date_text": "2024-06-10",
            }
        },
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_load_latest_daily_kline_date",
        lambda market, code, frequency="d": "",
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_beichi_history",
        lambda market, code, frequency="d": {
            "recent_beichi_time": None,
            "recent_beichi_time_text": "2024-06-03",
            "current_beichi_status_text": "当前背驰",
            "current_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
            "recent_beichi_types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
            "label": "最近背驰",
            "history": [],
            "history_text": "2024-06-11=>笔:背驰,盘整背驰@2024-06-03",
            "history_json": '[{"scan_date":"2024-06-11","beichi_date":"2024-06-03","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
            "scan_start_date_text": "2024-06-10",
            "scan_end_date_text": "2024-06-11",
            "history_title": "2024-06-10 ~ 2024-06-11 | 2024-06-11=>笔:背驰,盘整背驰@2024-06-03",
        },
        raising=False,
    )

    payload = serenity_aistocks.fetch_serenity_aistocks_recent_beichi_times(items)

    assert payload["hits"][0]["recent_beichi_time_text"] == "2024-06-03"


def test_fetch_serenity_aistocks_recent_beichi_times_replaces_rows_in_database(monkeypatch):
    items = [
        {"row_id": "sheet-1", "market": "a", "code": "SH.600183", "symbol": "sh600183"},
        {"row_id": "sheet-2", "market": "us", "code": "NVDA", "symbol": "NVDA"},
    ]
    captured_rows = []

    class FakeDB:
        def serenity_aistocks_recent_beichi_replace(self, rows):
            captured_rows.extend(rows)
            return True

    def fake_scan_recent_beichi_history(market, code, frequency="d"):
        if code == "SH.600183":
            return {
                "recent_beichi_time": None,
                "recent_beichi_time_text": "2024-06-01",
                "current_beichi_status_text": "当前背驰",
                "current_beichi_types_text": "笔:背驰,盘整背驰",
                "recent_beichi_types_text": "笔:背驰,盘整背驰",
                "label": "最近背驰",
                "history": [],
                "history_text": "2024-06-10=>笔:背驰,盘整背驰@2024-06-01",
                "history_json": '[{"scan_date":"2024-06-10","beichi_date":"2024-06-01","status_text":"当前背驰","types_text":"笔:背驰,盘整背驰"}]',
                "scan_start_date_text": "2024-06-09",
                "scan_end_date_text": "2024-06-10",
                "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>笔:背驰,盘整背驰@2024-06-01",
            }
        return {
            "recent_beichi_time": None,
            "recent_beichi_time_text": "--",
            "current_beichi_status_text": "当前无背驰",
            "current_beichi_types_text": "",
            "recent_beichi_types_text": "",
            "label": "未找到背驰",
            "history": [],
            "history_text": "2024-06-10=>无",
            "history_json": '[{"scan_date":"2024-06-10","beichi_date":"","status_text":"当前无背驰","types_text":""}]',
            "scan_start_date_text": "2024-06-09",
            "scan_end_date_text": "2024-06-10",
            "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>无",
        }

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_beichi_history",
        fake_scan_recent_beichi_history,
        raising=False,
    )

    payload = serenity_aistocks.fetch_serenity_aistocks_recent_beichi_times(items)

    assert payload["hits"][0]["recent_beichi_time_text"] == "2024-06-01"
    assert payload["misses"][0]["status"] == "not_found"
    assert captured_rows[0]["current_beichi_status_text"] == "当前背驰"
    assert captured_rows[1]["current_beichi_status_text"] == "当前无背驰"


def test_fetch_serenity_aistocks_recent_three_buy_times_replaces_rows_in_database_with_history(monkeypatch):
    items = [
        {"row_id": "sheet-1", "market": "a", "code": "SH.600183", "symbol": "sh600183"},
    ]
    captured_rows = []

    class FakeDB:
        def serenity_aistocks_recent_three_buy_replace(self, rows):
            captured_rows.extend(rows)
            return True

    def fake_scan_recent_three_buy_history(market, code, frequency="d"):
        return {
            "recent_three_buy_time": None,
            "recent_three_buy_time_text": "2024-06-01",
            "label": "最近 3买",
            "history": [],
            "history_text": "2024-06-10=>2024-06-01",
            "history_json": '[{"scan_date":"2024-06-10","three_buy_date":"2024-06-01"}]',
            "scan_start_date_text": "2024-06-09",
            "scan_end_date_text": "2024-06-10",
            "history_title": "2024-06-09 ~ 2024-06-10 | 2024-06-10=>2024-06-01",
        }

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())
    monkeypatch.setattr(
        serenity_aistocks,
        "_scan_recent_three_buy_history",
        fake_scan_recent_three_buy_history,
    )

    fetch_serenity_aistocks_recent_three_buy_times(items)

    assert captured_rows[0]["recent_three_buy_scan_history_text"]
    assert captured_rows[0]["recent_three_buy_scan_history_json"]
    history = json.loads(captured_rows[0]["recent_three_buy_scan_history_json"])
    assert history[0]["three_buy_date"] == "2024-06-01"
    assert captured_rows[0]["recent_three_buy_scan_start_date_text"]
    assert captured_rows[0]["recent_three_buy_scan_end_date_text"]


def test_serenity_aistocks_index_template_renders_cached_three_buy_history(monkeypatch):
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
                    "recent_three_buy_scan_history_text": "2026-06-21=>2026-06-03 | 2026-06-22=>2026-06-03",
                    "recent_three_buy_scan_start_date_text": "2026-06-20",
                    "recent_three_buy_scan_end_date_text": "2026-06-22",
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "2026-06-21=&gt;2026-06-03" in html
    assert "2026-06-20 ~ 2026-06-22" in html


def test_update_three_buy_frontend_contract_present_in_template(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert "updateTechCellDataset" in html
    assert "historyText" in html
    assert "historyJson" in html
    assert "techRange" in html


def test_scan_recent_three_buy_history_recomputes_without_web_cache(monkeypatch):
    klines = [
        {"date": f"2026-06-{day:02d}", "open": 10, "close": 10, "high": 10, "low": 10, "volume": 1}
        for day in range(1, 12)
    ]

    class FakeCL:
        def __init__(self, code, frequency, config):
            self.scan_date = None

        def process_klines(self, klines_df):
            self.scan_date = str(klines_df.iloc[-1]["date"])[:10]

    def fake_tv_chart(cd, config):
        mapping = {
            "2026-06-02": [],
            "2026-06-03": [{"points": {"time": 1780444800}, "text": "BI:3B"}],
            "2026-06-04": [{"points": {"time": 1780444800}, "text": "BI:3B"}],
            "2026-06-05": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
            "2026-06-06": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
            "2026-06-07": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
            "2026-06-08": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
            "2026-06-09": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
            "2026-06-10": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
            "2026-06-11": [{"points": {"time": 1780617600}, "text": "BI:3B"}],
        }
        return {"mmds": mapping.get(cd.scan_date, [])}

    monkeypatch.setattr(
        serenity_aistocks,
        "_load_recent_three_buy_source_klines",
        lambda market, code, frequency="d": serenity_aistocks.pd.DataFrame(klines),
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "web_batch_get_cl_datas",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("历史扫描不应走 web cache")
        ),
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "cl",
        type("FakeCLModule", (), {"CL": FakeCL})(),
        raising=False,
    )
    monkeypatch.setattr(serenity_aistocks, "query_cl_chart_config", lambda market, code: {})
    monkeypatch.setattr(
        serenity_aistocks,
        "apply_lite_chart_config_override",
        lambda cl_config, lite_chart: dict(cl_config),
    )
    monkeypatch.setattr(serenity_aistocks, "cl_data_to_tv_chart", fake_tv_chart)

    result = serenity_aistocks._scan_recent_three_buy_history("a", "SH.600183", "d")

    history = json.loads(result["history_json"])
    assert history[0] == {
        "scan_date": "2026-06-02",
        "three_buy_date": "",
        "label": "未找到 3买",
    }
    assert history[-1] == {
        "scan_date": "2026-06-11",
        "three_buy_date": "2026-06-05",
        "label": "最近 3买",
    }
    assert result["recent_three_buy_time_text"] == "2026-06-05"
    assert "2026-06-11=>2026-06-05" in result["history_text"]


def test_find_recent_beichi_marker_supports_multiple_types():
    marker = serenity_aistocks._find_recent_beichi_marker(
        [
            {"points": {"time": 1717200000}, "text": "笔:背驰,盘整背驰"},
            {"points": {"time": 1717286400}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"},
        ]
    )

    assert marker["timestamp"] == 1717286400
    assert marker["date_text"] == "2024-06-02"
    assert "笔:背驰,盘整背驰" in marker["types_text"]
    assert "线段:趋势背驰" in marker["types_text"]


def test_scan_recent_beichi_history_recomputes_without_web_cache(monkeypatch):
    klines = [
        {"date": f"2026-06-{day:02d}", "open": 10, "close": 10, "high": 10, "low": 10, "volume": 1}
        for day in range(1, 12)
    ]

    class FakeCL:
        def __init__(self, code, frequency, config):
            self.scan_date = None

        def process_klines(self, klines_df):
            self.scan_date = str(klines_df.iloc[-1]["date"])[:10]

    def fake_tv_chart(cd, config):
        mapping = {
            "2026-06-02": [],
            "2026-06-03": [{"points": {"time": 1780444800}, "text": "笔:背驰"}],
            "2026-06-04": [{"points": {"time": 1780444800}, "text": "笔:背驰"}],
            "2026-06-05": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
            "2026-06-06": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
            "2026-06-07": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
            "2026-06-08": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
            "2026-06-09": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
            "2026-06-10": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
            "2026-06-11": [{"points": {"time": 1780617600}, "text": "笔:背驰,盘整背驰 / 线段:趋势背驰"}],
        }
        return {"bcs": mapping.get(cd.scan_date, [])}

    monkeypatch.setattr(
        serenity_aistocks,
        "_load_recent_beichi_source_klines",
        lambda market, code, frequency="d": serenity_aistocks.pd.DataFrame(klines),
        raising=False,
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "web_batch_get_cl_datas",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("背驰历史扫描不应走 web cache")
        ),
    )
    monkeypatch.setattr(
        serenity_aistocks,
        "cl",
        type("FakeCLModule", (), {"CL": FakeCL})(),
        raising=False,
    )
    monkeypatch.setattr(serenity_aistocks, "query_cl_chart_config", lambda market, code: {})
    monkeypatch.setattr(
        serenity_aistocks,
        "apply_lite_chart_config_override",
        lambda cl_config, lite_chart: dict(cl_config),
    )
    monkeypatch.setattr(serenity_aistocks, "cl_data_to_tv_chart", fake_tv_chart)

    result = serenity_aistocks._scan_recent_beichi_history("a", "SH.600183", "d")

    history = json.loads(result["history_json"])
    assert history[0] == {
        "scan_date": "2026-06-02",
        "beichi_date": "",
        "status_text": "当前无背驰",
        "types_text": "",
    }
    assert history[-1] == {
        "scan_date": "2026-06-11",
        "beichi_date": "2026-06-05",
        "status_text": "当前背驰",
        "types_text": "笔:背驰,盘整背驰 / 线段:趋势背驰",
    }
    assert result["recent_beichi_time_text"] == "2026-06-05"
    assert result["current_beichi_status_text"] == "当前背驰"
    assert "2026-06-11=>笔:背驰,盘整背驰 / 线段:趋势背驰@2026-06-05" in result["history_text"]


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
    beichi_times = client.post(
        "/serenity/aistocks/recent-beichi-times",
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
    stock_search = client.get("/serenity/aistocks/stock-search?query=%E7%94%9F%E7%9B%8A&exchange=a")
    custom_add = client.post(
        "/serenity/aistocks/custom-stocks",
        json={"code": "sz301511", "theme_name": "我的新主题"},
    )
    custom_delete = client.delete(
        "/serenity/aistocks/custom-stocks",
        json={"theme_slug": "wdxzt", "market": "a", "code": "sz301511"},
    )

    assert overview.status_code == 200
    assert detail.status_code == 200
    assert prices.status_code == 200
    assert three_buy_times.status_code == 200
    assert beichi_times.status_code == 200
    assert status.status_code == 200
    assert stock_search.status_code == 200
    assert custom_add.status_code != 404
    assert custom_delete.status_code != 404
    assert "Sheet 总览" in overview.get_data(as_text=True)
    assert "后台同步" in overview.get_data(as_text=True)
    assert "Sheet 总览" in detail.get_data(as_text=True)
    assert "后台同步" in detail.get_data(as_text=True)
    assert 'id="rate-sort-button"' in detail.get_data(as_text=True)
    assert 'id="chart-modal"' in detail.get_data(as_text=True)
    assert "quotes" in prices.get_json()
    assert three_buy_times.get_json()["ok"] is True
    assert three_buy_times.get_json()["task_id"]
    assert beichi_times.get_json()["ok"] is True
    assert beichi_times.get_json()["task_id"]
    assert status.get_json()["running"] is True
    assert status.get_json()["last_success_count"] == 18
    assert "results" in stock_search.get_json()


def test_serenity_aistocks_recent_three_buy_task_status_route_returns_task_snapshot(app_client):
    _, client = app_client
    task_id = "three-buy-task-1"
    serenity_aistocks._set_aistocks_scan_task(
        task_id,
        task_type="recent_three_buy",
        state="running",
        message="正在扫描",
        progress=35,
        processed_items=7,
        total_items=20,
        hit_count=2,
        miss_count=5,
        partial_hits=[{"row_id": "a-1", "recent_three_buy_time_text": "2024-06-01"}],
        partial_misses=[],
    )

    response = client.get(f"/serenity/aistocks/recent-three-buy-times/task/{task_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["task_id"] == task_id
    assert payload["state"] == "running"
    assert payload["progress"] == 35
    assert payload["processed_items"] == 7
    assert payload["partial_hits"][0]["row_id"] == "a-1"


def test_serenity_aistocks_recent_beichi_task_status_route_returns_404_for_missing_task(app_client):
    _, client = app_client

    response = client.get("/serenity/aistocks/recent-beichi-times/task/missing-task")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_set_and_clear_active_aistocks_scan_task_roundtrip():
    task_snapshot = {
        "task_id": "task-1",
        "sheet_slug": "chip",
        "task_type": "recent_three_buy",
        "state": "running",
        "message": "正在扫描",
        "progress": 20,
    }

    serenity_aistocks._set_aistocks_scan_task(
        "task-1",
        sheet_slug="chip",
        task_type="recent_three_buy",
        state="running",
        message="正在扫描",
        progress=20,
    )
    serenity_aistocks._set_active_aistocks_scan_task("chip", "recent_three_buy", task_snapshot)
    loaded = serenity_aistocks._get_active_aistocks_scan_task("chip", "recent_three_buy")

    assert loaded["task_id"] == "task-1"
    assert loaded["sheet_slug"] == "chip"

    serenity_aistocks._clear_active_aistocks_scan_task("chip", "recent_three_buy", "task-1")
    assert serenity_aistocks._get_active_aistocks_scan_task("chip", "recent_three_buy") is None


def test_recent_three_buy_route_reuses_existing_active_task(app_client):
    _, client = app_client
    serenity_aistocks._set_aistocks_scan_task(
        "reuse-task-1",
        task_type="recent_three_buy",
        sheet_slug="chip",
        state="running",
        message="正在扫描",
        progress=30,
    )
    serenity_aistocks._set_active_aistocks_scan_task(
        "chip",
        "recent_three_buy",
        {
            "task_id": "reuse-task-1",
            "sheet_slug": "chip",
            "task_type": "recent_three_buy",
            "state": "running",
            "message": "正在扫描",
            "progress": 30,
        },
    )

    response = client.post(
        "/serenity/aistocks/recent-three-buy-times",
        json={
            "sheet_slug": "chip",
            "items": [{"row_id": "r1", "market": "a", "code": "SH.600183", "symbol": "SH.600183"}],
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["task_id"] == "reuse-task-1"
    assert payload["reused"] is True


def test_resolve_serenity_aistocks_page_context_includes_active_scan_tasks():
    workbook = load_serenity_aistocks_workbook()
    first_sheet_slug = workbook["sheets"][0]["sheet_slug"]
    serenity_aistocks._set_aistocks_scan_task(
        "resume-task-1",
        task_type="recent_three_buy",
        sheet_slug=first_sheet_slug,
        state="running",
        message="已完成 3 / 10 只",
        progress=30,
        processed_items=3,
        total_items=10,
    )
    serenity_aistocks._set_active_aistocks_scan_task(
        first_sheet_slug,
        "recent_three_buy",
        {
            "task_id": "resume-task-1",
            "sheet_slug": first_sheet_slug,
            "task_type": "recent_three_buy",
            "state": "running",
            "message": "已完成 3 / 10 只",
            "progress": 30,
            "processed_items": 3,
            "total_items": 10,
        },
    )

    context = serenity_aistocks._resolve_serenity_aistocks_page_context(
        status_provider=lambda: {"running": True},
        sheet_slug=first_sheet_slug,
    )

    assert context["active_scan_tasks"]["recent_three_buy"]["task_id"] == "resume-task-1"
    assert context["active_scan_tasks"]["recent_three_buy"]["state"] == "running"
    assert context["active_scan_tasks"]["recent_beichi"] is None


def test_get_active_aistocks_scan_task_ignores_stale_running_task():
    task_id = "stale-task-1"
    serenity_aistocks._set_aistocks_scan_task(
        task_id,
        task_type="recent_three_buy",
        sheet_slug="summary",
        state="running",
        message="正在扫描",
        progress=50,
    )
    with serenity_aistocks._AISTOCKS_SCAN_TASK_LOCK:
        serenity_aistocks._AISTOCKS_SCAN_TASKS[task_id]["updated_at"] = "2000-01-01T00:00:00"
    serenity_aistocks._set_active_aistocks_scan_task(
        "summary",
        "recent_three_buy",
        {
            "task_id": task_id,
            "sheet_slug": "summary",
            "task_type": "recent_three_buy",
            "state": "running",
            "message": "正在扫描",
            "progress": 50,
        },
    )

    active_task = serenity_aistocks._get_active_aistocks_scan_task("summary", "recent_three_buy")
    task_snapshot = serenity_aistocks._get_aistocks_scan_task(task_id)

    assert active_task is None
    assert task_snapshot["state"] == "failed"


def test_serenity_aistocks_recent_three_buy_task_status_route_marks_stale_running_task_failed(
    app_client,
):
    _, client = app_client
    task_id = "stale-status-task-1"
    serenity_aistocks._set_aistocks_scan_task(
        task_id,
        task_type="recent_three_buy",
        sheet_slug="kjxdqclzb",
        state="running",
        message="正在扫描",
        progress=50,
    )
    with serenity_aistocks._AISTOCKS_SCAN_TASK_LOCK:
        serenity_aistocks._AISTOCKS_SCAN_TASKS[task_id]["updated_at"] = "2000-01-01T00:00:00"
    serenity_aistocks._set_active_aistocks_scan_task(
        "kjxdqclzb",
        "recent_three_buy",
        {
            "task_id": task_id,
            "sheet_slug": "kjxdqclzb",
            "task_type": "recent_three_buy",
            "state": "running",
            "message": "正在扫描",
            "progress": 50,
        },
    )

    response = client.get(f"/serenity/aistocks/recent-three-buy-times/task/{task_id}")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["state"] == "failed"
    assert payload["error"] == "stale_task_timeout"
    assert serenity_aistocks._get_active_aistocks_scan_task("kjxdqclzb", "recent_three_buy") is None


def test_serenity_aistocks_index_template_embeds_active_scan_tasks_without_json_parse_breakage():
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
            "active_scan_tasks": {
                "recent_three_buy": {
                    "task_id": "resume-task-1",
                    "sheet_slug": sheet["sheet_slug"],
                    "task_type": "recent_three_buy",
                    "state": "running",
                    "message": "检测到未完成任务，正在恢复 John's `scan` 进度...",
                    "progress": 30,
                }
            },
        }
    )

    assert "JSON.parse('{{ (active_scan_tasks or {})|tojson|safe }}')" not in html
    assert 'id="active-scan-tasks-json"' in html
    assert 'JSON.parse(document.getElementById("active-scan-tasks-json")?.textContent || "{}")' in html
    assert "John\\u0027s" in html or "John's" in html
    assert "scan" in html


def test_serenity_aistocks_overview_keeps_shortage_summary_sheet_visible(app_client):
    _, client = app_client
    workbook = load_serenity_aistocks_workbook()
    sheet = next(item for item in workbook["sheets"] if item["sheet_name"] == "科技线短缺材料总表")

    overview = client.get("/serenity/aistocks")

    assert overview.status_code == 200
    html = overview.get_data(as_text=True)
    assert "科技线短缺材料总表" in html
    assert f'/serenity/aistocks/{sheet["sheet_slug"]}' in html


def test_serenity_aistocks_stock_search_uses_name_and_pinyin_initials(app_client, monkeypatch):
    _, client = app_client

    class FakeExchange:
        def all_stocks(self):
            return [
                {"code": "SZ.300285", "name": "国瓷材料"},
                {"code": "SH.600183", "name": "生益科技"},
                {"code": "SZ.301511", "name": "德福科技"},
            ]

    monkeypatch.setattr(serenity_aistocks, "get_exchange", lambda market: FakeExchange())

    chinese_response = client.get("/serenity/aistocks/stock-search?query=%E5%BE%B7%E7%A6%8F&exchange=a")
    pinyin_response = client.get("/serenity/aistocks/stock-search?query=dfkj&exchange=a")

    chinese_payload = chinese_response.get_json()
    pinyin_payload = pinyin_response.get_json()

    assert chinese_response.status_code == 200
    assert pinyin_response.status_code == 200
    assert chinese_payload["results"][0]["symbol"] == "SZ.301511"
    assert chinese_payload["results"][0]["description"] == "德福科技"
    assert pinyin_payload["results"][0]["symbol"] == "SZ.301511"


def test_serenity_aistocks_custom_stock_add_route_creates_new_theme(app_client, monkeypatch):
    _, client = app_client
    captured = {}

    class FakeExchange:
        def stock_info(self, code):
            normalized = str(code or "").upper()
            if normalized in {"SZ.301511", "301511", "SZ301511"}:
                return {"code": "SZ.301511", "name": "德福科技"}
            raise AssertionError(f"unexpected code: {code}")

    class FakeDB:
        def serenity_aistocks_custom_entry_add(self, row):
            captured["row"] = dict(row)
            return True

    monkeypatch.setattr(serenity_aistocks, "get_exchange", lambda market: FakeExchange())
    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    response = client.post(
        "/serenity/aistocks/custom-stocks",
        json={"code": "sz301511", "theme_name": "我的新主题"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["sheet_name"] == "我的新主题"
    assert payload["sheet_slug"] == serenity_aistocks._slugify_sheet_name("我的新主题")
    assert captured["row"]["stock_name"] == "德福科技"
    assert captured["row"]["market"] == "a"


def test_serenity_aistocks_custom_stock_submit_script_requires_selected_symbol(monkeypatch):
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
                "interval_seconds": 180,
                "last_run_at_text": "2026-06-17 10:00:00",
                "last_success_count": 18,
                "last_total_candidates": 20,
                "last_error": "",
                "status_label": "运行中",
            },
            "sheet_slugs": [item["sheet_slug"] for item in workbook["sheets"]],
        }
    )

    assert 'const selectedSymbol = String(selectedSymbolInput?.value || "").trim();' in html
    assert 'body: JSON.stringify({ code: selectedSymbol, theme_name: themeName })' in html
    assert 'const code = String(codeInput?.value || "").trim();' not in html


def test_serenity_aistocks_custom_stock_add_route_rejects_invalid_code(app_client, monkeypatch):
    _, client = app_client

    class FakeExchange:
        def stock_info(self, code):
            raise AssertionError(f"unexpected code: {code}")

    monkeypatch.setattr(serenity_aistocks, "get_exchange", lambda market: FakeExchange())

    response = client.post(
        "/serenity/aistocks/custom-stocks",
        json={"code": "NVDA", "theme_name": "我的新主题"},
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_serenity_aistocks_custom_stock_delete_route_marks_empty_theme(app_client, monkeypatch):
    _, client = app_client
    captured = {}

    class FakeDB:
        def serenity_aistocks_custom_entry_delete(self, theme_slug, market, code):
            captured["delete"] = {
                "theme_slug": theme_slug,
                "market": market,
                "code": code,
            }
            return True

        def serenity_aistocks_custom_entries_query(self):
            return []

    monkeypatch.setattr(serenity_aistocks, "db", FakeDB())

    response = client.delete(
        "/serenity/aistocks/custom-stocks",
        json={
            "theme_slug": serenity_aistocks._slugify_sheet_name("我的新主题"),
            "market": "a",
            "code": "sz301511",
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["theme_empty"] is True
    assert captured["delete"]["market"] == "a"


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


def test_serenity_aistocks_scheduler_default_interval_is_180_seconds():
    source = (
        PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert '"interval_seconds": 180' in source
    assert "_start_serenity_aistocks_price_sync(interval_seconds=180)" in source
