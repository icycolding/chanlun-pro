from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


_US_PROJECT_EXCHANGES = {"NASDAQ", "NYSE", "NYSEARCA", "AMEX", "OTC", "OTCQX", "OTCQB"}
_HK_PROJECT_EXCHANGES = {"HKG", "HKEX", "SEHK"}
_A_SHARE_EXCHANGES = {"SSE", "SZSE", "BSE", "STAR", "CHINEXT"}
_PROJECT_QUOTE_ALIASES = {
    ("SIVE", "OMXSTO"): {"market": "us", "code": "SIVEF"},
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _infer_reference_price(last_price: float, rate: float, open_price: float) -> float:
    change_factor = 1 + rate / 100.0
    if abs(change_factor) > 1e-9 and last_price > 0:
        prev_close = last_price / change_factor
        if prev_close > 0:
            return prev_close
    if open_price > 0:
        return open_price
    if last_price > 0:
        return last_price
    return 0.0


def normalize_a_share_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    if not normalized:
        return normalized
    if "." in normalized:
        return normalized
    if len(normalized) != 6 or not normalized.isdigit():
        return normalized

    if normalized.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return f"SH.{normalized}"
    if normalized.startswith(("000", "001", "002", "003", "159", "200", "300", "301")):
        return f"SZ.{normalized}"
    if normalized.startswith(("430", "440", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "880", "881", "882", "883", "884", "885", "886", "887", "888", "889")):
        return f"BJ.{normalized}"
    return normalized


def normalize_market_codes(market: str, codes: Iterable[str]) -> List[str]:
    normalized_market = str(market or "").strip().lower()
    normalized_codes: List[str] = []
    for code in codes or []:
        normalized_codes.append(
            normalize_a_share_code(code) if normalized_market == "a" else str(code or "").strip()
        )
    return normalized_codes


def normalize_hk_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    if not normalized:
        return normalized
    if "." in normalized:
        return normalized
    if normalized.isdigit():
        return f"KH.{normalized.zfill(5)}"
    return normalized


def infer_project_quote_target(
    symbol: str, exchange: str, market_text: str, company_name: str = ""
) -> Optional[Dict[str, str]]:
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_exchange = str(exchange or "").strip().upper()
    normalized_market = str(market_text or "").strip().upper()
    normalized_company = str(company_name or "").strip().upper()

    if not normalized_symbol or normalized_exchange == "PRIVATE":
        return None

    alias = _PROJECT_QUOTE_ALIASES.get((normalized_symbol, normalized_exchange))
    if alias:
        return dict(alias)

    if "SIVERS SEMICONDUCTORS" in normalized_company and normalized_exchange == "OMXSTO":
        return {"market": "us", "code": "SIVEF"}

    if normalized_symbol.startswith(("SH.", "SZ.", "BJ.")) or normalized_exchange in _A_SHARE_EXCHANGES:
        return {"market": "a", "code": normalize_a_share_code(normalized_symbol)}

    if normalized_exchange in _HK_PROJECT_EXCHANGES or normalized_market in {"HK", "HONG KONG"}:
        return {"market": "hk", "code": normalize_hk_code(normalized_symbol)}

    if normalized_exchange in _US_PROJECT_EXCHANGES:
        return {"market": "us", "code": normalized_symbol}

    return None


def fetch_tick_snapshots(ex: Any, codes: Iterable[str]) -> Dict[str, Dict[str, float | str]]:
    normalized_codes = [str(code or "").strip() for code in codes or [] if str(code or "").strip()]
    if not normalized_codes:
        return {}

    stock_ticks = {}
    try:
        stock_ticks = ex.ticks(normalized_codes) or {}
    except Exception:
        stock_ticks = {}

    snapshots = {
        code: build_tick_snapshot(code, tick) for code, tick in stock_ticks.items() if tick is not None
    }
    missing_codes = [code for code in normalized_codes if code not in snapshots]
    if not missing_codes:
        return snapshots

    for code in missing_codes:
        try:
            single_tick = ex.ticks([code]) or {}
        except Exception:
            continue
        tick = single_tick.get(code)
        if tick is None and single_tick:
            tick = next(iter(single_tick.values()))
        if tick is not None:
            snapshots[code] = build_tick_snapshot(code, tick)

    return snapshots


def build_tick_snapshot(code: str, tick: Any) -> Dict[str, float | str]:
    last_price = _safe_float(getattr(tick, "last", 0.0))
    rate = round(_safe_float(getattr(tick, "rate", 0.0)), 2)
    high = _safe_float(getattr(tick, "high", 0.0))
    low = _safe_float(getattr(tick, "low", 0.0))
    open_price = _safe_float(getattr(tick, "open", 0.0))

    reference_price = _infer_reference_price(last_price, rate, open_price)
    swing_rate = round(((high - low) / reference_price) * 100, 2) if reference_price > 0 else 0.0

    return {
        "code": code,
        "price": last_price,
        "rate": rate,
        "high": high,
        "low": low,
        "open": open_price,
        "swing_rate": swing_rate,
    }
