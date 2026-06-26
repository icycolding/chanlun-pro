from __future__ import annotations

import copy
import datetime
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import pandas as pd
import pinyin
from flask import abort, jsonify, render_template, request
from flask_login import login_required

from chanlun import fun
from chanlun.base import Market
from chanlun.cl_utils import cl_data_to_tv_chart, query_cl_chart_config, web_batch_get_cl_datas
from chanlun.db import db
from chanlun.exchange import get_exchange

from .a_share_matches_quotes import (
    build_chart_url,
    fetch_tick_snapshots,
    normalize_a_share_code,
    normalize_hk_code,
)
from .tv_chart_request_mode import apply_lite_chart_config_override


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AISTOCKS_XLSX_PATH = _PROJECT_ROOT / "serenity-aleabitoreddit-main" / "aistocks.xlsx"
_DEFAULT_PRICE_TEXT = "--"
_UNSUPPORTED_PRICE_TEXT = "价格不可用"
_DEFAULT_RECENT_THREE_BUY_TIME_TEXT = "--"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _format_datetime_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    normalized = _normalize_text(value)
    if not normalized:
        return ""
    try:
        return datetime.datetime.fromisoformat(normalized).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return normalized


def _normalize_cell_value(value: Any) -> str:
    text = _normalize_text(value)
    if text.lower() == "nan":
        return ""
    return text


def _slugify_sheet_name(sheet_name: str) -> str:
    normalized = _normalize_text(sheet_name)
    if not normalized:
        return "sheet"

    parts: list[str] = []
    for char in normalized:
        if char.isascii() and char.isalnum():
            parts.append(char.lower())
            continue
        if char in {" ", "/", "-", "_", "(", ")", "（", "）", "、"}:
            parts.append("-")
            continue
        py = _normalize_text(pinyin.get_initial(char)).replace(" ", "")
        if py:
            parts.append(py.lower())

    slug = re.sub(r"-+", "-", "".join(parts)).strip("-")
    return slug or f"sheet-{abs(hash(normalized))}"


def _format_price(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_PRICE_TEXT
    if abs(number) >= 100:
        return f"{number:.2f}"
    if abs(number) >= 1:
        return f"{number:.3f}"
    return f"{number:.4f}"


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.2f}%"


def _format_timestamp_to_date_text(value: Any) -> str:
    try:
        timestamp = int(float(value))
    except (TypeError, ValueError):
        return _DEFAULT_RECENT_THREE_BUY_TIME_TEXT
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _candidate_value(row: dict[str, Any], keywords: tuple[str, ...]) -> str:
    for key, value in row.items():
        normalized_key = _normalize_text(key).lower()
        if any(keyword in normalized_key for keyword in keywords):
            normalized_value = _normalize_text(value)
            if normalized_value:
                return normalized_value
    return ""


def _normalize_excel_symbol(value: str) -> str:
    return _normalize_text(value).replace(" ", "").replace("\u3000", "")


def _infer_market_from_symbol_or_text(symbol: str, market_hint: str = "", exchange_hint: str = "") -> str:
    normalized_symbol = _normalize_excel_symbol(symbol)
    normalized_market = _normalize_text(market_hint).upper()
    normalized_exchange = _normalize_text(exchange_hint).upper()

    if normalized_market in {"A", "CN", "CHINA"} or normalized_exchange in {"SSE", "SZSE", "BSE"}:
        return "a"
    if normalized_market in {"HK", "HONGKONG", "HONG KONG"} or normalized_exchange in {"HKEX", "SEHK", "HKG"}:
        return "hk"
    if normalized_market in {"US", "USA"} or normalized_exchange in {"NASDAQ", "NYSE", "AMEX", "OTC"}:
        return "us"

    if re.fullmatch(r"(sh|sz|bj)\d{6}", normalized_symbol, flags=re.IGNORECASE):
        return "a"
    if re.fullmatch(r"\d{6}", normalized_symbol):
        return "a"
    if re.fullmatch(r"\d{4,5}", normalized_symbol):
        return "hk"
    if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", normalized_symbol.upper()):
        return "us"
    return ""


