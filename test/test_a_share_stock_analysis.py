import datetime as dt
from pathlib import Path
import sys
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.a_share_stock_analysis import (
    build_stock_analysis_detail_payload,
    build_stock_analysis_detail_url,
    build_stock_analysis_summaries,
)
import cl_app.a_share_stock_analysis as stock_analysis_module
from cl_app.a_share_stock_analysis_workspace import sync_workspace_stock_analysis_payload


def _financial_item(report_date: dt.date, statement_type: str, item_name: str, item_value: float):
    return SimpleNamespace(
        report_date=report_date,
        statement_type=statement_type,
        item_name=item_name,
        item_value=item_value,
    )


def _news_row(title: str, published_at: dt.datetime, source: str = "Refinitiv Workspace", body: str = "body"):
    return SimpleNamespace(
        title=title,
        published_at=published_at,
        source=source,
        body=body,
        story_id=f"story-{title}",
        importance_score=90.0,
    )


def _render_stock_analysis_template(analysis):
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("a_share_match_stock_analysis.html")
    return template.render(analysis=analysis)


def test_build_stock_analysis_detail_url_supports_project_and_match():
    project_url = build_stock_analysis_detail_url(
        entity_type="project",
        identifier="SIVE",
        display_name="Sivers Semiconductors",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
    )
    match_url = build_stock_analysis_detail_url(
        entity_type="match",
        identifier="688498",
        display_name="688498 源杰科技",
        company_name="源杰科技",
        market="A",
    )

    assert project_url.startswith("/a_share_matches/stock-analysis/project/SIVE?")
    assert "company_name=Sivers+Semiconductors+AB" in project_url
    assert "display_name=Sivers+Semiconductors" in project_url
    assert match_url.startswith("/a_share_matches/stock-analysis/match/688498?")
    assert "display_name=688498+%E6%BA%90%E6%9D%B0%E7%A7%91%E6%8A%80" in match_url


def test_build_stock_analysis_summaries_limits_news_and_prefers_workspace_data(monkeypatch):
    financial_rows = [
        _financial_item(dt.date(2026, 3, 31), "Income Statement", "Revenue", 120.0),
        _financial_item(dt.date(2025, 12, 31), "Income Statement", "Revenue", 100.0),
        _financial_item(dt.date(2026, 3, 31), "Income Statement", "Net Income", 24.0),
        _financial_item(dt.date(2025, 12, 31), "Income Statement", "Net Income", 20.0),
    ]
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: financial_rows,
    )

    summaries = build_stock_analysis_summaries(
        [
            {
                "entity_type": "match",
                "identifier": "688498",
                "display_name": "688498 源杰科技",
                "company_name": "源杰科技",
                "market": "A",
            }
        ]
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["entity_type"] == "match"
    assert summary["financial_summary_short"]
    assert summary["financial_source"] == "workspace"
    assert summary["news_source"] == "hidden"
    assert summary["latest_news"] == []


def test_build_stock_analysis_summaries_falls_back_to_local_news_search(monkeypatch):
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: [],
    )

    summaries = build_stock_analysis_summaries(
        [
            {
                "entity_type": "project",
                "identifier": "SIVE",
                "display_name": "Sivers Semiconductors",
                "company_name": "Sivers Semiconductors AB",
                "exchange": "OMXSTO",
                "market": "Sweden/US",
            }
        ]
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["financial_source"] == "unavailable"
    assert summary["news_source"] == "hidden"
    assert summary["latest_news"] == []


def test_build_stock_analysis_summaries_uses_normalized_prefixed_financial_code(monkeypatch):
    def fake_company_financials_query(**kwargs):
        code = kwargs.get("code")
        if code == "SH.688498":
            return [
                _financial_item(dt.date(2026, 3, 31), "Income Statement", "Revenue", 210.0),
                _financial_item(dt.date(2025, 12, 31), "Income Statement", "Revenue", 180.0),
            ]
        return []

    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis.db.company_financials_query",
        fake_company_financials_query,
    )

    summaries = build_stock_analysis_summaries(
        [
            {
                "entity_type": "match",
                "identifier": "688498",
                "display_name": "688498 源杰科技",
                "company_name": "源杰科技",
                "market": "A",
            }
        ]
    )

    assert summaries[0]["financial_source"] == "workspace"
    assert "最新营收" in summaries[0]["financial_summary_short"]


