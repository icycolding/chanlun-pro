from pathlib import Path
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.a_share_matches_catalog import get_a_share_match_catalog
from cl_app.a_share_matches_quotes import infer_project_chart_target
from cl_app.a_share_matches_tweet_notes import get_project_tweet_note
from cl_app.a_share_matches_tweets import build_tweet_detail_url


def _render_a_share_matches_template():
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("a_share_matches.html")
    catalog = get_a_share_match_catalog()
    for theme in catalog["themes"]:
      for stock in theme["project_stocks"]:
        stock["tweet_detail_url"] = build_tweet_detail_url(
            symbol=stock["symbol"],
            company_name=stock["company_name"],
            exchange=stock["exchange"],
            market=stock["market"],
            display_name=stock["display_name"],
        )
        chart_target = infer_project_chart_target(
            symbol=stock["symbol"],
            exchange=stock["exchange"],
            market_text=stock["market"],
            company_name=stock["company_name"],
        )
        stock["chart_url"] = (
            f"/?market={chart_target['market']}&code={chart_target['code']}"
            "&embedded=1&lite_chart=1&default_interval=1D&load_last_chart=0"
            if chart_target.get("market") and chart_target.get("code")
            else ""
        )
        stock["chart_unavailable_reason"] = chart_target.get("unavailable_reason", "")
        stock["chart_frequency_label"] = "主页图形"
      for related in theme["theme_related_stocks"]:
        related.setdefault("detail_url", f"/a_share_matches/theme-stock/{theme['slug']}/{related['code']}")
    return template.render(catalog=catalog)


def _render_theme_related_detail_template(context):
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("a_share_match_theme_stock.html")
    return template.render(**context)


def test_a_share_match_catalog_has_expected_structure():
    catalog = get_a_share_match_catalog()

    assert catalog["theme_count"] == len(catalog["themes"])
    assert catalog["theme_count"] == 10
    assert catalog["project_stock_count"] == 21
    assert catalog["theme_related_stock_count"] > 0

    theme_slugs = set()
    for theme in catalog["themes"]:
        assert theme["title"]
        assert theme["slug"] not in theme_slugs
        theme_slugs.add(theme["slug"])
        assert theme["accent"]
        assert theme["project_stock_count"] == len(theme["project_stocks"])
        assert theme["related_stock_count"] == len(theme["theme_related_stocks"])
        assert theme["project_stocks"]
        assert theme["theme_related_stocks"]

        for stock in theme["project_stocks"]:
            assert stock["symbol"] is not None
            assert stock["display_name"]
            assert stock["company_name"]
            assert stock["theme_chip"]
            assert stock["research_summary"]
            assert stock["serenity_reason_summary"]
            assert stock["tweet_detail_label"]
            assert stock["stage_snapshot"]["name"]
            assert stock["market_cap_snapshot"]["current_anchor"]
            assert "chart_url" in stock
            assert stock["chart_frequency_label"] == "主页图形"
            assert "chart_unavailable_reason" in stock
            assert stock["main_matches"]
            assert stock["candidate_matches"]

            for match_group in [stock["main_matches"], stock["candidate_matches"]]:
                for match in match_group:
                    assert len(match["code"]) == 6
                    assert match["display_name"].startswith(match["code"])
                    assert 0 <= match["serenity_fit_score"] <= 20
                    assert match["serenity_fit_level"] in {"高", "中高", "中", "观察"}
                    assert match["supply_chain_position"]
                    assert match["mapping_path"]
                    assert match["judgement"]
                    assert match["major_risk"]
                    assert match["chart_url"].startswith("/?market=a&code=")
                    assert "&embedded=1" in match["chart_url"]
                    assert "&lite_chart=1" in match["chart_url"]
                    assert match["chart_frequency_label"] == "主页图形"

        for related in theme["theme_related_stocks"]:
            assert len(related["code"]) == 6
            assert related["display_name"].startswith(related["code"])
            assert related["role"]
            assert related["serenity_angle"]
            assert related["stage"]
            assert related["market_cap_hint"]
            assert related["major_risk"]
            assert related["detail_url"].endswith(f"/{theme['slug']}/{related['code']}")
            assert related["chart_url"].startswith("/?market=a&code=")
            assert "&embedded=1" in related["chart_url"]
            assert "&lite_chart=1" in related["chart_url"]
            assert related["chart_frequency_label"] == "主页图形"


def test_a_share_matches_template_renders_new_serenity_fit_structure():
    html = _render_a_share_matches_template()

    assert "Serenity Fit 数值 + 等级" in html
    assert "主题导航" in html
    assert "主映射" in html
    assert "候选池" in html
    assert "Serenity 视角" in html
    assert "Serenity 推荐理由" in html
    assert "查看推荐脉络" in html
    assert 'class="theme-nav-link is-active"' in html
    assert 'href="#theme-光模块-CPO-光子器件"' in html
    assert 'data-theme-section' in html
    assert 'data-symbol="SIVE"' in html
    assert 'data-a-share-code="688498"' in html
    assert "18/20" in html
    assert "项目股票价格" in html
    assert "查看相关 Tweets" in html
    assert "当前阶段" in html
    assert "市值空间" in html
    assert "--theme-accent:" in html
    assert "Serenity 主题扩展股票" in html
    assert "按主题扩展挖掘" in html
    assert "查看扩展详情" in html
    assert 'data-related-code="688498"' in html
    assert "查看缠论图" in html
    assert 'id="chart-modal"' in html
    assert 'id="chart-modal-loading"' in html
    assert 'data-chart-trigger' in html
    assert "requestIdleCallback" in html
    assert "preloadChartUrl" in html
    assert "查看推荐脉络" in html
    assert "查看扩展详情" in html


def test_all_project_stocks_have_rich_tweet_note_content():
    catalog = get_a_share_match_catalog()

    for theme in catalog["themes"]:
        for stock in theme["project_stocks"]:
            note = get_project_tweet_note(stock["symbol"])
            assert note["industry_chain"]["title"]
            assert note["industry_chain"]["nodes"]
            assert note["stage_view"]["name"]
            assert note["market_cap_view"]["current_anchor"]
            assert note["market_cap_view"]["scenarios"]


def test_theme_related_detail_template_renders_core_sections():
    catalog = get_a_share_match_catalog()
    theme = catalog["themes"][0]
    related = theme["theme_related_stocks"][0]

    html = _render_theme_related_detail_template(
        {
            "theme_title": theme["title"],
            "theme_accent": theme["accent"],
            "stock": related,
        }
    )

    assert "Serenity 主题扩展股票" in html
    assert theme["title"] in html
    assert related["display_name"] in html
    assert "Serenity 角度" in html
    assert "当前阶段" in html
    assert "市值空间判断" in html
    assert "主要风险" in html
    assert "查看缠论图" in html