def _infer_row_quote_target(row: dict[str, Any], columns: list[str]) -> dict[str, str]:
    market_hint = _candidate_value(row, ("市场", "market"))
    exchange_hint = _candidate_value(row, ("交易所", "exchange"))
    symbol_candidate = _candidate_value(row, ("代码", "ticker", "symbol", "股票代码", "证券代码"))
    name_candidate = _candidate_value(row, ("名称", "name", "公司"))

    normalized_symbol = _normalize_excel_symbol(symbol_candidate)
    market = _infer_market_from_symbol_or_text(normalized_symbol, market_hint, exchange_hint)
    if not normalized_symbol or not market:
        return {
            "market": "",
            "code": "",
            "normalized_code": "",
            "symbol": normalized_symbol,
            "name": name_candidate,
            "status": "unsupported",
        }

    normalized_code = _normalize_quote_code(market, normalized_symbol)
    return {
        "market": market,
        "code": normalized_symbol,
        "normalized_code": normalized_code,
        "symbol": normalized_symbol,
        "name": name_candidate,
        "status": "ok",
    }


def _normalize_quote_code(market: str, code: str) -> str:
    normalized_market = _normalize_text(market).lower()
    normalized_code = _normalize_text(code)
    if normalized_market == "a":
        return normalize_a_share_code(normalized_code)
    if normalized_market == "hk":
        return normalize_hk_code(normalized_code)
    if normalized_market == "us":
        return normalized_code.upper()
    return normalized_code


