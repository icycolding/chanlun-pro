#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlled local tool for Hermes to access chanlun-pro analysis functions.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[4]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.news_vector_api import (  # noqa: E402
    _build_market_data_view_payload,
    _generate_historical_analysis_payload,
    _generate_theme_simulation_payload,
    _load_historical_price_bars,
    _safe_float,
)


def _extract_lookback_hours(text: str, default: int = 72) -> int:
    normalized = str(text or "").lower()
    if not normalized:
        return default
    match = __import__("re").search(r"(\d+)\s*(年|个月|月|周|天|日|小时|h|hour)", normalized)
    if match:
        value = max(int(match.group(1)), 1)
        unit = match.group(2)
        if unit == "年":
            return value * 24 * 365
        if unit in {"个月", "月"}:
            return value * 24 * 30
        if unit == "周":
            return value * 24 * 7
        if unit in {"天", "日"}:
            return value * 24
        return value
    if "一年" in normalized:
        return 24 * 365
    if "半年" in normalized:
        return 24 * 180
    if "一月" in normalized or "一个月" in normalized:
        return 24 * 30
    if "一周" in normalized:
        return 24 * 7
    return default


def _infer_frequency(payload: Dict[str, Any], lookback_hours: int) -> str:
    preferred = str(payload.get("frequency") or payload.get("event_frequency") or "").strip().lower()
    if preferred:
        return preferred
    if lookback_hours >= 24 * 180:
        return "1d"
    if lookback_hours >= 24 * 30:
        return "240m"
    if lookback_hours >= 24 * 7:
        return "60m"
    if lookback_hours >= 24:
        return "15m"
    return "5m"


def _run_drawdown_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    current_market = str(payload.get("current_market") or payload.get("market") or "").strip()
    current_code = str(payload.get("current_code") or payload.get("code") or "").strip().upper()
    if not current_market or not current_code:
        raise ValueError("drawdown_analysis requires current_market and current_code")
    message = str(payload.get("message") or payload.get("theme_text") or "").strip()
    lookback_hours = max(24, min(_extract_lookback_hours(message, default=24 * 30), 24 * 365))
    frequency = _infer_frequency(payload, lookback_hours)
    price_bars = _load_historical_price_bars(
        market=current_market,
        code=current_code,
        frequency=frequency,
        lookback_hours=lookback_hours,
        purpose="Hermes回撤分析",
    )
    if len(price_bars) < 10:
        raise ValueError("历史价格数据不足，无法进行回撤分析")
    closes = []
    for bar in price_bars:
        close_value = _safe_float(bar.get("close"))
        open_value = _safe_float(bar.get("open"))
        price_value = close_value if close_value > 0 else open_value
        if price_value > 0:
            closes.append({"dt": bar.get("dt"), "price": price_value})
    if len(closes) < 10:
        raise ValueError("历史价格数据不足，无法进行回撤分析")
    peak_index = 0
    trough_index = 0
    peak_price = closes[0]["price"]
    max_drawdown_pct = 0.0
    for idx, item in enumerate(closes):
        price_value = item["price"]
        if price_value >= peak_price:
            peak_price = price_value
            peak_index = idx
        drawdown_pct = (price_value / peak_price - 1.0) * 100.0 if peak_price > 0 else 0.0
        if drawdown_pct < max_drawdown_pct:
            max_drawdown_pct = drawdown_pct
            trough_index = idx
    peak_point = closes[peak_index]
    trough_point = closes[trough_index]
    return {
        "summary": f"{current_code} 最大回撤约为 {abs(max_drawdown_pct):.2f}%",
        "lookback_hours": lookback_hours,
        "frequency": frequency,
        "max_drawdown_pct": round(abs(max_drawdown_pct), 4),
        "drawdown": {
            "peak_dt": peak_point["dt"].isoformat() if hasattr(peak_point["dt"], "isoformat") else str(peak_point["dt"]),
            "peak_price": round(peak_point["price"], 6),
            "trough_dt": trough_point["dt"].isoformat() if hasattr(trough_point["dt"], "isoformat") else str(trough_point["dt"]),
            "trough_price": round(trough_point["price"], 6),
        },
    }


def _run_event_chart_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    working_payload = dict(payload)
    message = str(payload.get("message") or payload.get("theme_text") or "").strip()
    lookback_hours = max(12, min(_extract_lookback_hours(message, default=48), 72))
    working_payload["lookback_hours"] = lookback_hours
    working_payload["event_frequency"] = _infer_frequency(working_payload, lookback_hours)
    result = _generate_historical_analysis_payload(working_payload)
    return {
        "summary": result.get("summary") or "历史事件图已整理",
        "summary_id": result.get("summary_id"),
        "lookback_hours": lookback_hours,
        "event_frequency": result.get("event_frequency"),
        "events": list(result.get("events") or [])[:3],
        "similar_events": list(result.get("similar_events") or [])[:3],
        "event_trade_templates": list(result.get("event_trade_templates") or [])[:3],
    }


def run_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    current_market = str(payload.get("current_market") or payload.get("market") or "").strip()
    current_code = str(payload.get("current_code") or payload.get("code") or "").strip()
    if action == "theme_simulation":
        working_payload = dict(payload)
        if "theme_label" not in working_payload:
            working_payload["theme_label"] = str(payload.get("theme") or payload.get("theme_text") or "").strip()
        if "theme_text" not in working_payload:
            working_payload["theme_text"] = str(payload.get("message") or working_payload.get("theme_label") or "").strip()
        return {
            "action": action,
            "data": _generate_theme_simulation_payload(working_payload),
        }
    if action == "market_data_view":
        if not current_market or not current_code:
            raise ValueError("market_data_view requires current_market and current_code")
        return {
            "action": action,
            "data": _build_market_data_view_payload(current_market, current_code, int(payload.get("limit", 8) or 8)),
        }
    if action == "historical_analysis":
        return {
            "action": action,
            "data": _generate_historical_analysis_payload(payload),
        }
    if action == "drawdown_analysis":
        return {
            "action": action,
            "data": _run_drawdown_analysis(payload),
        }
    if action == "event_chart_review":
        return {
            "action": action,
            "data": _run_event_chart_review(payload),
        }
    raise ValueError(f"Unsupported action: {action}")


def main():
    parser = argparse.ArgumentParser(description="Controlled chanlun-pro tool for Hermes")
    parser.add_argument("--action", required=True, choices=["theme_simulation", "market_data_view", "historical_analysis", "drawdown_analysis", "event_chart_review"])
    parser.add_argument("--payload", required=True, help="JSON payload")
    args = parser.parse_args()

    payload = json.loads(args.payload or "{}")
    captured_stdout = io.StringIO()
    with contextlib.redirect_stdout(captured_stdout):
        result = run_action(args.action, payload)
    noisy_output = captured_stdout.getvalue().strip()
    if noisy_output:
        print(noisy_output, file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
