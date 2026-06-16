from pathlib import Path
import sys

from flask import Flask, render_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))


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
