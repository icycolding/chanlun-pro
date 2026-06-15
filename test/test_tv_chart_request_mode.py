from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.tv_chart_request_mode import apply_lite_chart_config_override, is_lite_chart_request


def test_is_lite_chart_request_only_accepts_explicit_true_values():
    assert is_lite_chart_request({"lite_chart": "1"}) is True
    assert is_lite_chart_request({"lite_chart": "true"}) is True
    assert is_lite_chart_request({"lite_chart": "yes"}) is True
    assert is_lite_chart_request({"lite_chart": "0"}) is False
    assert is_lite_chart_request({}) is False


def test_apply_lite_chart_config_override_disables_low_to_high_without_mutating_input():
    original = {"enable_kchart_low_to_high": "1", "kline_type": "kline_default"}

    overridden = apply_lite_chart_config_override(original, lite_chart=True)

    assert overridden["enable_kchart_low_to_high"] == "0"
    assert overridden["kline_type"] == "kline_default"
    assert original["enable_kchart_low_to_high"] == "1"


def test_apply_lite_chart_config_override_keeps_original_when_not_lite_mode():
    original = {"enable_kchart_low_to_high": "1"}

    overridden = apply_lite_chart_config_override(original, lite_chart=False)

    assert overridden == original
