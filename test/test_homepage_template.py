from pathlib import Path
import sys

from flask import Flask, render_template
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

import cl_app
import cl_app.news_vector_db as news_vector_db


def _render_homepage_template():
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "templates"),
        static_folder=str(PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "static"),
    )
    app.secret_key = "test-secret"

    context = {
        "market_default_codes": {
            "a": "SH.000001",
            "hk": "HK.00700",
            "us": "AAPL",
            "fx": "EURUSD",
            "futures": "RB0",
            "ny_futures": "CL",
            "currency": "USDJPY",
            "currency_spot": "USDCNH",
        },
        "market_frequencys": {
            "a": ["1m", "5m", "30m", "d"],
            "hk": ["1m", "5m", "30m", "d"],
            "us": ["1m", "5m", "30m", "d"],
            "fx": ["1m", "5m", "30m", "d"],
            "futures": ["1m", "5m", "30m", "d"],
            "currency": ["1m", "5m", "30m", "d"],
            "currency_spot": ["1m", "5m", "30m", "d"],
            "ny_futures": ["1m", "5m", "30m", "d"],
        },
        "jin10_watch_defaults": {
            "interval": 60,
            "max_items": 20,
        },
    }

    with app.test_request_context("/"):
        return render_template("index.html", **context)


def test_homepage_template_removes_timesfm_controls():
    html = _render_homepage_template()

    assert "data-timesfm-" not in html
    assert "TimesFM 预测层" not in html
    assert "TimesFM 历史预测层" not in html
    assert "TimesFM 历史价格预测回顾" not in html
    assert "实时关注" not in html
    assert "市场数据底座" not in html
    assert "场景化路由与快评" not in html
    assert "风险经理" not in html
    assert "反思记忆" not in html
    assert 'id="realtime_focus_panel"' not in html


def test_homepage_template_includes_serenity_aistocks_button():
    html = _render_homepage_template()

    assert "Serenity AI Stocks" in html
    assert 'href="/serenity/aistocks"' in html


def test_homepage_template_guards_url_param_storage_when_utils_is_unavailable():
    html = _render_homepage_template()

    assert "function persistUrlParamSelection(market, code)" in html
    assert "window.Utils && typeof window.Utils.set_local_data === 'function'" in html


def test_homepage_template_uses_lightweight_news_search_api():
    html = _render_homepage_template()

    assert "/api/news/semantic_search" not in html
    assert "/api/news/search_by_symbol" in html


@pytest.fixture
def homepage_app_client(monkeypatch):
    monkeypatch.setattr(cl_app.TornadoScheduler, "start", lambda self: None)
    app = cl_app.create_app({"TESTING": True})
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "cl_pro"
        session["_fresh"] = True
    return app, client


def test_homepage_news_feed_does_not_initialize_vector_db_by_default(homepage_app_client, monkeypatch):
    _, client = homepage_app_client

    class FakeNews:
        id = 1
        news_id = "news-1"
        story_id = "story-1"
        title = "测试新闻"
        body = "测试内容"
        source = "unit-test"
        published_at = None
        language = "zh"
        category = "macro"
        tags = "测试"
        sentiment_score = 0.1
        importance_score = 0.8
        created_at = None
        updated_at = None

    monkeypatch.setattr(cl_app.db, "news_query", lambda **kwargs: [FakeNews()])
    monkeypatch.setattr(cl_app.db, "news_count", lambda **kwargs: 1)
    monkeypatch.setattr(
        news_vector_db,
        "get_vector_db",
        lambda: (_ for _ in ()).throw(AssertionError("homepage should not initialize vector db")),
    )

    response = client.get("/api/news?limit=5")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["code"] == 0
    assert payload["data"]["total_count"] == 1