def _build_db_query_items(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    query_items: list[dict[str, str]] = []
    for item in items or []:
        market = _normalize_text(item.get("market")).lower()
        code = _normalize_text(item.get("code"))
        row_id = _normalize_text(item.get("row_id"))
        symbol = _normalize_text(item.get("symbol")) or code
        if not market or not code:
            continue
        query_items.append(
            {
                "row_id": row_id,
                "market": market,
                "code": code,
                "symbol": symbol,
            }
        )
    return query_items


def _build_row_chart_view(
    quote_target: dict[str, Any] | None, cells: dict[str, Any] | None = None
) -> dict[str, str]:
    normalized_target = quote_target or {}
    market = _normalize_text(normalized_target.get("market")).lower()
    normalized_code = _normalize_text(normalized_target.get("normalized_code"))
    symbol = _normalize_text(normalized_target.get("symbol"))
    name = _candidate_value(cells or {}, ("名称", "name", "公司")) or symbol
    chart_title = f"{name or symbol or '股票'} 缠论图"
    if _normalize_text(normalized_target.get("status")) != "ok" or not market or not normalized_code:
        return {
            "chart_url": "",
            "chart_unavailable_reason": "当前未获取到可用缠论图地址。",
            "chart_frequency_label": "主页图形",
            "chart_title": chart_title,
        }

    chart_code = normalized_code
    if market == "a":
        chart_code = normalized_code.split(".")[-1]
    elif market == "us":
        chart_code = symbol or normalized_code

    chart_url = build_chart_url(market, chart_code)
    return {
        "chart_url": chart_url,
        "chart_unavailable_reason": "" if chart_url else "当前未获取到可用缠论图地址。",
        "chart_frequency_label": "主页图形",
        "chart_title": chart_title,
    }


def _build_recent_three_buy_view() -> dict[str, str]:
    return {
        "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "recent_three_buy_label": "未扫描",
        "recent_three_buy_status": "pending",
        "recent_three_buy_updated_at_text": "",
    }


def _build_db_price_map(items: list[dict[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    query_items = _build_db_query_items(items)
    price_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in db.serenity_aistocks_latest_prices_query(query_items):
        market = _normalize_text(row.get("market")).lower()
        code = _normalize_quote_code(market, row.get("code"))
        if market and code:
            price_map[(market, code)] = row
    return price_map


def _hydrate_sheet_rows_with_db_prices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hydrated_rows = copy.deepcopy(rows)
    query_items = []
    for row in hydrated_rows:
        quote_target = row.get("quote_target") or {}
        if quote_target.get("status") != "ok":
            row["updated_at_text"] = ""
            continue
        query_items.append(
            {
                "row_id": row.get("row_id"),
                "market": quote_target.get("market"),
                "code": quote_target.get("code"),
                "symbol": quote_target.get("symbol"),
            }
        )

    price_map = _build_db_price_map(query_items)
    for row in hydrated_rows:
        quote_target = row.get("quote_target") or {}
        normalized_code = _normalize_text(quote_target.get("normalized_code"))
        market = _normalize_text(quote_target.get("market")).lower()
        matched = price_map.get((market, normalized_code))
        row["updated_at_text"] = ""
        if not matched:
            continue
        status = _normalize_text(matched.get("status")) or "ok"
        row["price_status"] = status
        row["updated_at_text"] = _normalize_text(matched.get("updated_at_text"))
        if status == "ok":
            row["price_text"] = _normalize_text(matched.get("price_text")) or _DEFAULT_PRICE_TEXT
            row["rate_text"] = _normalize_text(matched.get("rate_text")) or "--"
        elif status == "unsupported":
            row["price_text"] = _UNSUPPORTED_PRICE_TEXT
            row["rate_text"] = "--"
        else:
            row["price_text"] = "等待后台同步"
            row["rate_text"] = "--"
    return hydrated_rows


def _build_db_recent_three_buy_map(items: list[dict[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    query_items = _build_db_query_items(items)
    recent_three_buy_map: dict[tuple[str, str], dict[str, Any]] = {}
    query_method = getattr(db, "serenity_aistocks_recent_three_buy_query", None)
    if query_method is None:
        return recent_three_buy_map
    for row in query_method(query_items):
        market = _normalize_text(row.get("market")).lower()
        code = _normalize_quote_code(market, row.get("code"))
        if market and code:
            recent_three_buy_map[(market, code)] = row
    return recent_three_buy_map


def _hydrate_sheet_rows_with_recent_three_buy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hydrated_rows = copy.deepcopy(rows)
    query_items = []
    for row in hydrated_rows:
        quote_target = row.get("quote_target") or {}
        if quote_target.get("status") != "ok":
            row["recent_three_buy_updated_at_text"] = ""
            continue
        query_items.append(
            {
                "row_id": row.get("row_id"),
                "market": quote_target.get("market"),
                "code": quote_target.get("code"),
                "symbol": quote_target.get("symbol"),
            }
        )

    recent_three_buy_map = _build_db_recent_three_buy_map(query_items)
    for row in hydrated_rows:
        quote_target = row.get("quote_target") or {}
        normalized_code = _normalize_text(quote_target.get("normalized_code"))
        market = _normalize_text(quote_target.get("market")).lower()
        matched = recent_three_buy_map.get((market, normalized_code))
        row["recent_three_buy_updated_at_text"] = ""
        if not matched:
            continue
        row["recent_three_buy_time_text"] = (
            _normalize_text(matched.get("recent_three_buy_time_text"))
            or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT
        )
        row["recent_three_buy_label"] = _normalize_text(matched.get("label")) or "未扫描"
        row["recent_three_buy_status"] = _normalize_text(matched.get("status")) or "pending"
        row["recent_three_buy_updated_at_text"] = _normalize_text(
            matched.get("updated_at_text")
        )
    return hydrated_rows


def _build_sheet_rows(sheet_name: str) -> tuple[list[str], list[dict[str, Any]]]:
    raw_df = pd.read_excel(_AISTOCKS_XLSX_PATH, sheet_name=sheet_name, header=None)
    rows = [
        [_normalize_cell_value(value) for value in row]
        for row in raw_df.values.tolist()
    ]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return ["价格"], []

    header_index = 0
    for index, row in enumerate(rows):
        if sum(1 for cell in row if cell) >= 2:
            header_index = index
            break

    raw_headers = rows[header_index]
    headers: list[str] = []
    for index, header in enumerate(raw_headers):
        headers.append(header or f"列{index + 1}")

    data_rows: list[dict[str, Any]] = []
    for row_index, values in enumerate(rows[header_index + 1 :], start=1):
        padded_values = values + [""] * (len(headers) - len(values))
        cells = {
            header: padded_values[index] if index < len(padded_values) else ""
            for index, header in enumerate(headers)
        }
        if not any(_normalize_text(value) for value in cells.values()):
            continue
        quote_target = _infer_row_quote_target(cells, headers)
        chart_view = _build_row_chart_view(quote_target, cells)
        recent_three_buy_view = _build_recent_three_buy_view()
        data_rows.append(
            {
                "row_id": f"{_slugify_sheet_name(sheet_name)}-{row_index}",
                "cells": cells,
                "quote_target": quote_target,
                "price_text": _DEFAULT_PRICE_TEXT,
                "rate_text": "--",
                "price_status": "pending" if quote_target.get("status") == "ok" else "unsupported",
                "updated_at_text": "",
                "chart_url": chart_view["chart_url"],
                "chart_unavailable_reason": chart_view["chart_unavailable_reason"],
                "chart_frequency_label": chart_view["chart_frequency_label"],
                "chart_title": chart_view["chart_title"],
                "recent_three_buy_time_text": recent_three_buy_view["recent_three_buy_time_text"],
                "recent_three_buy_label": recent_three_buy_view["recent_three_buy_label"],
                "recent_three_buy_status": recent_three_buy_view["recent_three_buy_status"],
                "recent_three_buy_updated_at_text": recent_three_buy_view["recent_three_buy_updated_at_text"],
            }
        )

    return headers + ["价格"], data_rows


def _build_sheet_summary(sheet_name: str, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    price_candidates = [row for row in rows if (row.get("quote_target") or {}).get("status") == "ok"]
    sample_symbols = [
        (row.get("quote_target") or {}).get("symbol", "")
        for row in price_candidates[:3]
        if (row.get("quote_target") or {}).get("symbol")
    ]
    return {
        "sheet_name": sheet_name,
        "sheet_slug": _slugify_sheet_name(sheet_name),
        "columns": columns,
        "row_count": len(rows),
        "has_price_candidates": len(price_candidates),
        "sample_symbols": sample_symbols,
    }


@lru_cache(maxsize=1)
def _load_workbook_payload() -> dict[str, Any]:
    xls = pd.ExcelFile(_AISTOCKS_XLSX_PATH)
    sheets: list[dict[str, Any]] = []
    sheet_details: dict[str, dict[str, Any]] = {}
    total_row_count = 0

    for sheet_name in xls.sheet_names:
        columns, rows = _build_sheet_rows(sheet_name)
        detail = {
            "sheet_name": sheet_name,
            "sheet_slug": _slugify_sheet_name(sheet_name),
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
        summary = _build_sheet_summary(sheet_name, columns, rows)
        sheets.append(summary)
        total_row_count += len(rows)
        sheet_details[detail["sheet_slug"]] = detail
        sheet_details[sheet_name] = detail

    return {
        "workbook_name": _AISTOCKS_XLSX_PATH.name,
        "sheet_count": len(sheets),
        "total_row_count": total_row_count,
        "sheets": sheets,
        "sheet_details": sheet_details,
    }


def load_serenity_aistocks_workbook() -> dict[str, Any]:
    payload = _load_workbook_payload()
    return {
        "workbook_name": payload["workbook_name"],
        "sheet_count": payload["sheet_count"],
        "total_row_count": payload["total_row_count"],
        "sheets": payload["sheets"],
    }


def get_serenity_aistocks_sheet(sheet_slug: str) -> dict[str, Any] | None:
    payload = _load_workbook_payload()
    detail = payload["sheet_details"].get(sheet_slug)
    if not detail:
        return None
    hydrated_detail = copy.deepcopy(detail)
    hydrated_rows = _hydrate_sheet_rows_with_db_prices(detail.get("rows") or [])
    hydrated_detail["rows"] = _hydrate_sheet_rows_with_recent_three_buy(hydrated_rows)
    return hydrated_detail


def fetch_serenity_aistocks_prices(items: list[dict[str, Any]] | None) -> dict[str, list[dict[str, str]]]:
    query_items = _build_db_query_items(items)
    price_map = _build_db_price_map(query_items)
    quotes: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    for item in query_items:
        row_id = _normalize_text(item.get("row_id"))
        market = _normalize_text(item.get("market")).lower()
        code = _normalize_quote_code(market, item.get("code"))
        symbol = _normalize_text(item.get("symbol")) or code
        matched = price_map.get((market, code))
        if not matched:
            unsupported.append({"row_id": row_id, "status": "pending", "symbol": symbol})
            continue
        status = _normalize_text(matched.get("status")) or "ok"
        if status == "ok":
            quotes.append(
                {
                    "row_id": row_id,
                    "market": market,
                    "code": code,
                    "price_text": _normalize_text(matched.get("price_text")) or _DEFAULT_PRICE_TEXT,
                    "rate_text": _normalize_text(matched.get("rate_text")) or "--",
                    "status": status,
                    "updated_at_text": _normalize_text(matched.get("updated_at_text")),
                }
            )
        else:
            unsupported.append({"row_id": row_id, "status": status, "symbol": symbol})

    return {"quotes": quotes, "unsupported": unsupported}


def _load_recent_three_buy_markers(
    market: str, code: str, frequency: str = "D"
) -> list[dict[str, Any]]:
    ex = get_exchange(Market(market))
    klines = ex.klines(code, frequency, args={"fq": ""})
    cl_config = query_cl_chart_config(market, code)
    cl_config = apply_lite_chart_config_override(cl_config, lite_chart=True)
    cl_config["enable_kchart_low_to_high"] = "0"
    cd = web_batch_get_cl_datas(market, code, {frequency: klines}, cl_config)[0]
    chart_data = cl_data_to_tv_chart(cd, cl_config)
    return chart_data.get("mmds") or []


def _find_recent_three_buy_marker(mmds: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    normalized_markers = list(mmds or [])
    for preferred_prefix in ("BI:", ""):
        for marker in reversed(normalized_markers):
            text = _normalize_text(marker.get("text")).upper()
            if preferred_prefix and not text.startswith(preferred_prefix):
                continue
            if "3B" not in text and "L3B" not in text:
                continue
            points = marker.get("points") or {}
            timestamp = points.get("time")
            if timestamp is None:
                continue
            return {
                "timestamp": int(timestamp),
                "text": text,
            }
    return None


def fetch_serenity_aistocks_recent_three_buy_times(
    items: list[dict[str, Any]] | None,
) -> dict[str, list[dict[str, str]]]:
    hits: list[dict[str, str]] = []
    misses: list[dict[str, str]] = []
    rows_to_replace: list[dict[str, Any]] = []
    scan_time = datetime.datetime.now()
    for raw_item in items or []:
        row_id = _normalize_text(raw_item.get("row_id"))
        market = _normalize_text(raw_item.get("market")).lower()
        code = _normalize_quote_code(market, raw_item.get("code"))
        symbol = _normalize_text(raw_item.get("symbol")) or code
        if not market or not code:
            misses.append(
                {
                    "row_id": row_id,
                    "symbol": symbol,
                    "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                    "status": "unsupported",
                }
            )
            continue
        item = {
            "row_id": row_id,
            "market": market,
            "code": code,
            "symbol": symbol,
        }
        row_id = _normalize_text(item.get("row_id"))
        market = _normalize_text(item.get("market")).lower()
        code = _normalize_quote_code(market, item.get("code"))
        symbol = _normalize_text(item.get("symbol")) or code
        try:
            mmds = _load_recent_three_buy_markers(market, code, frequency="d")
            marker = _find_recent_three_buy_marker(mmds)
        except Exception:
            miss_payload = {
                "row_id": row_id,
                "symbol": symbol,
                "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "status": "error",
            }
            misses.append(miss_payload)
            rows_to_replace.append(
                {
                    "market": market,
                    "code": code,
                    "symbol": symbol,
                    "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                    "label": "扫描异常",
                    "status": "error",
                    "source": "serenity_aistocks_manual_scan",
                    "scanned_at": scan_time,
                    "updated_at": scan_time,
                }
            )
            continue
        if not marker:
            miss_payload = {
                "row_id": row_id,
                "symbol": symbol,
                "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "status": "not_found",
            }
            misses.append(miss_payload)
            rows_to_replace.append(
                {
                    "market": market,
                    "code": code,
                    "symbol": symbol,
                    "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                    "label": "未找到 3买",
                    "status": "not_found",
                    "source": "serenity_aistocks_manual_scan",
                    "scanned_at": scan_time,
                    "updated_at": scan_time,
                }
            )
            continue
        recent_three_buy_time_text = _format_timestamp_to_date_text(marker.get("timestamp"))
        try:
            recent_three_buy_time = datetime.datetime.fromtimestamp(
                int(marker.get("timestamp"))
            )
        except (TypeError, ValueError, OSError):
            recent_three_buy_time = None
        hit_payload = {
            "row_id": row_id,
            "symbol": symbol,
            "recent_three_buy_time_text": recent_three_buy_time_text,
            "status": "ok",
            "label": "最近 3买",
        }
        hits.append(hit_payload)
        rows_to_replace.append(
            {
                "market": market,
                "code": code,
                "symbol": symbol,
                "recent_three_buy_time": recent_three_buy_time,
                "recent_three_buy_time_text": recent_three_buy_time_text,
                "label": "最近 3买",
                "status": "ok",
                "source": "serenity_aistocks_manual_scan",
                "scanned_at": scan_time,
                "updated_at": scan_time,
            }
        )
    replace_method = getattr(db, "serenity_aistocks_recent_three_buy_replace", None)
    if replace_method is not None and rows_to_replace:
        replace_method(rows_to_replace)
    return {"hits": hits, "misses": misses}


def collect_serenity_aistocks_quote_items() -> list[dict[str, str]]:
    payload = _load_workbook_payload()
    unique_items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for detail in payload.get("sheet_details", {}).values():
        if not isinstance(detail, dict) or "rows" not in detail:
            continue
        for row in detail.get("rows") or []:
            quote_target = row.get("quote_target") or {}
            if quote_target.get("status") != "ok":
                continue
            market = _normalize_text(quote_target.get("market")).lower()
            code = _normalize_text(quote_target.get("normalized_code"))
            if not market or not code or (market, code) in seen:
                continue
            seen.add((market, code))
            unique_items.append(
                {
                    "market": market,
                    "code": code,
                    "symbol": _normalize_text(quote_target.get("symbol")) or code,
                }
            )
    return unique_items


def sync_serenity_aistocks_latest_prices(db_instance=None) -> dict[str, Any]:
    db_instance = db_instance or db
    items = collect_serenity_aistocks_quote_items()
    grouped_codes: dict[str, list[str]] = {}
    symbol_map: dict[tuple[str, str], str] = {}
    for item in items:
        market = _normalize_text(item.get("market")).lower()
        code = _normalize_quote_code(market, item.get("code"))
        if not market or not code:
            continue
        grouped_codes.setdefault(market, [])
        if code not in grouped_codes[market]:
            grouped_codes[market].append(code)
        symbol_map[(market, code)] = _normalize_text(item.get("symbol")) or code

    run_at = datetime.datetime.now()
    rows_to_replace: list[dict[str, Any]] = []
    success_count = 0
    unsupported_count = 0
    error_count = 0

    for market, codes in grouped_codes.items():
        snapshots: dict[str, Any] = {}
        market_error = False
        try:
            ex = get_exchange(Market(market))
            snapshots = fetch_tick_snapshots(ex, codes)
        except Exception:
            market_error = True

        for code in codes:
            snapshot = snapshots.get(code) if not market_error else None
            if snapshot:
                success_count += 1
                rows_to_replace.append(
                    {
                        "market": market,
                        "code": code,
                        "symbol": symbol_map.get((market, code), code),
                        "price": snapshot.get("price"),
                        "rate": snapshot.get("rate"),
                        "price_text": _format_price(snapshot.get("price")),
                        "rate_text": _format_percent(snapshot.get("rate")),
                        "status": "ok",
                        "source": "serenity_aistocks_scheduler",
                        "fetched_at": run_at,
                        "updated_at": run_at,
                    }
                )
                continue

            status = "error" if market_error else "unsupported"
            if status == "error":
                error_count += 1
            else:
                unsupported_count += 1
            rows_to_replace.append(
                {
                    "market": market,
                    "code": code,
                    "symbol": symbol_map.get((market, code), code),
                    "price": None,
                    "rate": None,
                    "price_text": _UNSUPPORTED_PRICE_TEXT if status == "unsupported" else "等待后台同步",
                    "rate_text": "--",
                    "status": status,
                    "source": "serenity_aistocks_scheduler",
                    "fetched_at": run_at,
                    "updated_at": run_at,
                }
            )

    if rows_to_replace:
        db_instance.serenity_aistocks_latest_prices_replace(rows_to_replace)

    return {
        "run_at": run_at.isoformat(),
        "total_candidates": len(items),
        "success_count": success_count,
        "unsupported_count": unsupported_count,
        "error_count": error_count,
    }


def _build_sync_status_payload(raw_status: dict[str, Any] | None = None) -> dict[str, Any]:
    status = dict(raw_status or {})
    running = bool(status.get("running", False))
    last_error = _normalize_text(status.get("last_error"))
    if last_error:
        status_label = "异常"
    elif running:
        status_label = "运行中"
    else:
        status_label = "未启动"
    return {
        "running": running,
        "interval_seconds": int(status.get("interval_seconds") or 60),
        "last_run_at": _normalize_text(status.get("last_run_at")),
        "last_run_at_text": _format_datetime_text(status.get("last_run_at")),
        "last_success_count": int(status.get("last_success_count") or 0),
        "last_unsupported_count": int(status.get("last_unsupported_count") or 0),
        "last_error_count": int(status.get("last_error_count") or 0),
        "last_total_candidates": int(status.get("last_total_candidates") or 0),
        "last_error": last_error,
        "status_label": status_label,
    }


def _resolve_serenity_aistocks_page_context(
    status_provider, sheet_slug: str | None = None
) -> dict[str, Any] | None:
    workbook = load_serenity_aistocks_workbook()
    sheets = workbook.get("sheets") or []
    sync_status = _build_sync_status_payload(status_provider())
    if not sheets:
        return {
            "workbook": workbook,
            "selected_sheet": None,
            "selected_sheet_slug": "",
            "selected_sheet_summary": None,
            "sheet_slugs": [],
            "sync_status": sync_status,
        }

    resolved_sheet_slug = _normalize_text(sheet_slug) or _normalize_text(sheets[0].get("sheet_slug"))
    selected_sheet = get_serenity_aistocks_sheet(resolved_sheet_slug)
    if not selected_sheet:
        return None

    selected_sheet_summary = next(
        (sheet for sheet in sheets if _normalize_text(sheet.get("sheet_slug")) == resolved_sheet_slug),
        None,
    )
    return {
        "workbook": workbook,
        "selected_sheet": selected_sheet,
        "selected_sheet_slug": resolved_sheet_slug,
        "selected_sheet_summary": selected_sheet_summary,
        "sheet_slugs": [_normalize_text(sheet.get("sheet_slug")) for sheet in sheets if sheet.get("sheet_slug")],
        "sync_status": sync_status,
    }


def register_serenity_aistocks_routes(app, status_provider=None) -> None:
    status_provider = status_provider or (lambda: {})

    @app.route("/serenity/aistocks")
    @login_required
    def serenity_aistocks_index():
        context = _resolve_serenity_aistocks_page_context(status_provider=status_provider)
        return render_template("serenity_aistocks_index.html", **(context or {}))

    @app.route("/serenity/aistocks/<sheet_slug>")
    @login_required
    def serenity_aistocks_sheet_detail(sheet_slug: str):
        context = _resolve_serenity_aistocks_page_context(
            sheet_slug=sheet_slug, status_provider=status_provider
        )
        if not context:
            abort(404)
        return render_template("serenity_aistocks_index.html", **context)

    @app.route("/serenity/aistocks/prices", methods=["POST"])
    @login_required
    def serenity_aistocks_prices():
        payload = request.get_json(silent=True) or {}
        return jsonify(fetch_serenity_aistocks_prices(payload.get("items") or []))

    @app.route("/serenity/aistocks/status")
    @login_required
    def serenity_aistocks_status():
        return jsonify(_build_sync_status_payload(status_provider()))

    @app.route("/serenity/aistocks/recent-three-buy-times", methods=["POST"])
    @login_required
    def serenity_aistocks_recent_three_buy_times():
        payload = request.get_json(silent=True) or {}
        return jsonify(
            fetch_serenity_aistocks_recent_three_buy_times(payload.get("items") or [])
        )
