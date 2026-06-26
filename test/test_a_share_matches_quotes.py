from pathlib import Path
from types import SimpleNamespace
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from chanlun.exchange.exchange import Tick

from cl_app.a_share_matches_quotes import (
    build_chart_url,
    build_tick_snapshot,
    fetch_tick_snapshots,
    infer_project_chart_target,
    infer_project_quote_target,
    normalize_a_share_code,
    normalize_market_codes,
)


def test_build_tick_snapshot_includes_price_and_swing_pct():
    tick = Tick(
        code="688498",
        last=50.0,
        buy1=49.9,
        sell1=50.1,
        high=52.0,
        low=48.0,
        open=49.0,
        volume=123456,
        rate=2.5,
    )

    snapshot = build_tick_snapshot("688498", tick)

    assert snapshot["code"] == "688498"
    assert snapshot["price"] == 50.0
    assert snapshot["rate"] == 2.5
    assert snapshot["swing_rate"] == 8.2
    assert snapshot["high"] == 52.0
    assert snapshot["low"] == 48.0
    assert snapshot["market_cap"] is None
    assert snapshot["market_cap_text"] == "实时总市值待行情源补齐"
    assert snapshot["market_cap_source"] == "tick_unavailable"


def test_build_tick_snapshot_falls_back_to_last_price_when_reference_missing():
    tick = Tick(
        code="000001",
        last=10.0,
        buy1=9.9,
        sell1=10.1,
        high=10.5,
        low=9.8,
        open=0.0,
        volume=1000,
        rate=-100.0,
    )

    snapshot = build_tick_snapshot("000001", tick)

    assert snapshot["swing_rate"] == 7.0


def test_build_tick_snapshot_includes_market_cap_when_tick_provides_it():
    tick = SimpleNamespace(
        code="688498",
        last=50.0,
        high=52.0,
        low=48.0,
        open=49.0,
        rate=2.5,
        market_value=1234567890.0,
    )

    snapshot = build_tick_snapshot("688498", tick)

    assert snapshot["market_cap"] == 1234567890.0
    assert snapshot["market_cap_text"] == "12.35亿"
    assert snapshot["market_cap_source"] == "market_value"


def test_normalize_a_share_code_adds_expected_exchange_prefix():
    assert normalize_a_share_code("688498") == "SH.688498"
    assert normalize_a_share_code("603083") == "SH.603083"
    assert normalize_a_share_code("300394") == "SZ.300394"
    assert normalize_a_share_code("002281") == "SZ.002281"
    assert normalize_a_share_code("830000") == "BJ.830000"


def test_normalize_a_share_code_supports_prefixed_exchange_codes():
    assert normalize_a_share_code("sh600183") == "SH.600183"
    assert normalize_a_share_code("sz002281") == "SZ.002281"
    assert normalize_a_share_code("bj830000") == "BJ.830000"


def test_normalize_market_codes_only_changes_a_share_market():
    assert normalize_market_codes("a", ["688498", "SZ.300394"]) == [
        "SH.688498",
        "SZ.300394",
    ]
    assert normalize_market_codes("us", ["AAPL"]) == ["AAPL"]


def test_infer_project_quote_target_supports_us_and_hk_cases():
    assert infer_project_quote_target("SIVE", "OMXSTO", "Sweden/US") == {
        "market": "us",
        "code": "SIVEF",
    }
    assert infer_project_quote_target("SIVE", "OMXSTO", "Sweden/US", "Sivers Semiconductors AB") == {
        "market": "us",
        "code": "SIVEF",
    }
    assert infer_project_quote_target("LITE", "NASDAQ", "US") == {
        "market": "us",
        "code": "LITE",
    }
    assert infer_project_quote_target("00700", "HKG", "HK") == {
        "market": "hk",
        "code": "KH.00700",
    }


def test_infer_project_quote_target_returns_none_for_unsupported_market():
    assert infer_project_quote_target("LPK", "XETR", "Europe") is None
    assert infer_project_quote_target("SPCX", "Private", "US") is None
    assert infer_project_quote_target("VNP", "TSX", "Canada") is None


def test_infer_project_chart_target_supports_a_hk_us_and_alias_cases():
    assert infer_project_chart_target("SZ.300394", "SZSE", "China") == {
        "market": "a",
        "code": "300394",
    }
    assert infer_project_chart_target("00700", "HKG", "HK") == {
        "market": "hk",
        "code": "KH.00700",
    }
    assert infer_project_chart_target("LITE", "NASDAQ", "US") == {
        "market": "us",
        "code": "LITE",
    }
    assert infer_project_chart_target("SIVE", "OMXSTO", "Sweden/US", "Sivers Semiconductors AB") == {
        "market": "us",
        "code": "SIVEF",
    }


def test_infer_project_chart_target_returns_reason_for_unsupported_market():
    assert infer_project_chart_target("LPK", "XETR", "Europe") == {
        "market": "",
        "code": "",
        "unavailable_reason": "当前未支持该市场的缠论图，请先在主图页手动切换到可支持市场。",
    }


def test_build_chart_url_uses_lite_chart_mode_for_embedded_cards():
    assert build_chart_url("a", "688498") == (
        "/?market=a&code=688498&embedded=1&lite_chart=1"
        "&default_interval=1D&load_last_chart=0"
    )


class _FakeExchange:
    def __init__(self):
        self.calls = []

    def ticks(self, codes):
        self.calls.append(list(codes))
        if len(codes) > 1:
            raise RuntimeError("batch failed")
        code = codes[0]
        if code == "GOOD":
            return {
                "GOOD": SimpleNamespace(last=12.3, rate=2.5, high=13.0, low=11.8, open=12.0)
            }
        return {}


def test_fetch_tick_snapshots_falls_back_to_single_code_requests():
    ex = _FakeExchange()
    snapshots = fetch_tick_snapshots(ex, ["GOOD", "BAD"])
    assert "GOOD" in snapshots
    assert snapshots["GOOD"]["price"] == 12.3
    assert "BAD" not in snapshots
    assert ex.calls == [["GOOD", "BAD"], ["GOOD"], ["BAD"]]
