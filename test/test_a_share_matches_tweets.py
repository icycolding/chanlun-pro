from pathlib import Path
import json
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.a_share_matches_tweets import (
    build_project_tweet_query,
    build_tweet_detail_payload,
    build_tweet_detail_url,
    build_tweet_summary_for_stock,
    find_related_tweets_for_stock,
    get_tweets_data_version,
    load_serenity_tweets,
    match_tweet_to_project_stock,
)
from cl_app.a_share_matches_tweet_notes import get_project_tweet_note


def _make_tweet(tweet_id: str, text: str, quoted_text: str = ""):
    return {
        "id": tweet_id,
        "text": text,
        "text_zh": f"ZH: {text}",
        "createdAtLocal": "2026-06-08 15:31",
        "createdAtISO": "2026-06-08T07:31:50+00:00",
        "author": {"screenName": "aleabitoreddit"},
        "metrics": {"likes": 10, "retweets": 2, "replies": 1, "quotes": 0, "views": 99},
        "quotedTweet": {"text": quoted_text, "text_zh": f"ZH: {quoted_text}"} if quoted_text else {},
    }


def _render_tweet_detail_template(**context):
    template_dir = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("a_share_match_tweets.html")
    return template.render(**context)


def test_match_tweet_to_project_stock_supports_ticker_and_company_name():
    query = build_project_tweet_query("SIVE", "Sivers Semiconductors AB", "OMXSTO", "Sweden/US", "Sivers Semiconductors")
    reasons = match_tweet_to_project_stock(
        _make_tweet("1", "JP Morgan bought 5% of $SIVE in Sivers Semiconductors AB."),
        query,
    )
    assert "Ticker" in reasons
    assert any(reason.startswith("Company Name") for reason in reasons)


def test_match_tweet_to_project_stock_supports_alias_and_quoted_tweet():
    query = build_project_tweet_query("SIVE", "Sivers Semiconductors AB", "OMXSTO", "Sweden/US", "Sivers Semiconductors")
    reasons = match_tweet_to_project_stock(
        _make_tweet("2", "I agree with this setup.", "Sivers is still underowned and $SIVEF keeps working."),
        query,
    )
    assert "Ticker Alias (SIVEF)" in reasons
    assert "Quoted Tweet" in reasons


def test_match_tweet_to_project_stock_does_not_false_positive_unrelated_tweet():
    query = build_project_tweet_query("LITE", "Lumentum Holdings Inc.", "NASDAQ", "US", "Lumentum")
    reasons = match_tweet_to_project_stock(
        _make_tweet("3", "I am focused on $NVDA and $TSM today."),
        query,
    )
    assert reasons == []


def test_build_tweet_detail_url_includes_context():
    url = build_tweet_detail_url("SIVE", "Sivers Semiconductors AB", "OMXSTO", "Sweden/US", "Sivers Semiconductors")
    assert url.startswith("/a_share_matches/tweets/SIVE?")
    assert "company_name=Sivers+Semiconductors+AB" in url
    assert "display_name=Sivers+Semiconductors" in url


def test_build_tweet_summary_for_stock_uses_cached_dataset():
    summary = build_tweet_summary_for_stock(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
    )
    assert summary["symbol"] == "SIVE"
    assert summary["mention_count"] > 0
    assert summary["latest_mention_at"]
    assert summary["detail_url"].startswith("/a_share_matches/tweets/SIVE")


def test_find_related_tweets_for_stock_deduplicates_and_returns_view_model(monkeypatch):
    dataset = [
        _make_tweet("10", "Bullish on $SIVE and Sivers Semiconductors AB."),
        _make_tweet("10", "Bullish on $SIVE and Sivers Semiconductors AB."),
        _make_tweet("11", "Nothing here."),
    ]
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.load_serenity_tweets",
        lambda: dataset,
    )
    tweets = find_related_tweets_for_stock(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
    )
    assert len(tweets) == 1
    assert tweets[0]["id"] == "10"
    assert tweets[0]["url"].endswith("/10")
    assert "Ticker" in tweets[0]["match_reasons"]
    assert tweets[0]["text_zh"].startswith("ZH:")


def test_find_related_tweets_for_stock_includes_quoted_translation(monkeypatch):
    dataset = [
        _make_tweet("12", "Main text for $SIVE.", "Quoted text for $SIVE."),
    ]
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.load_serenity_tweets",
        lambda: dataset,
    )
    tweets = find_related_tweets_for_stock(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
    )
    assert len(tweets) == 1
    assert tweets[0]["quoted_text"] == "Quoted text for $SIVE."
    assert tweets[0]["quoted_text_zh"] == "ZH: Quoted text for $SIVE."