def test_build_stock_analysis_detail_payload_includes_ai_analysis_and_tweet_link(monkeypatch):
    financial_rows = [
        _financial_item(dt.date(2026, 3, 31), "Income Statement", "Revenue", 320.0),
        _financial_item(dt.date(2025, 12, 31), "Income Statement", "Revenue", 280.0),
        _financial_item(dt.date(2026, 3, 31), "Income Statement", "Net Income", 64.0),
        _financial_item(dt.date(2025, 12, 31), "Income Statement", "Net Income", 56.0),
    ]
    news_rows = [
        _news_row("Workspace 新闻 A", dt.datetime(2026, 6, 15, 10, 0)),
        _news_row("Workspace 新闻 B", dt.datetime(2026, 6, 14, 10, 0)),
    ]

    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: financial_rows,
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._search_local_news",
        lambda **kwargs: ([
            {"title": item.title, "published_at": item.published_at.strftime("%Y-%m-%d %H:%M"), "source": item.source}
            for item in news_rows
        ], "workspace"),
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis.search_news_by_stock",
        lambda *args, **kwargs: {"success": True, "results": [], "total_found": 0},
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._build_ai_financial_analysis",
        lambda *args, **kwargs: "AI 财务解读结论",
    )

    payload = build_stock_analysis_detail_payload(
        entity_type="project",
        identifier="SIVE",
        display_name="Sivers Semiconductors",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        chart_url="/?market=us&code=SIVEF",
    )

    assert payload["financial_summary"]
    assert payload["financial_ai_analysis"] == "AI 财务解读结论"
    assert payload["tweet_detail_url"].startswith("/a_share_matches/tweets/SIVE?")
    assert len(payload["latest_news"]) == 2
    assert payload["detail_url"].startswith("/a_share_matches/stock-analysis/project/SIVE?")


def test_build_stock_analysis_detail_payload_includes_selection_metrics_for_project_and_match(monkeypatch):
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._search_local_news",
        lambda **kwargs: ([], "unavailable"),
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._build_ai_financial_analysis",
        lambda *args, **kwargs: "暂无财务数据，无法生成 AI 解读。",
    )

    project_payload = build_stock_analysis_detail_payload(
        entity_type="project",
        identifier="SIVE",
        display_name="Sivers Semiconductors",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
    )
    match_payload = build_stock_analysis_detail_payload(
        entity_type="match",
        identifier="688498",
        display_name="688498 源杰科技",
        company_name="源杰科技",
        market="A",
    )

    assert project_payload["selection_reason"]["summary"]
    assert project_payload["market_cap_research"]["current_text"]
    assert project_payload["segment_market_view"]["market_size_text"]
    assert project_payload["market_cap_live_text"] == "实时总市值待行情源补齐"
    assert match_payload["selection_reason"]["summary"]
    assert match_payload["market_cap_research"]["current_text"]
    assert match_payload["segment_market_view"]["company_share_text"]
    assert match_payload["market_cap_live_text"] == "实时总市值待行情源补齐"


def test_build_stock_analysis_detail_payload_falls_back_to_default_selection_metrics(monkeypatch):
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._search_local_news",
        lambda **kwargs: ([], "unavailable"),
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._build_ai_financial_analysis",
        lambda *args, **kwargs: "暂无财务数据，无法生成 AI 解读。",
    )

    payload = build_stock_analysis_detail_payload(
        entity_type="project",
        identifier="UNKNOWN",
        display_name="Unknown",
        company_name="Unknown Inc.",
        exchange="NASDAQ",
        market="US",
    )

    assert payload["selection_reason"]["summary"]
    assert payload["selection_reason"]["fit_basis"]
    assert payload["scarcity_view"]["label"]
    assert payload["capacity_view"]["label"]
    assert payload["pricing_view"]["label"]
    assert payload["market_cap_research"]["current_text"]
    assert payload["segment_market_view"]["market_size_text"]
    assert payload["segment_market_view"]["company_share_text"]
    assert payload["market_cap_live_text"] == "实时总市值待行情源补齐"


