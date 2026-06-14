import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app import _parse_tv_symbol, _resolve_tv_symbol_stock_info


class _FakeFXExchange:
    def stock_info(self, code):
        return None

    def all_stocks(self):
        return [
            {"code": "FX.AUDUSD", "name": "AUDUSD", "precision": 10000},
            {"code": "FX.EURUSD", "name": "EURUSD", "precision": 10000},
        ]


class _FakeEmptyExchange:
    def stock_info(self, code):
        return None

    def all_stocks(self):
        return []


def test_resolve_tv_symbol_stock_info_matches_fx_suffix():
    stock = _resolve_tv_symbol_stock_info(_FakeFXExchange(), "fx", "audusd")
    assert stock["code"] == "FX.AUDUSD"
    assert stock["name"] == "AUDUSD"
    assert stock["precision"] == 10000


def test_resolve_tv_symbol_stock_info_falls_back_for_unknown_fx():
    stock = _resolve_tv_symbol_stock_info(_FakeEmptyExchange(), "fx", "audusd")
    assert stock["code"] == "AUDUSD"
    assert stock["name"] == "AUDUSD"
    assert stock["precision"] == 10000


def test_parse_tv_symbol_normalizes_market_and_code():
    market, code = _parse_tv_symbol("FX:audusd")
    assert market == "fx"
    assert code == "audusd"


def test_parse_tv_symbol_rejects_invalid_values():
    assert _parse_tv_symbol("") == (None, None)
    assert _parse_tv_symbol("fx") == (None, None)
    assert _parse_tv_symbol("fx:") == (None, None)