def test_build_tweet_detail_payload_includes_version_and_bilingual_fields(monkeypatch):
    dataset = [
        _make_tweet("20", "Main text for $SIVE.", "Quoted text for $SIVE."),
    ]
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.load_serenity_tweets",
        lambda: dataset,
    )
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.get_tweets_data_version",
        lambda: "123456",
    )
    payload = build_tweet_detail_payload(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
    )
    assert payload["symbol"] == "SIVE"
    assert payload["mention_count"] == 1
    assert payload["latest_mention_at"] == "2026-06-08 15:31"
    assert payload["data_version"] == "123456"
    assert payload["overview_title"]
    assert payload["overview_summary"]
    assert payload["why_serenity_likes_it"]
    assert payload["industry_chain"]["title"]
    assert payload["industry_chain"]["nodes"]
    assert payload["stage_view"]["name"]
    assert payload["market_cap_view"]["scenarios"]
    assert payload["timeline_sections"]
    assert payload["tweets"][0]["text_zh"] == "ZH: Main text for $SIVE."
    assert payload["tweets"][0]["quoted_text_zh"] == "ZH: Quoted text for $SIVE."


def test_build_tweet_detail_payload_exposes_archive_source_metadata(monkeypatch):
    dataset = [
        _make_tweet("21", "Fresh thesis on $SIVE."),
    ]
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.load_serenity_tweets",
        lambda: dataset,
    )
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.get_tweets_data_version",
        lambda: "999",
    )
    monkeypatch.setattr(
        "cl_app.a_share_matches_tweets.get_serenity_archive_metadata",
        lambda: {
            "source_scope": "serenity_x_archive_only",
            "archive_updated_at": "2026-06-14T00:02:20Z",
            "latest_archive_at": "2026-06-08T07:31:50+00:00",
            "status": "stale",
            "coverage_note": "当前仅覆盖 Serenity 的 X/Twitter 档案，不代表全网讨论，也不含实时行情。",
        },
    )
    payload = build_tweet_detail_payload(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
    )
    assert payload["source_scope"] == "serenity_x_archive_only"
    assert payload["archive_updated_at"] == "2026-06-14T00:02:20Z"
    assert payload["latest_archive_at"] == "2026-06-08T07:31:50+00:00"
    assert payload["source_status"] == "stale"
    assert "不含实时行情" in payload["coverage_note"]


def test_get_project_tweet_note_returns_static_timeline():
    note = get_project_tweet_note("SIVE")
    assert note["overview_title"]
    assert note["overview_summary"]
    assert note["why_serenity_likes_it"]
    assert note["industry_chain"]["title"]
    assert len(note["industry_chain"]["nodes"]) >= 3
    assert note["stage_view"]["name"]
    assert note["market_cap_view"]["scenarios"]
    assert len(note["timeline_sections"]) >= 1
    assert note["timeline_sections"][0]["title"]


def test_tweet_detail_template_renders_overview_and_timeline():
    payload = build_tweet_detail_payload(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
    )
    html = _render_tweet_detail_template(
        symbol="SIVE",
        company_name="Sivers Semiconductors AB",
        exchange="OMXSTO",
        market="Sweden/US",
        display_name="Sivers Semiconductors",
        mention_count=payload["mention_count"],
        latest_mention_at=payload["latest_mention_at"],
        overview_title=payload["overview_title"],
        overview_summary=payload["overview_summary"],
        why_serenity_likes_it=payload["why_serenity_likes_it"],
        industry_chain=payload["industry_chain"],
        stage_view=payload["stage_view"],
        market_cap_view=payload["market_cap_view"],
        timeline_sections=payload["timeline_sections"],
        data_version=payload["data_version"],
        tweets=payload["tweets"],
    )
    assert "Serenity 推荐理由" in html
    assert "产业链全景" in html
    assert "当前阶段" in html
    assert "市值空间" in html
    assert "时间线" in html
    assert "为什么 Serenity 看它" in html


def test_get_tweets_data_version_changes_when_file_changes(tmp_path, monkeypatch):
    tweets_path = tmp_path / "aleabitoreddit_tweets.json"
    tweets_path.write_text(json.dumps([_make_tweet("1", "first version")]), encoding="utf-8")
    monkeypatch.setattr("cl_app.a_share_matches_tweets._TWEETS_JSON_PATH", tweets_path)

    first_version = get_tweets_data_version()
    tweets_path.write_text(json.dumps([_make_tweet("2", "second version")]), encoding="utf-8")
    second_version = get_tweets_data_version()

    assert second_version != "0"
    assert first_version != second_version


def test_load_serenity_tweets_reloads_when_json_file_changes(tmp_path, monkeypatch):
    tweets_path = tmp_path / "aleabitoreddit_tweets.json"
    tweets_path.write_text(json.dumps([_make_tweet("1", "first version")]), encoding="utf-8")

    monkeypatch.setattr("cl_app.a_share_matches_tweets._TWEETS_JSON_PATH", tweets_path)
    load_serenity_tweets.cache_clear()

    first_payload = load_serenity_tweets()
    assert first_payload[0]["id"] == "1"

    tweets_path.write_text(json.dumps([_make_tweet("2", "second version")]), encoding="utf-8")

    second_payload = load_serenity_tweets()
    assert second_payload[0]["id"] == "2"