def test_build_stock_analysis_detail_payload_surfaces_theme_specific_deep_research_metrics(monkeypatch):
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._search_local_news",
        lambda *args, **kwargs: ([], "local"),
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._build_ai_financial_analysis",
        lambda *args, **kwargs: "暂无财务数据，无法生成 AI 解读。",
    )

    cases = [
        ("project", "SNDK", "SanDisk Corporation", "NASDAQ", "US", "HBM shortage"),
        ("match", "603019", "603019 中科曙光", None, "A", "GPU 真正上电交付"),
        ("project", "TSM", "Taiwan Semiconductor Manufacturing Co.", "NYSE", "US/Taiwan", "N2"),
        ("match", "688120", "688120 华海清科", None, "A", "平坦化"),
        ("project", "RKLB", "Rocket Lab USA, Inc.", "NASDAQ", "US", "75次成功任务"),
        ("match", "600406", "600406 国电南瑞", None, "A", "354.32 亿元"),
        ("project", "VPG", "Vishay Precision Group, Inc.", "NYSE", "US", "高精度 sensing"),
        ("match", "688027", "688027 国盾量子", None, "A", "两台量子计算整机交付"),
    ]

    for entity_type, identifier, display_name, exchange, market, expected_text in cases:
        payload = build_stock_analysis_detail_payload(
            entity_type=entity_type,
            identifier=identifier,
            display_name=display_name,
            company_name=display_name.split(" ", 1)[-1] if entity_type == "match" else display_name,
            exchange=exchange,
            market=market,
        )
        joined = " ".join(
            [
                payload["selection_reason"]["summary"],
                payload["selection_reason"]["fit_basis"],
                payload["scarcity_view"]["detail"],
                payload["capacity_view"]["detail"],
                payload["pricing_view"]["detail"],
                payload["segment_market_view"]["market_size_text"],
            ]
        )
        assert expected_text in joined


def test_build_stock_analysis_detail_payload_surfaces_live_market_cap_from_quote_snapshot(monkeypatch):
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._query_financial_rows",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._search_local_news",
        lambda *args, **kwargs: ([], "local"),
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis._build_ai_financial_analysis",
        lambda *args, **kwargs: "暂无财务数据，无法生成 AI 解读。",
    )
    monkeypatch.setattr(
        stock_analysis_module,
        "_build_live_quote_snapshot",
        lambda **kwargs: {
            "price_text": "123.45",
            "change_text": "+2.30%",
            "market_cap_text": "321.00亿",
            "swing_text": "5.60%",
            "range_text": "120.00 - 126.00",
            "market_text": "A",
        },
        raising=False,
    )

    payload = build_stock_analysis_detail_payload(
        entity_type="match",
        identifier="688498",
        display_name="688498 源杰科技",
        company_name="源杰科技",
        market="A",
    )

    assert payload["market_cap_live_text"] == "321.00亿"
    assert payload["live_quote"]["price_text"] == "123.45"
    assert payload["live_quote"]["change_text"] == "+2.30%"


def test_a_share_match_stock_analysis_template_renders_selection_metrics_panel():
    html = _render_stock_analysis_template(
        {
            "display_name": "Sivers Semiconductors",
            "identifier": "SIVE",
            "entity_type": "project",
            "company_name": "Sivers Semiconductors AB",
            "exchange": "OMXSTO",
            "market": "Sweden/US",
            "financial_source": "workspace",
            "news_source": "workspace",
            "chart_url": "/?market=us&code=SIVEF",
            "tweet_detail_url": "/a_share_matches/tweets/SIVE",
            "financial_summary": "财务摘要",
            "financial_ai_analysis": "AI 财务解读",
            "latest_news": [],
            "selection_reason": {
                "summary": "因为它卡在上游光源位置。",
                "fit_basis": "比普通模组更靠近 choke point。",
            },
            "scarcity_view": {"label": "高", "detail": "供应商少。"},
            "capacity_view": {"label": "扩产难", "detail": "验证周期长。"},
            "pricing_view": {"label": "有涨价基础", "detail": "供需偏紧时更容易传导。"},
            "market_cap_research": {
                "current_text": "当前按 60-90 亿美元理解。",
                "upside_text": "上行情形按 120-150 亿美元理解。",
            },
            "market_cap_live_text": "实时总市值待行情源补齐",
            "segment_market_view": {
                "market_size_text": "对应环节市场规模约数十亿美元。",
                "company_share_text": "公司份额约低个位数。",
                "share_level": "早期卡位",
            },
        }
    )

    assert "为什么符合" in html
    assert "稀缺性" in html
    assert "扩产难度" in html
    assert "涨价能力" in html
    assert "研究市值" in html
    assert "实时市值" in html
    assert "环节市场规模" in html
    assert "公司份额" in html
    assert "份额等级" in html


