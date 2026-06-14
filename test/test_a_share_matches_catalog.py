from pathlib import Path
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.a_share_matches_catalog import get_a_share_match_catalog
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
    return template.render(catalog=catalog)


def test_a_share_match_catalog_has_expected_structure():
    catalog = get_a_share_match_catalog()

    assert catalog["theme_count"] == len(catalog["themes"])
    assert catalog["theme_count"] == 10
    assert catalog["project_stock_count"] == 21

    theme_slugs = set()
    for theme in catalog["themes"]:
        assert theme["title"]
        assert theme["slug"] not in theme_slugs
        theme_slugs.add(theme["slug"])
        assert theme["accent"]
        assert theme["project_stock_count"] == len(theme["project_stocks"])
        assert theme["project_stocks"]

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
