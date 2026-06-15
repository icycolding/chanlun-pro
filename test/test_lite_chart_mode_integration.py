from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHARTS_JS = (
    PROJECT_ROOT
    / "web"
    / "chanlun_chart"
    / "cl_app"
    / "static"
    / "js"
    / "charts.js"
)
CL_APP_INIT = PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app" / "__init__.py"


def test_charts_js_reads_lite_chart_url_flags_and_disables_last_chart_restore():
    source = CHARTS_JS.read_text(encoding="utf-8")

    assert "lite_chart" in source
    assert "default_interval" in source
    assert "load_last_chart" in source
    assert "new URLSearchParams(window.location.search)" in source


def test_tv_history_route_applies_lite_chart_override_before_cache_and_fetch():
    source = CL_APP_INIT.read_text(encoding="utf-8")

    assert "lite_chart = is_lite_chart_request(request.args)" in source
    assert "cl_config = apply_lite_chart_config_override(cl_config, lite_chart)" in source