def test_a_share_match_stock_analysis_template_renders_live_quote_refresh_controls():
    html = _render_stock_analysis_template(
        {
            "display_name": "Sivers Semiconductors",
            "identifier": "SIVE",
            "entity_type": "project",
            "company_name": "Sivers Semiconductors AB",
            "exchange": "OMXSTO",
            "market": "Sweden/US",
            "financial_source": "workspace",
            "news_source": "workspace",
            "chart_url": "/?market=us&code=SIVEF",
            "tweet_detail_url": "/a_share_matches/tweets/SIVE",
            "financial_summary": "财务摘要",
            "financial_ai_analysis": "AI 财务解读",
            "latest_news": [],
            "selection_reason": {
                "summary": "因为它卡在上游光源位置。",
                "fit_basis": "比普通模组更靠近 choke point。",
            },
            "scarcity_view": {"label": "高", "detail": "供应商少。"},
            "capacity_view": {"label": "扩产难", "detail": "验证周期长。"},
            "pricing_view": {"label": "有涨价基础", "detail": "供需偏紧时更容易传导。"},
            "market_cap_research": {
                "current_text": "当前按 60-90 亿美元理解。",
                "upside_text": "上行情形按 120-150 亿美元理解。",
            },
            "market_cap_live_text": "321.00亿",
            "live_quote": {
                "price_text": "123.45",
                "change_text": "+2.30%",
                "market_cap_text": "321.00亿",
                "swing_text": "5.60%",
                "range_text": "120.00 - 126.00",
                "market_text": "US",
            },
            "segment_market_view": {
                "market_size_text": "对应环节市场规模约数十亿美元。",
                "company_share_text": "公司份额约低个位数。",
                "share_level": "早期卡位",
            },
        }
    )

    assert "实时行情" in html
    assert "123.45" in html
    assert "loadLiveQuote" in html
    assert "setInterval" in html


def test_sync_workspace_stock_analysis_payload_inserts_news_and_financials(monkeypatch):
    inserted_news = []
    inserted_financials = []

    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis_workspace.db.news_insert",
        lambda payload: inserted_news.append(payload) or True,
    )
    monkeypatch.setattr(
        "cl_app.a_share_stock_analysis_workspace.db.company_financials_insert",
        lambda **kwargs: inserted_financials.append(kwargs) or True,
    )

    result = sync_workspace_stock_analysis_payload(
        {
            "news_items": [
                {
                    "entity_type": "project",
                    "identifier": "SIVE",
                    "display_name": "Sivers Semiconductors",
                    "company_name": "Sivers Semiconductors AB",
                    "title": "Workspace 新闻",
                    "body": "News body",
                    "source": "Refinitiv Workspace",
                    "published_at": "2026-06-15T10:30:00",
                    "story_id": "story-1",
                }
            ],
            "financial_reports": [
                {
                    "entity_type": "match",
                    "identifier": "688498",
                    "company_name": "源杰科技",
                    "report_date": "2026-03-31",
                    "statement_type": "Income Statement",
                    "financials": [
                        {"item_name": "Revenue", "item_value": 123.0},
                        {"item_name": "Net Income", "item_value": 45.0},
                    ],
                }
            ],
        }
    )

    assert result["news_inserted"] == 1
    assert result["financial_reports_inserted"] == 1
    assert result["financial_rows_inserted"] == 2
    assert inserted_news[0]["source"] == "Refinitiv Workspace"
    assert "workspace" in inserted_news[0]["tags"].lower()
    assert inserted_financials[0]["code"] == "688498"
    assert inserted_financials[0]["name"] == "源杰科技"
