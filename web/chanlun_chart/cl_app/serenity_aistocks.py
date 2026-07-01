from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import datetime
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from typing import Any
import uuid

import pandas as pd
import pinyin
from flask import abort, jsonify, render_template, request
from flask_login import login_required

from chanlun import cl
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
from .a_share_stock_analysis import build_stock_analysis_detail_url
from . import serenity_aistocks_serenity_fit as _serenity_fit
from .serenity_aistocks_serenity_fit import build_serenity_aistock_fit_view
from .tv_chart_request_mode import apply_lite_chart_config_override


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AISTOCKS_XLSX_PATH = _PROJECT_ROOT / "serenity-aleabitoreddit-main" / "aistocks.xlsx"
_DEFAULT_PRICE_TEXT = "--"
_UNSUPPORTED_PRICE_TEXT = "价格不可用"
_DEFAULT_RECENT_THREE_BUY_TIME_TEXT = "--"
_DEFAULT_CUSTOM_THEME_COLUMNS = ["代码", "名称", "核心概念 / 备注", "价格"]
_AISTOCKS_SCAN_TASKS: dict[str, dict[str, Any]] = {}
_AISTOCKS_ACTIVE_SCAN_TASKS: dict[str, dict[str, Any]] = {}
_AISTOCKS_SCAN_TASK_LOCK = threading.Lock()
_AISTOCKS_SCAN_TASK_KEEP_LIMIT = 64
_AISTOCKS_SCAN_TASK_EXPIRE_SECONDS = 30 * 60
_AISTOCKS_SCAN_TASK_STALE_SECONDS = 10 * 60
_AISTOCKS_SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="serenity-aistocks-scan")
_KNOWN_A_SHARE_SYMBOL_CORRECTIONS = {
    "国瓷材料": "sz300285",
    "德福科技": "sz301511",
}


def _aistocks_scan_task_cache_key(task_id: str) -> str:
    return f"serenity_aistocks_scan_task:{_normalize_text(task_id)}"


def _aistocks_active_scan_task_cache_key(sheet_slug: str, task_type: str) -> str:
    return f"serenity_aistocks_active_scan_task:{_normalize_text(sheet_slug)}:{_normalize_text(task_type)}"


def _trim_aistocks_scan_tasks() -> None:
    ordered_ids = sorted(
        _AISTOCKS_SCAN_TASKS.keys(),
        key=lambda task_id: _AISTOCKS_SCAN_TASKS[task_id].get("updated_at", ""),
    )
    for task_id in ordered_ids[:-_AISTOCKS_SCAN_TASK_KEEP_LIMIT]:
        _AISTOCKS_SCAN_TASKS.pop(task_id, None)


def _save_aistocks_scan_task_to_cache(task_id: str, task: dict[str, Any]) -> None:
    cache_set = getattr(db, "cache_set", None)
    if cache_set is None:
        return
    try:
        cache_set(
            _aistocks_scan_task_cache_key(task_id),
            task,
            expire=int(time.time()) + _AISTOCKS_SCAN_TASK_EXPIRE_SECONDS,
        )
    except Exception:
        return


def _set_active_aistocks_scan_task(
    sheet_slug: str, task_type: str, task_snapshot: dict[str, Any]
) -> None:
    normalized_sheet_slug = _normalize_text(sheet_slug)
    normalized_task_type = _normalize_text(task_type)
    if not normalized_sheet_slug or not normalized_task_type:
        return
    payload = copy.deepcopy(task_snapshot)
    payload["sheet_slug"] = normalized_sheet_slug
    payload["task_type"] = normalized_task_type
    cache_key = _aistocks_active_scan_task_cache_key(normalized_sheet_slug, normalized_task_type)
    with _AISTOCKS_SCAN_TASK_LOCK:
        _AISTOCKS_ACTIVE_SCAN_TASKS[cache_key] = copy.deepcopy(payload)
    cache_set = getattr(db, "cache_set", None)
    if cache_set is None:
        return
    try:
        cache_set(
            cache_key,
            payload,
            expire=int(time.time()) + _AISTOCKS_SCAN_TASK_EXPIRE_SECONDS,
        )
    except Exception:
        return


def _get_active_aistocks_scan_task(
    sheet_slug: str, task_type: str
) -> dict[str, Any] | None:
    normalized_sheet_slug = _normalize_text(sheet_slug)
    normalized_task_type = _normalize_text(task_type)
    if not normalized_sheet_slug or not normalized_task_type:
        return None
    cache_key = _aistocks_active_scan_task_cache_key(normalized_sheet_slug, normalized_task_type)
    with _AISTOCKS_SCAN_TASK_LOCK:
        task = copy.deepcopy(_AISTOCKS_ACTIVE_SCAN_TASKS.get(cache_key))
    if not task:
        cache_get = getattr(db, "cache_get", None)
        if cache_get is None:
            return None
        try:
            task = cache_get(cache_key)
        except Exception:
            task = None
        if task:
            with _AISTOCKS_SCAN_TASK_LOCK:
                _AISTOCKS_ACTIVE_SCAN_TASKS[cache_key] = copy.deepcopy(task)
    if not task:
        return None
    task_snapshot = _get_aistocks_scan_task(_normalize_text(task.get("task_id")))
    if not task_snapshot:
        _clear_active_aistocks_scan_task(
            normalized_sheet_slug,
            normalized_task_type,
            _normalize_text(task.get("task_id")),
        )
        return None
    if _is_aistocks_scan_task_stale(task_snapshot):
        task_snapshot = _set_aistocks_scan_task(
            _normalize_text(task_snapshot.get("task_id")),
            state="failed",
            message="扫描任务超时未更新，已自动结束",
            error="stale_task_timeout",
            finished_at=datetime.datetime.now().isoformat(),
            progress=100,
        )
        _clear_active_aistocks_scan_task(
            normalized_sheet_slug,
            normalized_task_type,
            _normalize_text(task_snapshot.get("task_id")),
        )
        return None
    state = _normalize_text(task_snapshot.get("state"))
    if state not in {"pending", "running"}:
        _clear_active_aistocks_scan_task(
            normalized_sheet_slug,
            normalized_task_type,
            _normalize_text(task_snapshot.get("task_id")),
        )
        return None
    return task_snapshot


def _clear_active_aistocks_scan_task(sheet_slug: str, task_type: str, task_id: str) -> None:
    normalized_sheet_slug = _normalize_text(sheet_slug)
    normalized_task_type = _normalize_text(task_type)
    if not normalized_sheet_slug or not normalized_task_type:
        return
    cache_key = _aistocks_active_scan_task_cache_key(normalized_sheet_slug, normalized_task_type)
    with _AISTOCKS_SCAN_TASK_LOCK:
        active_task = copy.deepcopy(_AISTOCKS_ACTIVE_SCAN_TASKS.get(cache_key))
        if active_task and task_id and _normalize_text(active_task.get("task_id")) not in {"", _normalize_text(task_id)}:
            return
        _AISTOCKS_ACTIVE_SCAN_TASKS.pop(cache_key, None)
    cache_del = getattr(db, "cache_del", None)
    if cache_del is None:
        return
    try:
        cache_del(cache_key)
    except Exception:
        return


def _set_aistocks_scan_task(task_id: str, **updates: Any) -> dict[str, Any]:
    with _AISTOCKS_SCAN_TASK_LOCK:
        task = _AISTOCKS_SCAN_TASKS.setdefault(task_id, {})
        task.setdefault("task_id", task_id)
        task.update(updates)
        task["updated_at"] = datetime.datetime.now().isoformat()
        _trim_aistocks_scan_tasks()
        task_snapshot = copy.deepcopy(task)
    _save_aistocks_scan_task_to_cache(task_id, task_snapshot)
    return task_snapshot


def _is_aistocks_scan_task_stale(task_snapshot: dict[str, Any]) -> bool:
    state = _normalize_text(task_snapshot.get("state"))
    if state not in {"pending", "running"}:
        return False
    updated_at = _normalize_text(task_snapshot.get("updated_at"))
    if not updated_at:
        return False
    try:
        updated_at_dt = datetime.datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    return (datetime.datetime.now() - updated_at_dt).total_seconds() > _AISTOCKS_SCAN_TASK_STALE_SECONDS


def _normalize_aistocks_scan_task_snapshot(task_snapshot: dict[str, Any]) -> dict[str, Any]:
    state = _normalize_text(task_snapshot.get("state"))
    if state not in {"pending", "running"}:
        return task_snapshot

    failure_error = ""
    failure_message = ""
    if _is_aistocks_scan_task_stale(task_snapshot):
        failure_error = "stale_task_timeout"
        failure_message = "扫描任务超时未更新，已自动结束"
    elif _normalize_text(task_snapshot.get("finished_at")) or _normalize_text(
        task_snapshot.get("error")
    ):
        failure_error = _normalize_text(task_snapshot.get("error")) or "invalid_task_state"
        failure_message = _normalize_text(task_snapshot.get("message")) or "扫描任务状态异常，已自动结束"

    if not failure_error:
        return task_snapshot

    task_id = _normalize_text(task_snapshot.get("task_id"))
    if not task_id:
        return task_snapshot

    normalized_snapshot = _set_aistocks_scan_task(
        task_id,
        state="failed",
        message=failure_message,
        error=failure_error,
        finished_at=_normalize_text(task_snapshot.get("finished_at"))
        or datetime.datetime.now().isoformat(),
        progress=100,
    )
    _clear_active_aistocks_scan_task(
        _normalize_text(task_snapshot.get("sheet_slug")),
        _normalize_text(task_snapshot.get("task_type")),
        task_id,
    )
    return normalized_snapshot


def _get_aistocks_scan_task(task_id: str) -> dict[str, Any] | None:
    task_snapshot = None
    with _AISTOCKS_SCAN_TASK_LOCK:
        task = _AISTOCKS_SCAN_TASKS.get(task_id)
        if task:
            task_snapshot = copy.deepcopy(task)
    if task_snapshot:
        return _normalize_aistocks_scan_task_snapshot(task_snapshot)
    cache_get = getattr(db, "cache_get", None)
    if cache_get is None:
        return None
    try:
        cached_task = cache_get(_aistocks_scan_task_cache_key(task_id))
    except Exception:
        cached_task = None
    if not cached_task:
        return None
    with _AISTOCKS_SCAN_TASK_LOCK:
        _AISTOCKS_SCAN_TASKS[task_id] = copy.deepcopy(cached_task)
    return _normalize_aistocks_scan_task_snapshot(copy.deepcopy(cached_task))


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


def _build_pinyin_initials(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    initials: list[str] = []
    for char in normalized:
        initial = _normalize_text(pinyin.get_initial(char))
        if initial:
            initials.append(initial[0])
    return "".join(initials).lower()


def _build_stock_filter_key(cells: dict[str, Any], quote_target: dict[str, Any]) -> str:
    parts = [
        _normalize_text(cells.get("名称")),
        _normalize_text(cells.get("代码")),
        _normalize_text(quote_target.get("symbol")),
        _normalize_text(quote_target.get("code")),
    ]
    name = _normalize_text(cells.get("名称"))
    if name:
        parts.append(_build_pinyin_initials(name))
    return " ".join(part.lower() for part in parts if part).strip()


@lru_cache(maxsize=1)
def _load_a_share_symbol_to_names_map() -> dict[str, str]:
    try:
        ex = get_exchange(Market.A)
        all_stocks = ex.all_stocks() or []
    except Exception:
        return {}

    symbol_to_name: dict[str, str] = {}
    for stock in all_stocks:
        symbol = _normalize_a_share_excel_symbol(stock.get("code"))
        name = _normalize_text(stock.get("name"))
        if not symbol or not name:
            continue
        symbol_to_name[symbol] = name
    return symbol_to_name


def _resolve_custom_stock_info_from_code(code: str) -> dict[str, str] | None:
    normalized_symbol = _normalize_a_share_excel_symbol(code)
    if not re.fullmatch(r"(sh|sz|bj)\d{6}", normalized_symbol, flags=re.IGNORECASE):
        return None

    normalized_code = _normalize_quote_code("a", normalized_symbol)
    stock_name = _load_a_share_symbol_to_names_map().get(normalized_symbol, "")
    try:
        ex = get_exchange(Market.A)
    except Exception:
        ex = None

    if ex is not None:
        for candidate in (normalized_code, normalized_symbol.upper(), normalized_symbol[2:]):
            try:
                stock_info = ex.stock_info(candidate) or {}
            except Exception:
                continue
            matched_name = _normalize_text(stock_info.get("name"))
            if matched_name:
                stock_name = matched_name
                break

    if not stock_name:
        return None

    return {
        "market": "a",
        "code": normalized_code,
        "symbol": normalized_symbol,
        "stock_name": stock_name,
    }


def _load_serenity_aistocks_custom_entries() -> list[dict[str, str]]:
    if not hasattr(db, "serenity_aistocks_custom_entries_query"):
        return []
    try:
        rows = db.serenity_aistocks_custom_entries_query() or []
    except Exception:
        return []

    entries: list[dict[str, str]] = []
    for row in rows:
        theme_name = _normalize_text(row.get("theme_name"))
        theme_slug = _normalize_text(row.get("theme_slug")) or _slugify_sheet_name(theme_name)
        market = _normalize_text(row.get("market")).lower() or "a"
        if market != "a":
            continue
        symbol = _normalize_a_share_excel_symbol(row.get("symbol") or row.get("code"))
        normalized_code = _normalize_quote_code("a", symbol)
        stock_name = _normalize_text(row.get("stock_name"))
        notes = _normalize_text(row.get("notes"))
        if not theme_name or not theme_slug or not symbol or not normalized_code:
            continue
        entries.append(
            {
                "theme_name": theme_name,
                "theme_slug": theme_slug,
                "market": market,
                "code": normalized_code,
                "symbol": symbol,
                "stock_name": stock_name or _load_a_share_symbol_to_names_map().get(symbol, symbol.upper()),
                "notes": notes,
            }
        )
    return entries


def _build_custom_row(
    theme_name: str,
    theme_slug: str,
    base_columns: list[str],
    entry: dict[str, str],
    row_index: int,
) -> dict[str, Any]:
    columns_without_price = [column for column in base_columns if column != "价格"]
    cells = {column: "" for column in columns_without_price}
    for column in columns_without_price:
        if column == "所属分类":
            cells[column] = theme_name
        elif column == "代码":
            cells[column] = entry.get("symbol", "")
        elif column == "名称":
            cells[column] = entry.get("stock_name", "")
        elif column == "核心概念 / 备注":
            cells[column] = entry.get("notes", "")

    quote_target = {
        "market": entry.get("market", "a"),
        "code": entry.get("symbol", ""),
        "normalized_code": entry.get("code", ""),
        "symbol": entry.get("symbol", ""),
        "name": entry.get("stock_name", ""),
        "status": "ok",
    }
    chart_view = _build_row_chart_view(quote_target, cells)
    recent_three_buy_view = _build_recent_three_buy_view()
    recent_beichi_view = _build_recent_beichi_view()
    row_id = f"{theme_slug}-custom-{row_index}"
    serenity_fit_view = build_serenity_aistock_fit_view(
        row_id=row_id,
        sheet_slug=theme_slug,
        cells=cells,
        quote_target=quote_target,
    )
    return {
        "row_id": row_id,
        "cells": cells,
        "quote_target": quote_target,
        "price_text": _DEFAULT_PRICE_TEXT,
        "rate_text": "--",
        "price_status": "pending",
        "updated_at_text": "",
        "chart_url": chart_view["chart_url"],
        "chart_unavailable_reason": chart_view["chart_unavailable_reason"],
        "chart_frequency_label": chart_view["chart_frequency_label"],
        "chart_title": chart_view["chart_title"],
        "stock_filter_key": _build_stock_filter_key(cells, quote_target),
        "recent_three_buy_time_text": recent_three_buy_view["recent_three_buy_time_text"],
        "recent_three_buy_label": recent_three_buy_view["recent_three_buy_label"],
        "recent_three_buy_status": recent_three_buy_view["recent_three_buy_status"],
        "recent_three_buy_updated_at_text": recent_three_buy_view["recent_three_buy_updated_at_text"],
        "recent_beichi_time_text": recent_beichi_view["recent_beichi_time_text"],
        "current_beichi_status_text": recent_beichi_view["current_beichi_status_text"],
        "current_beichi_types_text": recent_beichi_view["current_beichi_types_text"],
        "recent_beichi_types_text": recent_beichi_view["recent_beichi_types_text"],
        "recent_beichi_status": recent_beichi_view["recent_beichi_status"],
        "recent_beichi_updated_at_text": recent_beichi_view["recent_beichi_updated_at_text"],
        "serenity_fit_status": serenity_fit_view.get("fit_status", "watch"),
        "serenity_fit_label": serenity_fit_view.get("fit_label", "待观察"),
        "serenity_fit_reason_short": serenity_fit_view.get("fit_reason_short", ""),
        "serenity_fit_reason_detail": serenity_fit_view.get("fit_reason_detail", ""),
        "serenity_fit_detail_url": _build_serenity_aistock_detail_url(
            row_id=row_id, cells=cells, quote_target=quote_target
        ),
        "is_custom_entry": True,
        "custom_theme_slug": theme_slug,
        "custom_market": entry.get("market", "a"),
        "custom_code": entry.get("code", ""),
    }


def _merge_workbook_with_custom_entries(workbook_payload: dict[str, Any]) -> dict[str, Any]:
    merged_payload = copy.deepcopy(workbook_payload)
    entries = _load_serenity_aistocks_custom_entries()
    if not entries:
        return merged_payload

    grouped_entries: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        grouped_entries.setdefault(entry["theme_slug"], []).append(entry)

    sheets = merged_payload.get("sheets") or []
    sheet_details = merged_payload.get("sheet_details") or {}
    sheet_index_map = {
        _normalize_text(sheet.get("sheet_slug")): index for index, sheet in enumerate(sheets)
    }
    new_summaries: list[dict[str, Any]] = []

    for theme_slug, theme_entries in grouped_entries.items():
        detail = sheet_details.get(theme_slug)
        if detail:
            theme_name = detail.get("sheet_name") or theme_entries[0].get("theme_name") or theme_slug
            columns = list(detail.get("columns") or _DEFAULT_CUSTOM_THEME_COLUMNS)
            rows = list(detail.get("rows") or [])
        else:
            theme_name = theme_entries[0].get("theme_name") or theme_slug
            columns = list(_DEFAULT_CUSTOM_THEME_COLUMNS)
            rows = []

        custom_rows = [
            _build_custom_row(theme_name, theme_slug, columns, entry, row_index)
            for row_index, entry in enumerate(theme_entries, start=1)
        ]
        detail = {
            "sheet_name": theme_name,
            "sheet_slug": theme_slug,
            "columns": columns,
            "rows": rows + custom_rows,
            "row_count": len(rows) + len(custom_rows),
        }
        sheet_details[theme_slug] = detail
        sheet_details[theme_name] = detail
        summary = _build_sheet_summary(theme_name, columns, detail["rows"])
        if theme_slug in sheet_index_map:
            sheets[sheet_index_map[theme_slug]] = summary
        else:
            new_summaries.append(summary)

    if new_summaries:
        sheets.extend(sorted(new_summaries, key=lambda item: _normalize_text(item.get("sheet_name"))))

    merged_payload["sheets"] = sheets
    merged_payload["sheet_details"] = sheet_details
    merged_payload["sheet_count"] = len(sheets)
    merged_payload["total_row_count"] = sum(int(sheet.get("row_count") or 0) for sheet in sheets)
    return merged_payload


def _search_serenity_aistocks_symbols(
    query: str, exchange: str, limit: int = 10
) -> list[dict[str, str]]:
    normalized_query = _normalize_text(query).lower()
    normalized_exchange = _normalize_text(exchange).lower() or "a"
    if not normalized_query:
        return []
    try:
        ex = get_exchange(Market(normalized_exchange))
        all_stocks = ex.all_stocks() or []
    except Exception:
        return []

    matched_stocks: list[dict[str, Any]] = []
    for stock in all_stocks:
        code = _normalize_text(stock.get("code"))
        name = _normalize_text(stock.get("name"))
        if not code:
            continue
        if normalized_exchange in {"currency", "currency_spot"}:
            matched = normalized_query in code.lower()
        else:
            matched = (
                normalized_query in code.lower()
                or normalized_query in name.lower()
                or normalized_query in _build_pinyin_initials(name)
            )
        if matched:
            matched_stocks.append(stock)

    results: list[dict[str, str]] = []
    for stock in matched_stocks[: max(limit, 1)]:
        results.append(
            {
                "symbol": _normalize_text(stock.get("code")),
                "description": _normalize_text(stock.get("name")),
                "exchange": normalized_exchange,
            }
        )
    return results


def _format_timestamp_to_date_text(value: Any) -> str:
    try:
        timestamp = int(float(value))
    except (TypeError, ValueError):
        return _DEFAULT_RECENT_THREE_BUY_TIME_TEXT
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _format_date_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    normalized = _normalize_text(value)
    if not normalized:
        return ""
    try:
        return datetime.datetime.fromisoformat(normalized).strftime("%Y-%m-%d")
    except ValueError:
        return normalized[:10]


def _normalize_kline_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    normalized = _normalize_text(value)
    if not normalized:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(normalized[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _resolve_kline_date_column(klines: Any) -> str:
    if not isinstance(klines, pd.DataFrame):
        return ""
    if "date" in klines.columns:
        return "date"
    if "datetime" in klines.columns:
        return "datetime"
    return ""


def _extract_ordered_kline_dates(klines: Any) -> list[datetime.date]:
    date_column = _resolve_kline_date_column(klines)
    if not date_column:
        return []
    ordered_dates: list[datetime.date] = []
    seen: set[datetime.date] = set()
    for value in klines[date_column].tolist():
        normalized = _normalize_kline_date(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        ordered_dates.append(normalized)
    return ordered_dates


def _slice_klines_to_end_date(klines: Any, end_date: datetime.date) -> Any:
    if not isinstance(klines, pd.DataFrame):
        return klines
    date_column = _resolve_kline_date_column(klines)
    if not date_column:
        return klines.copy()
    normalized_dates = klines[date_column].apply(_normalize_kline_date)
    sliced = klines.loc[normalized_dates <= end_date].copy()
    return sliced.reset_index(drop=True)


def _build_three_buy_scan_history_text(history_rows: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for row in history_rows or []:
        scan_date = _format_date_text(row.get("scan_date"))
        three_buy_date = _format_date_text(row.get("three_buy_date")) or "未找到"
        if not scan_date:
            continue
        parts.append(f"{scan_date}=>{three_buy_date}")
    return " | ".join(parts)


def _build_three_buy_history_title(start_date_text: str, end_date_text: str, history_text: str) -> str:
    range_text = " ~ ".join(
        [text for text in [start_date_text, end_date_text] if _normalize_text(text)]
    )
    if range_text and history_text:
        return f"{range_text} | {history_text}"
    return range_text or history_text


def _normalize_beichi_types_text(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    parts = [segment.strip() for segment in text.split("/") if segment.strip()]
    return " / ".join(parts)


def _build_beichi_scan_history_text(history_rows: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for row in history_rows or []:
        scan_date = _format_date_text(row.get("scan_date"))
        beichi_date = _format_date_text(row.get("beichi_date"))
        types_text = _normalize_beichi_types_text(row.get("types_text"))
        if not scan_date:
            continue
        if beichi_date and types_text:
            parts.append(f"{scan_date}=>{types_text}@{beichi_date}")
        else:
            parts.append(f"{scan_date}=>无")
    return " | ".join(parts)


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


def _normalize_a_share_excel_symbol(value: str) -> str:
    normalized = _normalize_text(value).strip()
    if not normalized:
        return ""
    if "." in normalized:
        market, code = normalized.split(".", 1)
        market_prefix = market.lower()
        if market_prefix in {"sh", "sz", "bj"} and code:
            return f"{market_prefix}{code}"
    return _normalize_excel_symbol(normalized).lower()


@lru_cache(maxsize=1)
def _load_a_share_name_to_symbols_map() -> dict[str, list[str]]:
    try:
        ex = get_exchange(Market.A)
        all_stocks = ex.all_stocks() or []
    except Exception:
        return {}

    name_to_symbols: dict[str, set[str]] = {}
    for stock in all_stocks:
        name = _normalize_text(stock.get("name"))
        symbol = _normalize_a_share_excel_symbol(stock.get("code"))
        if not name or not symbol:
            continue
        name_to_symbols.setdefault(name, set()).add(symbol)

    return {
        name: sorted(symbols)
        for name, symbols in name_to_symbols.items()
        if symbols
    }


def _apply_known_symbol_corrections(cells: dict[str, Any]) -> dict[str, Any]:
    corrected_cells = dict(cells)
    name = _candidate_value(corrected_cells, ("名称", "name", "公司"))
    symbol = _candidate_value(
        corrected_cells, ("代码", "ticker", "symbol", "股票代码", "证券代码")
    )
    corrected_symbol = _KNOWN_A_SHARE_SYMBOL_CORRECTIONS.get(name)
    if not corrected_symbol and name:
        matched_symbols = _load_a_share_name_to_symbols_map().get(name) or []
        if len(matched_symbols) == 1:
            corrected_symbol = matched_symbols[0]
    if not corrected_symbol or _normalize_excel_symbol(symbol) == corrected_symbol:
        return corrected_cells

    for key, value in list(corrected_cells.items()):
        normalized_key = _normalize_text(key).lower()
        if any(keyword in normalized_key for keyword in ("代码", "ticker", "symbol", "股票代码", "证券代码")):
            corrected_cells[key] = corrected_symbol
            break
    return corrected_cells


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
        "recent_three_buy_scan_history_text": "",
        "recent_three_buy_scan_history_json": "[]",
        "recent_three_buy_scan_start_date_text": "",
        "recent_three_buy_scan_end_date_text": "",
        "recent_three_buy_history_title": "",
    }


def _build_recent_beichi_view() -> dict[str, str]:
    return {
        "recent_beichi_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "current_beichi_status_text": "当前无背驰",
        "current_beichi_types_text": "",
        "recent_beichi_types_text": "",
        "recent_beichi_status": "pending",
        "recent_beichi_updated_at_text": "",
        "recent_beichi_scan_history_text": "",
        "recent_beichi_scan_history_json": "[]",
        "recent_beichi_scan_start_date_text": "",
        "recent_beichi_scan_end_date_text": "",
        "recent_beichi_history_title": "",
    }


def _build_serenity_aistock_detail_url(
    row_id: str,
    cells: dict[str, Any] | None = None,
    quote_target: dict[str, Any] | None = None,
) -> str:
    resolved_cells = cells or {}
    resolved_quote_target = quote_target or {}
    display_name = _candidate_value(resolved_cells, ("名称", "name", "公司")) or _normalize_text(
        resolved_quote_target.get("name")
    )
    market_key = _normalize_text(resolved_quote_target.get("market")).lower()
    market_label = {
        "a": "A",
        "hk": "HK",
        "us": "US",
    }.get(market_key, market_key.upper())
    return build_stock_analysis_detail_url(
        entity_type="serenity_aistock",
        identifier=row_id,
        display_name=display_name,
        company_name=display_name,
        market=market_label,
        numeric_code=_normalize_text(resolved_quote_target.get("code")),
    )


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
        row["recent_three_buy_scan_history_text"] = _normalize_text(
            matched.get("recent_three_buy_scan_history_text")
        )
        row["recent_three_buy_scan_history_json"] = _normalize_text(
            matched.get("recent_three_buy_scan_history_json")
        ) or "[]"
        row["recent_three_buy_scan_start_date_text"] = _normalize_text(
            matched.get("recent_three_buy_scan_start_date_text")
        )
        row["recent_three_buy_scan_end_date_text"] = _normalize_text(
            matched.get("recent_three_buy_scan_end_date_text")
        )
        row["recent_three_buy_history_title"] = _build_three_buy_history_title(
            row["recent_three_buy_scan_start_date_text"],
            row["recent_three_buy_scan_end_date_text"],
            row["recent_three_buy_scan_history_text"],
        )
        row["recent_three_buy_updated_at_text"] = _normalize_text(
            matched.get("updated_at_text")
        )
    return hydrated_rows


def _build_db_recent_beichi_map(items: list[dict[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    query_items = _build_db_query_items(items)
    recent_beichi_map: dict[tuple[str, str], dict[str, Any]] = {}
    query_method = getattr(db, "serenity_aistocks_recent_beichi_query", None)
    if query_method is None:
        return recent_beichi_map
    for row in query_method(query_items):
        market = _normalize_text(row.get("market")).lower()
        code = _normalize_quote_code(market, row.get("code"))
        if market and code:
            recent_beichi_map[(market, code)] = row
    return recent_beichi_map


def _hydrate_sheet_rows_with_recent_beichi(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hydrated_rows = copy.deepcopy(rows)
    query_items = []
    for row in hydrated_rows:
        quote_target = row.get("quote_target") or {}
        if quote_target.get("status") != "ok":
            row["recent_beichi_updated_at_text"] = ""
            continue
        query_items.append(
            {
                "row_id": row.get("row_id"),
                "market": quote_target.get("market"),
                "code": quote_target.get("code"),
                "symbol": quote_target.get("symbol"),
            }
        )

    recent_beichi_map = _build_db_recent_beichi_map(query_items)
    for row in hydrated_rows:
        quote_target = row.get("quote_target") or {}
        normalized_code = _normalize_text(quote_target.get("normalized_code"))
        market = _normalize_text(quote_target.get("market")).lower()
        matched = recent_beichi_map.get((market, normalized_code))
        row["recent_beichi_updated_at_text"] = ""
        if not matched:
            continue
        row["recent_beichi_time_text"] = (
            _normalize_text(matched.get("recent_beichi_time_text"))
            or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT
        )
        row["current_beichi_status_text"] = (
            _normalize_text(matched.get("current_beichi_status_text")) or "当前无背驰"
        )
        row["current_beichi_types_text"] = _normalize_text(matched.get("current_beichi_types_text"))
        row["recent_beichi_types_text"] = _normalize_text(matched.get("recent_beichi_types_text"))
        row["recent_beichi_status"] = _normalize_text(matched.get("status")) or "pending"
        row["recent_beichi_scan_history_text"] = _normalize_text(
            matched.get("recent_beichi_scan_history_text")
        )
        row["recent_beichi_scan_history_json"] = _normalize_text(
            matched.get("recent_beichi_scan_history_json")
        ) or "[]"
        row["recent_beichi_scan_start_date_text"] = _normalize_text(
            matched.get("recent_beichi_scan_start_date_text")
        )
        row["recent_beichi_scan_end_date_text"] = _normalize_text(
            matched.get("recent_beichi_scan_end_date_text")
        )
        row["recent_beichi_history_title"] = _build_three_buy_history_title(
            row["recent_beichi_scan_start_date_text"],
            row["recent_beichi_scan_end_date_text"],
            row["recent_beichi_scan_history_text"],
        )
        row["recent_beichi_updated_at_text"] = _normalize_text(
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
        cells = _apply_known_symbol_corrections(cells)
        if not any(_normalize_text(value) for value in cells.values()):
            continue
        quote_target = _infer_row_quote_target(cells, headers)
        chart_view = _build_row_chart_view(quote_target, cells)
        recent_three_buy_view = _build_recent_three_buy_view()
        recent_beichi_view = _build_recent_beichi_view()
        row_id = f"{_slugify_sheet_name(sheet_name)}-{row_index}"
        serenity_fit_view = build_serenity_aistock_fit_view(
            row_id=row_id,
            sheet_slug=_slugify_sheet_name(sheet_name),
            cells=cells,
            quote_target=quote_target,
        )
        data_rows.append(
            {
                "row_id": row_id,
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
                "stock_filter_key": _build_stock_filter_key(cells, quote_target),
                "recent_three_buy_time_text": recent_three_buy_view["recent_three_buy_time_text"],
                "recent_three_buy_label": recent_three_buy_view["recent_three_buy_label"],
                "recent_three_buy_status": recent_three_buy_view["recent_three_buy_status"],
                "recent_three_buy_updated_at_text": recent_three_buy_view["recent_three_buy_updated_at_text"],
                "recent_beichi_time_text": recent_beichi_view["recent_beichi_time_text"],
                "current_beichi_status_text": recent_beichi_view["current_beichi_status_text"],
                "current_beichi_types_text": recent_beichi_view["current_beichi_types_text"],
                "recent_beichi_types_text": recent_beichi_view["recent_beichi_types_text"],
                "recent_beichi_status": recent_beichi_view["recent_beichi_status"],
                "recent_beichi_updated_at_text": recent_beichi_view["recent_beichi_updated_at_text"],
                "serenity_fit_status": serenity_fit_view.get("fit_status", "watch"),
                "serenity_fit_label": serenity_fit_view.get("fit_label", "待观察"),
                "serenity_fit_reason_short": serenity_fit_view.get("fit_reason_short", ""),
                "serenity_fit_reason_detail": serenity_fit_view.get("fit_reason_detail", ""),
                "serenity_fit_detail_url": _build_serenity_aistock_detail_url(
                    row_id=row_id, cells=cells, quote_target=quote_target
                ),
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
    payload = _merge_workbook_with_custom_entries(_load_workbook_payload())
    return {
        "workbook_name": payload["workbook_name"],
        "sheet_count": payload["sheet_count"],
        "total_row_count": payload["total_row_count"],
        "sheets": payload["sheets"],
    }


def get_serenity_aistocks_sheet(sheet_slug: str) -> dict[str, Any] | None:
    payload = _merge_workbook_with_custom_entries(_load_workbook_payload())
    detail = payload["sheet_details"].get(sheet_slug)
    if not detail:
        return None
    hydrated_detail = copy.deepcopy(detail)
    hydrated_rows = _hydrate_sheet_rows_with_db_prices(detail.get("rows") or [])
    hydrated_rows = _hydrate_sheet_rows_with_recent_three_buy(hydrated_rows)
    hydrated_detail["rows"] = _hydrate_sheet_rows_with_recent_beichi(hydrated_rows)
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


def _load_recent_three_buy_source_klines(market: str, code: str, frequency: str = "D") -> Any:
    ex = get_exchange(Market(market))
    return ex.klines(code, frequency, args={"fq": ""})


def _load_recent_beichi_source_klines(market: str, code: str, frequency: str = "D") -> Any:
    return _load_recent_three_buy_source_klines(market, code, frequency)


def _load_latest_daily_kline_date(market: str, code: str, frequency: str = "d") -> str:
    try:
        ex = get_exchange(Market(market))
        klines = ex.klines(code, frequency, args={"fq": "", "limit": 1})
    except Exception:
        return ""
    ordered_dates = _extract_ordered_kline_dates(klines)
    if not ordered_dates:
        return ""
    return _format_date_text(ordered_dates[-1])


def _build_three_buy_markers_from_klines(
    market: str, code: str, frequency: str, klines: Any
) -> list[dict[str, Any]]:
    cl_config = query_cl_chart_config(market, code)
    cl_config = apply_lite_chart_config_override(cl_config, lite_chart=True)
    cl_config["enable_kchart_low_to_high"] = "0"
    cd = web_batch_get_cl_datas(market, code, {frequency: klines}, cl_config)[0]
    chart_data = cl_data_to_tv_chart(cd, cl_config)
    return chart_data.get("mmds") or []


def _load_recent_three_buy_markers(
    market: str, code: str, frequency: str = "D"
) -> list[dict[str, Any]]:
    klines = _load_recent_three_buy_source_klines(market, code, frequency)
    return _build_three_buy_markers_from_klines(market, code, frequency, klines)


def _build_three_buy_markers_without_cache(
    market: str, code: str, frequency: str, klines: Any
) -> list[dict[str, Any]]:
    cl_config = query_cl_chart_config(market, code)
    cl_config = apply_lite_chart_config_override(cl_config, lite_chart=True)
    cl_config["enable_kchart_low_to_high"] = "0"
    cd = cl.CL(code, frequency, cl_config)
    cd.process_klines(klines.copy() if isinstance(klines, pd.DataFrame) else klines)
    chart_data = cl_data_to_tv_chart(cd, cl_config)
    if not chart_data:
        return []
    return chart_data.get("mmds") or []


def _build_beichi_markers_without_cache(
    market: str, code: str, frequency: str, klines: Any
) -> list[dict[str, Any]]:
    cl_config = query_cl_chart_config(market, code)
    cl_config = apply_lite_chart_config_override(cl_config, lite_chart=True)
    cl_config["enable_kchart_low_to_high"] = "0"
    cd = cl.CL(code, frequency, cl_config)
    cd.process_klines(klines.copy() if isinstance(klines, pd.DataFrame) else klines)
    chart_data = cl_data_to_tv_chart(cd, cl_config)
    if not chart_data:
        return []
    return chart_data.get("bcs") or []


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


def _find_recent_three_buy_marker_from_klines(
    market: str, code: str, frequency: str, klines: Any
) -> dict[str, Any] | None:
    return _find_recent_three_buy_marker(
        _build_three_buy_markers_without_cache(market, code, frequency, klines)
    )


def _find_recent_beichi_marker(bcs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    normalized_markers = list(bcs or [])
    for marker in reversed(normalized_markers):
        points = marker.get("points") or {}
        timestamp = points.get("time")
        if timestamp is None:
            continue
        types_text = _normalize_beichi_types_text(marker.get("text"))
        return {
            "timestamp": int(timestamp),
            "text": _normalize_text(marker.get("text")),
            "types_text": types_text,
            "date_text": _format_timestamp_to_date_text(timestamp),
        }
    return None


def _find_recent_beichi_marker_from_klines(
    market: str, code: str, frequency: str, klines: Any
) -> dict[str, Any] | None:
    return _find_recent_beichi_marker(
        _build_beichi_markers_without_cache(market, code, frequency, klines)
    )


def _scan_recent_three_buy_history(
    market: str, code: str, frequency: str = "d"
) -> dict[str, Any]:
    klines = _load_recent_three_buy_source_klines(market, code, frequency)
    ordered_dates = _extract_ordered_kline_dates(klines)
    if not ordered_dates:
        return {
            "recent_three_buy_time": None,
            "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
            "label": "未找到 3买",
            "history": [],
            "history_text": "",
            "history_json": "[]",
            "scan_start_date_text": "",
            "scan_end_date_text": "",
            "history_title": "",
        }

    if len(ordered_dates) >= 11:
        scan_start_date = ordered_dates[-11]
        scan_dates = ordered_dates[-10:]
    else:
        scan_start_date = ordered_dates[0]
        scan_dates = [ordered_dates[-1]]
    scan_end_date = scan_dates[-1]

    history_rows: list[dict[str, str]] = []
    latest_hit_date_text = ""
    latest_hit_timestamp: datetime.datetime | None = None
    for scan_date in scan_dates:
        marker = _find_recent_three_buy_marker_from_klines(
            market, code, frequency, _slice_klines_to_end_date(klines, scan_date)
        )
        three_buy_date_text = _format_timestamp_to_date_text(marker.get("timestamp")) if marker else ""
        history_rows.append(
            {
                "scan_date": _format_date_text(scan_date),
                "three_buy_date": three_buy_date_text,
                "label": "最近 3买" if three_buy_date_text else "未找到 3买",
            }
        )
        if three_buy_date_text:
            latest_hit_date_text = three_buy_date_text
            latest_hit_timestamp = datetime.datetime.strptime(
                three_buy_date_text, "%Y-%m-%d"
            )

    history_text = _build_three_buy_scan_history_text(history_rows)
    return {
        "recent_three_buy_time": latest_hit_timestamp,
        "recent_three_buy_time_text": latest_hit_date_text or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "label": "最近 3买" if latest_hit_date_text else "未找到 3买",
        "history": history_rows,
        "history_text": history_text,
        "history_json": json.dumps(history_rows, ensure_ascii=False),
        "scan_start_date_text": _format_date_text(scan_start_date),
        "scan_end_date_text": _format_date_text(scan_end_date),
        "history_title": _build_three_buy_history_title(
            _format_date_text(scan_start_date),
            _format_date_text(scan_end_date),
            history_text,
        ),
    }


def _scan_recent_beichi_history(
    market: str, code: str, frequency: str = "d"
) -> dict[str, Any]:
    klines = _load_recent_beichi_source_klines(market, code, frequency)
    ordered_dates = _extract_ordered_kline_dates(klines)
    if not ordered_dates:
        return {
            "recent_beichi_time": None,
            "recent_beichi_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
            "current_beichi_status_text": "当前无背驰",
            "current_beichi_types_text": "",
            "recent_beichi_types_text": "",
            "label": "未找到背驰",
            "history": [],
            "history_text": "",
            "history_json": "[]",
            "scan_start_date_text": "",
            "scan_end_date_text": "",
            "history_title": "",
        }

    if len(ordered_dates) >= 11:
        scan_start_date = ordered_dates[-11]
        scan_dates = ordered_dates[-10:]
    else:
        scan_start_date = ordered_dates[0]
        scan_dates = [ordered_dates[-1]]
    scan_end_date = scan_dates[-1]

    history_rows: list[dict[str, str]] = []
    latest_hit_date_text = ""
    latest_hit_types_text = ""
    latest_hit_timestamp: datetime.datetime | None = None
    current_status_text = "当前无背驰"
    current_types_text = ""

    for scan_date in scan_dates:
        marker = _find_recent_beichi_marker_from_klines(
            market, code, frequency, _slice_klines_to_end_date(klines, scan_date)
        )
        beichi_date_text = marker.get("date_text") if marker else ""
        types_text = marker.get("types_text") if marker else ""
        status_text = "当前背驰" if beichi_date_text else "当前无背驰"
        history_rows.append(
            {
                "scan_date": _format_date_text(scan_date),
                "beichi_date": beichi_date_text,
                "status_text": status_text,
                "types_text": types_text,
            }
        )
        current_status_text = status_text
        current_types_text = types_text
        if beichi_date_text:
            latest_hit_date_text = beichi_date_text
            latest_hit_types_text = types_text
            latest_hit_timestamp = datetime.datetime.strptime(
                beichi_date_text, "%Y-%m-%d"
            )

    history_text = _build_beichi_scan_history_text(history_rows)
    return {
        "recent_beichi_time": latest_hit_timestamp,
        "recent_beichi_time_text": latest_hit_date_text or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "current_beichi_status_text": current_status_text,
        "current_beichi_types_text": current_types_text,
        "recent_beichi_types_text": latest_hit_types_text,
        "label": "最近背驰" if latest_hit_date_text else "未找到背驰",
        "history": history_rows,
        "history_text": history_text,
        "history_json": json.dumps(history_rows, ensure_ascii=False),
        "scan_start_date_text": _format_date_text(scan_start_date),
        "scan_end_date_text": _format_date_text(scan_end_date),
        "history_title": _build_three_buy_history_title(
            _format_date_text(scan_start_date),
            _format_date_text(scan_end_date),
            history_text,
        ),
    }


def _should_use_recent_three_buy_cache(cached_row: dict[str, Any] | None, latest_date_text: str) -> bool:
    if not cached_row or not latest_date_text:
        return False
    return (
        _normalize_text(cached_row.get("status")) in {"ok", "not_found"}
        and _format_date_text(cached_row.get("recent_three_buy_scan_end_date_text")) == latest_date_text
    )


def _build_recent_three_buy_cached_hit_payload(
    row_id: str, symbol: str, cached_row: dict[str, Any]
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "symbol": symbol,
        "recent_three_buy_time_text": _normalize_text(
            cached_row.get("recent_three_buy_time_text")
        )
        or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "status": "ok",
        "label": _normalize_text(cached_row.get("label")) or "最近 3买",
        "recent_three_buy_scan_history_text": _normalize_text(
            cached_row.get("recent_three_buy_scan_history_text")
        ),
        "recent_three_buy_scan_history_json": _normalize_text(
            cached_row.get("recent_three_buy_scan_history_json")
        )
        or "[]",
        "recent_three_buy_scan_start_date_text": _normalize_text(
            cached_row.get("recent_three_buy_scan_start_date_text")
        ),
        "recent_three_buy_scan_end_date_text": _normalize_text(
            cached_row.get("recent_three_buy_scan_end_date_text")
        ),
        "recent_three_buy_history_title": _build_three_buy_history_title(
            _normalize_text(cached_row.get("recent_three_buy_scan_start_date_text")),
            _normalize_text(cached_row.get("recent_three_buy_scan_end_date_text")),
            _normalize_text(cached_row.get("recent_three_buy_scan_history_text")),
        ),
    }


def _build_recent_three_buy_cached_miss_payload(
    row_id: str, symbol: str, cached_row: dict[str, Any]
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "symbol": symbol,
        "recent_three_buy_time_text": _normalize_text(
            cached_row.get("recent_three_buy_time_text")
        )
        or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "status": "not_found",
        "recent_three_buy_scan_history_text": _normalize_text(
            cached_row.get("recent_three_buy_scan_history_text")
        ),
        "recent_three_buy_scan_history_json": _normalize_text(
            cached_row.get("recent_three_buy_scan_history_json")
        )
        or "[]",
        "recent_three_buy_scan_start_date_text": _normalize_text(
            cached_row.get("recent_three_buy_scan_start_date_text")
        ),
        "recent_three_buy_scan_end_date_text": _normalize_text(
            cached_row.get("recent_three_buy_scan_end_date_text")
        ),
        "recent_three_buy_history_title": _build_three_buy_history_title(
            _normalize_text(cached_row.get("recent_three_buy_scan_start_date_text")),
            _normalize_text(cached_row.get("recent_three_buy_scan_end_date_text")),
            _normalize_text(cached_row.get("recent_three_buy_scan_history_text")),
        ),
    }


def _should_use_recent_beichi_cache(cached_row: dict[str, Any] | None, latest_date_text: str) -> bool:
    if not cached_row or not latest_date_text:
        return False
    return (
        _normalize_text(cached_row.get("status")) in {"ok", "not_found"}
        and _format_date_text(cached_row.get("recent_beichi_scan_end_date_text")) == latest_date_text
    )


def _build_recent_beichi_cached_hit_payload(
    row_id: str, symbol: str, cached_row: dict[str, Any]
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "symbol": symbol,
        "recent_beichi_time_text": _normalize_text(cached_row.get("recent_beichi_time_text"))
        or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "current_beichi_status_text": _normalize_text(
            cached_row.get("current_beichi_status_text")
        )
        or "当前无背驰",
        "current_beichi_types_text": _normalize_text(
            cached_row.get("current_beichi_types_text")
        ),
        "recent_beichi_types_text": _normalize_text(cached_row.get("recent_beichi_types_text")),
        "recent_beichi_scan_history_text": _normalize_text(
            cached_row.get("recent_beichi_scan_history_text")
        ),
        "recent_beichi_scan_history_json": _normalize_text(
            cached_row.get("recent_beichi_scan_history_json")
        )
        or "[]",
        "recent_beichi_scan_start_date_text": _normalize_text(
            cached_row.get("recent_beichi_scan_start_date_text")
        ),
        "recent_beichi_scan_end_date_text": _normalize_text(
            cached_row.get("recent_beichi_scan_end_date_text")
        ),
        "recent_beichi_history_title": _build_three_buy_history_title(
            _normalize_text(cached_row.get("recent_beichi_scan_start_date_text")),
            _normalize_text(cached_row.get("recent_beichi_scan_end_date_text")),
            _normalize_text(cached_row.get("recent_beichi_scan_history_text")),
        ),
        "status": "ok",
        "label": _normalize_text(cached_row.get("label")) or "最近背驰",
    }


def _build_recent_beichi_cached_miss_payload(
    row_id: str, symbol: str, cached_row: dict[str, Any]
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "symbol": symbol,
        "recent_beichi_time_text": _normalize_text(cached_row.get("recent_beichi_time_text"))
        or _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
        "current_beichi_status_text": _normalize_text(
            cached_row.get("current_beichi_status_text")
        )
        or "当前无背驰",
        "current_beichi_types_text": _normalize_text(
            cached_row.get("current_beichi_types_text")
        ),
        "recent_beichi_types_text": _normalize_text(cached_row.get("recent_beichi_types_text")),
        "recent_beichi_scan_history_text": _normalize_text(
            cached_row.get("recent_beichi_scan_history_text")
        ),
        "recent_beichi_scan_history_json": _normalize_text(
            cached_row.get("recent_beichi_scan_history_json")
        )
        or "[]",
        "recent_beichi_scan_start_date_text": _normalize_text(
            cached_row.get("recent_beichi_scan_start_date_text")
        ),
        "recent_beichi_scan_end_date_text": _normalize_text(
            cached_row.get("recent_beichi_scan_end_date_text")
        ),
        "recent_beichi_history_title": _build_three_buy_history_title(
            _normalize_text(cached_row.get("recent_beichi_scan_start_date_text")),
            _normalize_text(cached_row.get("recent_beichi_scan_end_date_text")),
            _normalize_text(cached_row.get("recent_beichi_scan_history_text")),
        ),
        "status": "not_found",
    }


def _replace_recent_three_buy_rows(rows: list[dict[str, Any]]) -> None:
    replace_method = getattr(db, "serenity_aistocks_recent_three_buy_replace", None)
    if replace_method is not None and rows:
        replace_method(rows)


def _replace_recent_beichi_rows(rows: list[dict[str, Any]]) -> None:
    replace_method = getattr(db, "serenity_aistocks_recent_beichi_replace", None)
    if replace_method is not None and rows:
        replace_method(rows)


def _scan_recent_three_buy_item(
    raw_item: dict[str, Any],
    cached_row_map: dict[tuple[str, str], dict[str, Any]],
    scan_time: datetime.datetime,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    row_id = _normalize_text(raw_item.get("row_id"))
    market = _normalize_text(raw_item.get("market")).lower()
    code = _normalize_quote_code(market, raw_item.get("code"))
    symbol = _normalize_text(raw_item.get("symbol")) or code
    if not market or not code:
        return (
            "miss",
            {
                "row_id": row_id,
                "symbol": symbol,
                "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "status": "unsupported",
            },
            None,
        )
    cached_row = cached_row_map.get((market, code))
    latest_date_text = _load_latest_daily_kline_date(market, code, frequency="d")
    if _should_use_recent_three_buy_cache(cached_row, latest_date_text):
        if _normalize_text(cached_row.get("status")) == "not_found":
            return "miss", _build_recent_three_buy_cached_miss_payload(row_id, symbol, cached_row), None
        return "hit", _build_recent_three_buy_cached_hit_payload(row_id, symbol, cached_row), None
    try:
        scan_result = _scan_recent_three_buy_history(market, code, frequency="d")
    except Exception:
        return (
            "miss",
            {
                "row_id": row_id,
                "symbol": symbol,
                "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "status": "error",
                "recent_three_buy_scan_history_text": "",
                "recent_three_buy_scan_history_json": "[]",
                "recent_three_buy_scan_start_date_text": "",
                "recent_three_buy_scan_end_date_text": "",
                "recent_three_buy_history_title": "",
            },
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
                "recent_three_buy_scan_history_text": "",
                "recent_three_buy_scan_history_json": "[]",
                "recent_three_buy_scan_start_date_text": "",
                "recent_three_buy_scan_end_date_text": "",
                "recent_three_buy_history_title": "",
            },
        )
    if scan_result["recent_three_buy_time_text"] == _DEFAULT_RECENT_THREE_BUY_TIME_TEXT:
        return (
            "miss",
            {
                "row_id": row_id,
                "symbol": symbol,
                "recent_three_buy_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "status": "not_found",
                "recent_three_buy_scan_history_text": scan_result["history_text"],
                "recent_three_buy_scan_history_json": scan_result["history_json"],
                "recent_three_buy_scan_start_date_text": scan_result["scan_start_date_text"],
                "recent_three_buy_scan_end_date_text": scan_result["scan_end_date_text"],
                "recent_three_buy_history_title": scan_result["history_title"],
            },
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
                "recent_three_buy_scan_history_text": scan_result["history_text"],
                "recent_three_buy_scan_history_json": scan_result["history_json"],
                "recent_three_buy_scan_start_date_text": scan_result["scan_start_date_text"],
                "recent_three_buy_scan_end_date_text": scan_result["scan_end_date_text"],
            },
        )
    return (
        "hit",
        {
            "row_id": row_id,
            "symbol": symbol,
            "recent_three_buy_time_text": scan_result["recent_three_buy_time_text"],
            "status": "ok",
            "label": "最近 3买",
            "recent_three_buy_scan_history_text": scan_result["history_text"],
            "recent_three_buy_scan_history_json": scan_result["history_json"],
            "recent_three_buy_scan_start_date_text": scan_result["scan_start_date_text"],
            "recent_three_buy_scan_end_date_text": scan_result["scan_end_date_text"],
            "recent_three_buy_history_title": scan_result["history_title"],
        },
        {
            "market": market,
            "code": code,
            "symbol": symbol,
            "recent_three_buy_time": scan_result["recent_three_buy_time"],
            "recent_three_buy_time_text": scan_result["recent_three_buy_time_text"],
            "label": "最近 3买",
            "status": "ok",
            "source": "serenity_aistocks_manual_scan",
            "scanned_at": scan_time,
            "updated_at": scan_time,
            "recent_three_buy_scan_history_text": scan_result["history_text"],
            "recent_three_buy_scan_history_json": scan_result["history_json"],
            "recent_three_buy_scan_start_date_text": scan_result["scan_start_date_text"],
            "recent_three_buy_scan_end_date_text": scan_result["scan_end_date_text"],
        },
    )


def _scan_recent_beichi_item(
    raw_item: dict[str, Any],
    cached_row_map: dict[tuple[str, str], dict[str, Any]],
    scan_time: datetime.datetime,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    row_id = _normalize_text(raw_item.get("row_id"))
    market = _normalize_text(raw_item.get("market")).lower()
    code = _normalize_quote_code(market, raw_item.get("code"))
    symbol = _normalize_text(raw_item.get("symbol")) or code
    if not market or not code:
        return (
            "miss",
            {
                "row_id": row_id,
                "symbol": symbol,
                "recent_beichi_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "current_beichi_status_text": "当前无背驰",
                "status": "unsupported",
            },
            None,
        )
    cached_row = cached_row_map.get((market, code))
    latest_date_text = _load_latest_daily_kline_date(market, code, frequency="d")
    if _should_use_recent_beichi_cache(cached_row, latest_date_text):
        if _normalize_text(cached_row.get("status")) == "not_found":
            return "miss", _build_recent_beichi_cached_miss_payload(row_id, symbol, cached_row), None
        return "hit", _build_recent_beichi_cached_hit_payload(row_id, symbol, cached_row), None
    try:
        scan_result = _scan_recent_beichi_history(market, code, frequency="d")
    except Exception:
        return (
            "miss",
            {
                "row_id": row_id,
                "symbol": symbol,
                "recent_beichi_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "current_beichi_status_text": "扫描异常",
                "current_beichi_types_text": "",
                "recent_beichi_types_text": "",
                "status": "error",
                "recent_beichi_scan_history_text": "",
                "recent_beichi_scan_history_json": "[]",
                "recent_beichi_scan_start_date_text": "",
                "recent_beichi_scan_end_date_text": "",
                "recent_beichi_history_title": "",
            },
            {
                "market": market,
                "code": code,
                "symbol": symbol,
                "recent_beichi_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "current_beichi_status_text": "扫描异常",
                "current_beichi_types_text": "",
                "recent_beichi_types_text": "",
                "label": "扫描异常",
                "status": "error",
                "source": "serenity_aistocks_manual_scan",
                "scanned_at": scan_time,
                "updated_at": scan_time,
                "recent_beichi_scan_history_text": "",
                "recent_beichi_scan_history_json": "[]",
                "recent_beichi_scan_start_date_text": "",
                "recent_beichi_scan_end_date_text": "",
            },
        )
    base_payload = {
        "row_id": row_id,
        "symbol": symbol,
        "recent_beichi_time_text": scan_result["recent_beichi_time_text"],
        "current_beichi_status_text": scan_result["current_beichi_status_text"],
        "current_beichi_types_text": scan_result["current_beichi_types_text"],
        "recent_beichi_types_text": scan_result["recent_beichi_types_text"],
        "recent_beichi_scan_history_text": scan_result["history_text"],
        "recent_beichi_scan_history_json": scan_result["history_json"],
        "recent_beichi_scan_start_date_text": scan_result["scan_start_date_text"],
        "recent_beichi_scan_end_date_text": scan_result["scan_end_date_text"],
        "recent_beichi_history_title": scan_result["history_title"],
    }
    if scan_result["recent_beichi_time_text"] == _DEFAULT_RECENT_THREE_BUY_TIME_TEXT:
        return (
            "miss",
            {**base_payload, "status": "not_found"},
            {
                "market": market,
                "code": code,
                "symbol": symbol,
                "recent_beichi_time_text": _DEFAULT_RECENT_THREE_BUY_TIME_TEXT,
                "current_beichi_status_text": scan_result["current_beichi_status_text"],
                "current_beichi_types_text": scan_result["current_beichi_types_text"],
                "recent_beichi_types_text": scan_result["recent_beichi_types_text"],
                "label": "未找到背驰",
                "status": "not_found",
                "source": "serenity_aistocks_manual_scan",
                "scanned_at": scan_time,
                "updated_at": scan_time,
                "recent_beichi_scan_history_text": scan_result["history_text"],
                "recent_beichi_scan_history_json": scan_result["history_json"],
                "recent_beichi_scan_start_date_text": scan_result["scan_start_date_text"],
                "recent_beichi_scan_end_date_text": scan_result["scan_end_date_text"],
            },
        )
    return (
        "hit",
        {**base_payload, "status": "ok", "label": "最近背驰"},
        {
            "market": market,
            "code": code,
            "symbol": symbol,
            "recent_beichi_time": scan_result["recent_beichi_time"],
            "recent_beichi_time_text": scan_result["recent_beichi_time_text"],
            "current_beichi_status_text": scan_result["current_beichi_status_text"],
            "current_beichi_types_text": scan_result["current_beichi_types_text"],
            "recent_beichi_types_text": scan_result["recent_beichi_types_text"],
            "label": "最近背驰",
            "status": "ok",
            "source": "serenity_aistocks_manual_scan",
            "scanned_at": scan_time,
            "updated_at": scan_time,
            "recent_beichi_scan_history_text": scan_result["history_text"],
            "recent_beichi_scan_history_json": scan_result["history_json"],
            "recent_beichi_scan_start_date_text": scan_result["scan_start_date_text"],
            "recent_beichi_scan_end_date_text": scan_result["scan_end_date_text"],
        },
    )


def _process_aistocks_scan_items(
    items: list[dict[str, Any]] | None,
    *,
    task_type: str,
    scan_item_fn,
    cached_row_map: dict[tuple[str, str], dict[str, Any]],
    replace_rows_fn,
    progress_callback=None,
) -> dict[str, list[dict[str, Any]]]:
    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    rows_to_replace: list[dict[str, Any]] = []
    scan_time = datetime.datetime.now()
    normalized_items = list(items or [])
    total_items = len(normalized_items)
    for index, raw_item in enumerate(normalized_items, start=1):
        result_kind, payload, replace_row = scan_item_fn(raw_item, cached_row_map, scan_time)
        if result_kind == "hit":
            hits.append(payload)
        else:
            misses.append(payload)
        if replace_row is not None:
            if progress_callback is None:
                rows_to_replace.append(replace_row)
            else:
                replace_rows_fn([replace_row])
        if progress_callback is not None:
            progress = 100 if total_items <= 0 else min(99, int(index * 100 / total_items))
            progress_callback(
                processed_items=index,
                total_items=total_items,
                hit_count=len(hits),
                miss_count=len(misses),
                progress=progress,
                partial_hits=copy.deepcopy(hits),
                partial_misses=copy.deepcopy(misses),
                message=f"已完成 {index} / {total_items} 只",
                state="running",
            )
    if progress_callback is None and rows_to_replace:
        replace_rows_fn(rows_to_replace)
    return {"hits": hits, "misses": misses}


def fetch_serenity_aistocks_recent_three_buy_times(
    items: list[dict[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    return _process_aistocks_scan_items(
        items,
        task_type="recent_three_buy",
        scan_item_fn=_scan_recent_three_buy_item,
        cached_row_map=_build_db_recent_three_buy_map(items or []),
        replace_rows_fn=_replace_recent_three_buy_rows,
    )


def fetch_serenity_aistocks_recent_beichi_times(
    items: list[dict[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    return _process_aistocks_scan_items(
        items,
        task_type="recent_beichi",
        scan_item_fn=_scan_recent_beichi_item,
        cached_row_map=_build_db_recent_beichi_map(items or []),
        replace_rows_fn=_replace_recent_beichi_rows,
    )


def _run_recent_three_buy_scan_task(task_id: str, items: list[dict[str, Any]] | None) -> None:
    normalized_items = list(items or [])
    try:
        _set_aistocks_scan_task(
            task_id,
            task_type="recent_three_buy",
            state="running",
            message="任务已启动",
            progress=1,
            total_items=len(normalized_items),
            processed_items=0,
            hit_count=0,
            miss_count=0,
            partial_hits=[],
            partial_misses=[],
            started_at=datetime.datetime.now().isoformat(),
        )
        result = _process_aistocks_scan_items(
            normalized_items,
            task_type="recent_three_buy",
            scan_item_fn=_scan_recent_three_buy_item,
            cached_row_map=_build_db_recent_three_buy_map(normalized_items),
            replace_rows_fn=_replace_recent_three_buy_rows,
            progress_callback=lambda **updates: _set_aistocks_scan_task(task_id, **updates),
        )
        _set_aistocks_scan_task(
            task_id,
            task_type="recent_three_buy",
            state="completed",
            message=f"扫描完成，命中 {len(result['hits'])} / {len(normalized_items)} 只",
            progress=100,
            total_items=len(normalized_items),
            processed_items=len(normalized_items),
            hit_count=len(result["hits"]),
            miss_count=len(result["misses"]),
            partial_hits=result["hits"],
            partial_misses=result["misses"],
            result=result,
            finished_at=datetime.datetime.now().isoformat(),
        )
        completed_task = _get_aistocks_scan_task(task_id) or {}
        _clear_active_aistocks_scan_task(
            _normalize_text(completed_task.get("sheet_slug")),
            "recent_three_buy",
            task_id,
        )
    except Exception as exc:
        _set_aistocks_scan_task(
            task_id,
            task_type="recent_three_buy",
            state="failed",
            message=str(exc) or "三买扫描失败",
            error=str(exc) or "三买扫描失败",
            progress=100,
            finished_at=datetime.datetime.now().isoformat(),
        )
        failed_task = _get_aistocks_scan_task(task_id) or {}
        _clear_active_aistocks_scan_task(
            _normalize_text(failed_task.get("sheet_slug")),
            "recent_three_buy",
            task_id,
        )


def _run_recent_beichi_scan_task(task_id: str, items: list[dict[str, Any]] | None) -> None:
    normalized_items = list(items or [])
    try:
        _set_aistocks_scan_task(
            task_id,
            task_type="recent_beichi",
            state="running",
            message="任务已启动",
            progress=1,
            total_items=len(normalized_items),
            processed_items=0,
            hit_count=0,
            miss_count=0,
            partial_hits=[],
            partial_misses=[],
            started_at=datetime.datetime.now().isoformat(),
        )
        result = _process_aistocks_scan_items(
            normalized_items,
            task_type="recent_beichi",
            scan_item_fn=_scan_recent_beichi_item,
            cached_row_map=_build_db_recent_beichi_map(normalized_items),
            replace_rows_fn=_replace_recent_beichi_rows,
            progress_callback=lambda **updates: _set_aistocks_scan_task(task_id, **updates),
        )
        _set_aistocks_scan_task(
            task_id,
            task_type="recent_beichi",
            state="completed",
            message=f"扫描完成，命中 {len(result['hits'])} / {len(normalized_items)} 只",
            progress=100,
            total_items=len(normalized_items),
            processed_items=len(normalized_items),
            hit_count=len(result["hits"]),
            miss_count=len(result["misses"]),
            partial_hits=result["hits"],
            partial_misses=result["misses"],
            result=result,
            finished_at=datetime.datetime.now().isoformat(),
        )
        completed_task = _get_aistocks_scan_task(task_id) or {}
        _clear_active_aistocks_scan_task(
            _normalize_text(completed_task.get("sheet_slug")),
            "recent_beichi",
            task_id,
        )
    except Exception as exc:
        _set_aistocks_scan_task(
            task_id,
            task_type="recent_beichi",
            state="failed",
            message=str(exc) or "背驰扫描失败",
            error=str(exc) or "背驰扫描失败",
            progress=100,
            finished_at=datetime.datetime.now().isoformat(),
        )
        failed_task = _get_aistocks_scan_task(task_id) or {}
        _clear_active_aistocks_scan_task(
            _normalize_text(failed_task.get("sheet_slug")),
            "recent_beichi",
            task_id,
        )


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

    resolved_sheet_slug = _normalize_text(sheet_slug) or _normalize_text(
        sheets[0].get("sheet_slug")
    )
    selected_sheet = get_serenity_aistocks_sheet(resolved_sheet_slug)
    if not selected_sheet:
        return None

    selected_sheet_summary = next(
        (sheet for sheet in sheets if _normalize_text(sheet.get("sheet_slug")) == resolved_sheet_slug),
        None,
    )
    active_scan_tasks = {
        "recent_three_buy": _get_active_aistocks_scan_task(
            resolved_sheet_slug, "recent_three_buy"
        ),
        "recent_beichi": _get_active_aistocks_scan_task(
            resolved_sheet_slug, "recent_beichi"
        ),
    }
    return {
        "workbook": workbook,
        "selected_sheet": selected_sheet,
        "selected_sheet_slug": resolved_sheet_slug,
        "selected_sheet_summary": selected_sheet_summary,
        "sheet_slugs": [_normalize_text(sheet.get("sheet_slug")) for sheet in sheets if sheet.get("sheet_slug")],
        "sync_status": sync_status,
        "active_scan_tasks": active_scan_tasks,
    }


# ---------------------------------------------------------------------------
# 点击按需分析（Serenity 研究）：后端 spawn 无头 claude，过质量闸门后写回研究 JSON。
# ---------------------------------------------------------------------------
_ANALYZE_TASK_TYPE = "serenity_analyze"
_ANALYZE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 命中缓存 1 周内直接复用，可强制刷新
_ANALYZE_CLAUDE_TIMEOUT_SECONDS = 8 * 60
_ANALYZE_CLAUDE_BIN = os.environ.get("SERENITY_CLAUDE_BIN") or "/root/.local/bin/claude"
_VALIDATE_RESEARCH_SCRIPT = _PROJECT_ROOT / "scripts" / "validate_serenity_research.py"
# 每次分析的实时过程日志目录，服务器上可 `tail -f` 观察 claude 的联网/推理全过程。
_ANALYZE_LOG_DIR = Path(__file__).resolve().parents[1] / "logs" / "serenity_analyze"
# 无头 claude 的中性工作目录：不在项目内运行，避免继承本项目 SessionStart hook
# 注入的旧对话摘要（每次多吃约 28k input token 的成本噪声）。
_ANALYZE_NEUTRAL_CWD = Path(tempfile.gettempdir()) / "serenity_analyze_cwd"


def _analyze_slug(name: str) -> str:
    return _slugify_sheet_name(_normalize_text(name)) or "unknown"


def _load_research_json() -> dict[str, Any]:
    try:
        with open(_serenity_fit._AISTOCKS_RESEARCH_JSON_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _research_entry_is_fresh(entry: dict[str, Any]) -> bool:
    verified_at = _normalize_text(entry.get("verified_at"))
    if not verified_at:
        return False
    try:
        verified_dt = datetime.datetime.fromisoformat(verified_at)
    except ValueError:
        try:
            verified_dt = datetime.datetime.strptime(verified_at, "%Y-%m-%d")
        except ValueError:
            return False
    age = (datetime.datetime.now() - verified_dt).total_seconds()
    return 0 <= age <= _ANALYZE_CACHE_TTL_SECONDS


# Serenity 方法论 14 点认证清单（源自 references/methodology.md §15）。子进程在中性 cwd
# 读不到项目文件，故内嵌为自包含 rubric，逐条判定 yes/partial/no/na + 证据。
_SERENITY_CHECKLIST = (
    "1. 瓶颈：是否独家/近独家单点卡点，无近期合格替代，具真实定价权？\n"
    "2. 上游且便宜：是否位于『卖铲人』上游，且其组件占下游 BOM 比例小（买方宁可涨价买单而非绕开）？\n"
    "3. 链路通透：能否从原料/输入层完整画到模组/成品，不混淆 衬底≠外延≠晶圆≠激光≠模块/封装？\n"
    "4. 需求驱动：TAM 是否由超算 AI capex / 物理 AI（机器人）驱动，而非传统周期性市场？\n"
    "5. 合同与对手方：是否有签约多年订单，且对手方信用强（AAA 超算/大厂而非烧钱 lab）？\n"
    "6. 真实毛利：GAAP 毛利（非挑拣的非 GAAP/单行口径）是否支撑其质地？\n"
    "7. 融资质量：是否存在大额增发/ATM、SBC、高息债等稀释否决项？（A 股看定增/大额减持/高质押）\n"
    "8. 阶段：是否处于放量前的认证/设计导入期、被 TTM 收入低估；还是已被市场抢跑？\n"
    "9. 催化与时点：可交易窗口内是否有明确日期催化（财报/行业大会/政策/指数纳入）？\n"
    "10. 市值空间：市值是否足够小、机构重估仍在前方？\n"
    "11. 验证滞后：机构/券商覆盖是否仍落后于供应链证据（=信息差），还是已被计价？\n"
    "12. 风险与仓位：二元性有多强（稀释/单一客户/出口管制/重组）？\n"
    "13. 披露权重：原作者是否持有/回避/无仓（A 股场景通常为 na）？\n"
    "14. 宏观叠加：当前利率/关税/战争 regime 对该具体论点是利还是弊？"
)

# v2 研究 schema 骨架（analyze / critique 两轮共用）。详见 serenity-aleabitoreddit-main/RESEARCH_SCHEMA.md。
_V2_SCHEMA_SKELETON = (
    "{"
    "\"code_in_xlsx\":\"\",\"code_verified\":\"\",\"code_fix_note\":\"\",\"verified_at\":\"YYYY-MM-DD\","
    "\"fit_status\":\"fit|partial_fit|not_fit|watch\",\"fit_reason_short\":\"\",\"fit_reason_detail\":\"\",\"fit_basis\":\"\","
    "\"selection_reason\":{\"summary\":\"\",\"fit_basis\":\"\"},"
    "\"scarcity_view\":{\"label\":\"强|中|弱\",\"detail\":\"\"},"
    "\"capacity_view\":{\"label\":\"强|中|弱\",\"detail\":\"\"},"
    "\"pricing_view\":{\"label\":\"强|中|弱\",\"detail\":\"\"},"
    "\"segment_market_view\":{\"market_size_text\":\"\",\"company_share_text\":\"\",\"share_level\":\"\"},"
    "\"sector_context_view\":{\"sector_name\":\"\",\"sector_role\":\"\",\"market_size_text\":\"\",\"growth_outlook\":\"\","
    "\"company_position_text\":\"\",\"company_share_text\":\"\",\"share_level\":\"\",\"evidence_note\":\"\"},"
    "\"industry_chain_view\":{\"upstream\":\"\",\"midstream\":\"\",\"downstream\":\"\",\"company_link_position\":\"\",\"choke_point_note\":\"\"},"
    "\"market_cap_research\":{\"current_text\":\"\",\"upside_text\":\"\",\"downside_text\":\"\",\"rationale\":\"\",\"live_number_source_required\":true},"
    "\"financials_view\":{\"revenue_segments\":[{\"name\":\"\",\"pct\":\"\",\"trend\":\"\"}],\"revenue_trend_3y\":\"\",\"margin_text\":\"\",\"operating_leverage_text\":\"\"},"
    "\"moat_view\":{\"moat_types\":[\"\"],\"durability\":\"强|中|弱\",\"detail\":\"\"},"
    "\"valuation_view\":{\"pe_text\":\"\",\"pb_text\":\"\",\"peg_text\":\"\",\"vs_history_text\":\"\",\"vs_peers_text\":\"\",\"verdict\":\"低估|合理|高估\"},"
    "\"catalysts_view\":[{\"window\":\"\",\"event\":\"\",\"impact\":\"\"}],"
    "\"risks_view\":[{\"risk\":\"\",\"impact\":\"\",\"monitor\":\"\"}],"
    "\"thesis_view\":{\"variant_perception\":\"\",\"bull_points\":[\"\"],\"bear_points\":[\"\"]},"
    "\"scenario_view\":{\"bull\":{\"prob\":\"\",\"target\":\"\",\"drivers\":\"\"},\"base\":{\"prob\":\"\",\"target\":\"\",\"drivers\":\"\"},\"bear\":{\"prob\":\"\",\"target\":\"\",\"drivers\":\"\"}},"
    "\"confidence\":{\"overall\":\"高|中|低\",\"by_dimension\":{\"scarcity\":\"\",\"valuation\":\"\",\"catalysts\":\"\",\"risks\":\"\"},\"evidence_tier_summary\":\"\"},"
    "\"serenity_certification\":{\"verdict\":\"fit|partial_fit|not_fit|watch\",\"score\":\"N/14\","
    "\"checklist\":["
    "{\"id\":1,\"name\":\"瓶颈\",\"result\":\"yes|partial|no|na\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":2,\"name\":\"上游且便宜\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":3,\"name\":\"链路通透\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":4,\"name\":\"需求驱动\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":5,\"name\":\"合同与对手方\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":6,\"name\":\"真实毛利\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":7,\"name\":\"融资质量\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":8,\"name\":\"阶段\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":9,\"name\":\"催化与时点\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":10,\"name\":\"市值空间\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":11,\"name\":\"验证滞后\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":12,\"name\":\"风险与仓位\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":13,\"name\":\"披露权重\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"},"
    "{\"id\":14,\"name\":\"宏观叠加\",\"result\":\"\",\"evidence\":\"\",\"source_url\":\"\"}"
    "],\"bottleneck_map\":\"原料→…→模组/成品的多跳链路，并标注每层由谁卡点\","
    "\"disqualifiers\":[],\"anti_patterns_checked\":\"\",\"summary\":\"\"},"
    "\"evidence_sources\":[{\"title\":\"\",\"summary\":\"\",\"url\":\"\",\"source_type\":\"\",\"tier\":1}]"
    "}"
)


def _prompt_gather(name: str, code: str) -> str:
    """PASS A：只采集证据，不下结论。"""
    return (
        "你是卖方股票研究员（决策支持用途，本工具不下单、不自动交易）。这是第 1 步：只做数据采集，不下结论。\n"
        f"联网检索 A 股「{name}」（xlsx 代码 {code or '未知'}）近 12 个月公开信息，逐项覆盖：\n"
        f"①名称↔代码核验：确认 {code or '记录代码'} 是否真对应本公司，不符给正确代码（形如 sh600000/sz300285/bj430000）；\n"
        "②最新年报/季报：营收、归母净利、各营收分部及占比、毛利率、经营杠杆；\n"
        "③市值与估值：总市值、P/E、P/B、PEG（查得到就给并附来源；查不到写 null，不编造）；\n"
        "④细分市场空间与公司份额；⑤产业链上下游与卡点；⑥护城河线索；\n"
        "⑦近 12 月催化事件；⑧主要风险。\n"
        "只输出一个 JSON（无 markdown、无多余文字）：\n"
        "{\"code_check\":{\"code_in_xlsx\":\"\",\"code_verified\":\"\",\"note\":\"\"},"
        "\"evidence\":[{\"topic\":\"\",\"point\":\"\",\"value\":\"\",\"url\":\"\",\"tier\":1}]}\n"
        "tier：1=一手披露/交易所，2=权威财媒，3=其他。无法核实的字段值写 null。"
    )


def _prompt_analyze(name: str, code: str, gather_text: str) -> str:
    """PASS B：基于采集证据做多维分析，产出完整 v2 schema。"""
    return (
        "你是卖方股票研究员（决策支持用途，不下单、不自动交易）。这是第 2 步：基于下方证据做多维分析，"
        "按机构研究（CFA）结构严格输出完整 JSON。\n\n"
        f"标的：「{name}」（xlsx 代码 {code or '未知'}）。\n"
        "【第 1 步采集到的证据】\n" + (gather_text or "")[:6000] + "\n\n"
        "要求：\n"
        "1. 【核心】用 Serenity 方法论做一次完整认证 serenity_certification：逐条判定下面 14 点，"
        "每条 result 取 yes/partial/no/na 并给 evidence(基于证据的简短理由)与 source_url。"
        "从严如实判定——多数 A 股并非 US 式独家卡点，该给 partial/no 就给，不得为凑分虚高；"
        "na 只用于真正不适用(如第 13 披露权重对 A 股)，不得用 na 逃避判断。"
        "score 写成 已通过(yes)条数/14；verdict 依据总体强弱取 fit/partial_fit/not_fit/watch；"
        "bottleneck_map 用多跳 BOM 链路(原料→…→模组)并标注每层由谁卡点；"
        "disqualifiers 列命中的否决项(大额定增/减持/高质押/高息债等)；"
        "anti_patterns_checked 说明已排查的反模式(纯技术面/内部人卖出/混淆链路层/情绪噪音)。\n"
        "Serenity 14 点清单：\n" + _SERENITY_CHECKLIST + "\n"
        "2. fit_status 必须等于 serenity_certification.verdict（两者一致）。\n"
        "3. scarcity_view 即 Serenity 卡点/稀缺性一维；其余覆盖护城河/估值/催化/风险/情景/论点。\n"
        "4. 每个视图组都要实证填写，不得留空或占位（禁止 待补充/待验证/TODO/N/A/暂无）。\n"
        "5. 不得编造精确数字；无源处写定性并置 market_cap_research.live_number_source_required=true。\n"
        "6. scarcity/capacity/pricing/moat 的 label/durability 用 强/中/弱；valuation.verdict 用 低估/合理/高估；\n"
        "   scenario 给 牛/基准/熊 三档（prob 粗略概率、target 方向、drivers 关键驱动）；confidence 逐维给 高/中/低。\n"
        "7. evidence_sources ≥3 条真实 http(s) 链接，每条 tier 取纯数字 1/2/3（1=一手披露/交易所，2=权威财媒，3=其他；写成整数，勿写 'tier2' 这类字符串）。\n\n"
        "只输出一个 JSON（无 markdown、无多余文字），结构：\n" + _V2_SCHEMA_SKELETON
    )


def _prompt_critique(name: str, draft_text: str) -> str:
    """PASS C：自查草稿并补全/修正，输出同结构 v2 JSON。"""
    return (
        f"你是严格的研究质控。下面是「{name}」的研究草稿 JSON，请逐字段自查并修正：\n"
        "①serenity_certification 是否 14 条齐全、每条 result∈{yes,partial,no,na} 且有 evidence；"
        "verdict/score/bottleneck_map/disqualifiers/anti_patterns_checked 是否填实；"
        "是否存在为凑分虚高或滥用 na 逃避判断（如是则据证据改判）；fit_status 是否等于 verdict；\n"
        "②scarcity/capacity/pricing/moat/valuation/scenario/thesis/confidence 是否都已实证填写；\n"
        "③evidence_sources 是否 ≥3 条且每条带 tier；\n"
        "④是否残留 待补充/待验证/待研究/TODO/N/A/暂无 等占位（有则据证据补实或改定性）；\n"
        "⑤是否存在无来源的精确数字（有则改为定性或删除，并置 market_cap_research.live_number_source_required=true）。\n"
        "修正后只输出完整、同结构的 v2 JSON（无 markdown、无多余文字）。\n\n"
        "【草稿】\n" + (draft_text or "")[:9000]
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _render_stream_event(evt: dict[str, Any], counts: dict[str, int]) -> str | None:
    """把 claude stream-json 事件渲染成一行可读的中文过程日志；无关事件返回 None。

    counts 为可变计数器，按实际 tool_use 累计联网检索/抓取次数（server_tool_use
    只统计服务端 web 工具，客户端 WebSearch/WebFetch 不计入，故在此自行累计）。
    """
    etype = evt.get("type")
    if etype == "assistant":
        parts: list[str] = []
        for block in (evt.get("message") or {}).get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text = _normalize_text(block.get("text"))
                if text:
                    parts.append("💬 " + text[:200])
            elif btype == "tool_use":
                tool = block.get("name") or "tool"
                if "websearch" in tool.lower():
                    counts["search"] = counts.get("search", 0) + 1
                elif "webfetch" in tool.lower():
                    counts["fetch"] = counts.get("fetch", 0) + 1
                inp = block.get("input") or {}
                arg = _normalize_text(inp.get("query") or inp.get("url") or inp.get("prompt"))
                parts.append(f"🔧 {tool} {arg}".strip()[:200])
        return "\n".join(p for p in parts if p) or None
    if etype == "user":
        return "⬅️  收到工具结果"
    if etype == "result":
        server = (evt.get("usage") or {}).get("server_tool_use") or {}
        searches = max(counts.get("search", 0), server.get("web_search_requests", 0))
        fetches = max(counts.get("fetch", 0), server.get("web_fetch_requests", 0))
        cost = evt.get("total_cost_usd") or 0
        return (
            f"✅ 完成 | 联网检索 {searches} 次 · 抓取网页 {fetches} 次 · 用时 "
            f"{round((evt.get('duration_ms') or 0) / 1000)}s · 花费 ${cost:.3f}"
        )
    return None


def _analyze_env() -> dict[str, str]:
    env = dict(os.environ)
    bin_dir = os.path.dirname(_ANALYZE_CLAUDE_BIN)
    if bin_dir and bin_dir not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def _stream_one_claude(
    task_id: str,
    prompt: str,
    log_path: Path,
    *,
    pass_title: str,
    progress: int,
) -> str:
    """跑一轮无头 claude，逐事件追加写入可 tail 的过程日志，回传最新步骤给前端；返回最终文本。"""
    _ANALYZE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    _ANALYZE_NEUTRAL_CWD.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            _ANALYZE_CLAUDE_BIN,
            "-p",
            prompt,
            "--allowedTools",
            "WebSearch WebFetch",
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(_ANALYZE_NEUTRAL_CWD),
        env=_analyze_env(),
    )
    # 看门狗：单轮超时强杀，避免 claude 卡住时子进程永远挂着。
    watchdog = threading.Timer(_ANALYZE_CLAUDE_TIMEOUT_SECONDS, proc.kill)
    watchdog.start()

    final_text = ""
    counts: dict[str, int] = {"search": 0, "fetch": 0}
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n===== {pass_title} =====\n")
            log.write(f"# {datetime.datetime.now().isoformat()}\n\n")
            log.flush()
            for raw_line in proc.stdout or []:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "result":
                    final_text = _normalize_text(evt.get("result")) or final_text
                rendered = _render_stream_event(evt, counts)
                if not rendered:
                    continue
                stamp = datetime.datetime.now().strftime("%H:%M:%S")
                log.write(f"[{stamp}] {rendered}\n")
                log.flush()
                headline = rendered.splitlines()[0][:110]
                _set_aistocks_scan_task(
                    task_id, state="running", message=f"{pass_title}｜{headline}", progress=progress
                )
    finally:
        watchdog.cancel()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if proc.returncode not in (0, None) and not final_text:
        raise RuntimeError(f"{pass_title} 异常退出（returncode={proc.returncode}），详见日志 {log_path}")
    return final_text


def _run_research_pipeline(
    task_id: str, name: str, code: str
) -> tuple[dict[str, Any] | None, Path]:
    """三轮流水线：采集 → 多维分析 → 自查补全。全程流式写入同一 tail 日志。"""
    log_path = _ANALYZE_LOG_DIR / f"{_analyze_slug(name)}_{task_id[:8]}.log"
    _ANALYZE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"# Serenity 深度研究（3 轮流水线）：{name}（xlsx 代码 {code or '未知'}）\n")
        log.write(f"# task={task_id}\n")
        log.write(f"# 开始 {datetime.datetime.now().isoformat()}\n")
    _set_aistocks_scan_task(task_id, log_file=str(log_path))

    gather_text = _stream_one_claude(
        task_id, _prompt_gather(name, code), log_path,
        pass_title="PASS A · 数据采集", progress=35,
    )
    draft_text = _stream_one_claude(
        task_id, _prompt_analyze(name, code, gather_text), log_path,
        pass_title="PASS B · 多维分析", progress=65,
    )
    draft = _extract_json_object(draft_text)
    if not draft:
        raise RuntimeError("PASS B 未能解析出 JSON")

    critique_text = _stream_one_claude(
        task_id, _prompt_critique(name, draft_text), log_path,
        pass_title="PASS C · 自查补全", progress=90,
    )
    final = _extract_json_object(critique_text) or draft
    try:  # 总是落盘产出，便于失败诊断（无需重跑）
        log_path.with_suffix(".result.json").write_text(
            json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n# 结束 {datetime.datetime.now().isoformat()}\n")
    return final, log_path


def _classify_gate_failure(detail: str) -> tuple[str, str]:
    """把质量闸门 detail 归类为 (error_code, 面向用户的友好文案)。

    区分「证据不足」（数据源问题，非 bug，提示可换标的/重试）与「结构未达标」
    （模型漏填字段/占位/分级非法，属流水线质量问题）。
    """
    d = detail or ""
    evidence_hit = ("证据来源不足" in d) or ("缺合法 tier" in d)
    structural_markers = (
        "为空", "非法", "占位符", "须含", "须为", "不一致",
        "缺 fit_reason_short", "缺 serenity_certification",
        "缺合法已校验代码", "checklist", "认证", "疑似逃避",
    )
    structural_hit = any(m in d for m in structural_markers)
    if evidence_hit and not structural_hit:
        return (
            "evidence_insufficient",
            "公开证据不足（有效来源少于 3 条或来源分级缺失），为避免臆测已放弃出报告。"
            "可换证据更充分的标的，或稍后联网重试。",
        )
    if evidence_hit and structural_hit:
        return (
            "quality_gate_mixed",
            "研究质量未达标（既有证据不足、也有结构字段缺失），已放弃出报告，可稍后重试。",
        )
    return (
        "quality_gate_structure",
        "研究结构未达标（部分字段缺失/占位/分级非法），已放弃出报告，可稍后重试。",
    )


def _validate_single_research_entry(name: str, entry: dict[str, Any]) -> tuple[bool, str]:
    """用独立质量闸门脚本校验单条研究，返回 (是否通过, 说明)。"""
    tmp_path = _serenity_fit._AISTOCKS_RESEARCH_JSON_PATH.parent / f".analyze_check_{_analyze_slug(name)}.json"
    try:
        tmp_path.write_text(json.dumps({name: entry}, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            ["python3", str(_VALIDATE_RESEARCH_SCRIPT), str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(_PROJECT_ROOT),
        )
        return completed.returncode == 0, (completed.stdout or completed.stderr or "").strip()
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _write_research_entry(name: str, entry: dict[str, Any]) -> None:
    """原子合并单条研究到研究 JSON，并清 lru_cache 让读取层立即生效。"""
    data = _load_research_json()
    data[name] = entry
    path = _serenity_fit._AISTOCKS_RESEARCH_JSON_PATH
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    _serenity_fit._load_research_overrides.cache_clear()
    _serenity_fit._build_fit_map.cache_clear()


def _analyze_result_summary(name: str, entry: dict[str, Any], *, cached: bool) -> dict[str, Any]:
    return {
        "name": name,
        "cached": cached,
        "fit_status": _normalize_text(entry.get("fit_status")),
        "fit_reason_short": _normalize_text(entry.get("fit_reason_short")),
        "code_verified": _normalize_text(entry.get("code_verified")) or _normalize_text(entry.get("code_in_xlsx")),
        "verified_at": _normalize_text(entry.get("verified_at")),
    }


def _run_serenity_analyze_task(task_id: str, name: str, code: str, force: bool) -> None:
    slug = _analyze_slug(name)
    try:
        if not force:
            existing = _load_research_json().get(name)
            if isinstance(existing, dict) and _research_entry_is_fresh(existing):
                _set_aistocks_scan_task(
                    task_id,
                    state="done",
                    progress=100,
                    message="命中一周内缓存，直接复用",
                    finished_at=datetime.datetime.now().isoformat(),
                    result=_analyze_result_summary(name, existing, cached=True),
                )
                _clear_active_aistocks_scan_task(slug, _ANALYZE_TASK_TYPE, task_id)
                return

        _set_aistocks_scan_task(
            task_id, state="running", progress=20, message="启动三轮深度研究流水线…"
        )
        entry, _log_path = _run_research_pipeline(task_id, name, code)
        if not entry:
            raise RuntimeError("未能从分析结果中解析出 JSON")

        entry.setdefault("code_in_xlsx", code)
        entry.setdefault("verified_at", datetime.date.today().isoformat())
        entry["schema_version"] = 3
        # fit_status 与 Serenity 认证结论保持一致（认证是唯一裁决口径）。
        _cert_verdict = _normalize_text((entry.get("serenity_certification") or {}).get("verdict"))
        if _cert_verdict in {"fit", "partial_fit", "not_fit", "watch"}:
            entry["fit_status"] = _cert_verdict

        _set_aistocks_scan_task(task_id, state="running", progress=70, message="正在通过质量闸门…")
        passed, detail = _validate_single_research_entry(name, entry)
        if not passed:
            try:  # 落盘被拒条目 + 把闸门原因写进过程日志，便于诊断
                rej = _ANALYZE_LOG_DIR / f"{_analyze_slug(name)}_{task_id[:8]}.rejected.json"
                rej.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
                with open(rej.with_name(f"{_analyze_slug(name)}_{task_id[:8]}.log"), "a", encoding="utf-8") as log:
                    log.write(f"\n# 质量闸门未通过：\n{detail}\n")
            except OSError:
                pass
            err_code, friendly = _classify_gate_failure(detail)
            _set_aistocks_scan_task(
                task_id,
                state="failed",
                progress=100,
                message=friendly,
                error=err_code,
                detail=detail[:400],  # 原始闸门明细，供前端可选展开诊断
                finished_at=datetime.datetime.now().isoformat(),
            )
            return  # finally 仍会清理活跃任务

        _write_research_entry(name, entry)
        _set_aistocks_scan_task(
            task_id,
            state="done",
            progress=100,
            message="分析完成，已更新研究并刷新页面数据",
            finished_at=datetime.datetime.now().isoformat(),
            result=_analyze_result_summary(name, entry, cached=False),
        )
    except subprocess.TimeoutExpired:
        _set_aistocks_scan_task(
            task_id,
            state="failed",
            progress=100,
            message="分析超时，请稍后重试",
            error="analyze_timeout",
            finished_at=datetime.datetime.now().isoformat(),
        )
    except Exception as exc:  # noqa: BLE001 - 面向用户回传可读错误
        _set_aistocks_scan_task(
            task_id,
            state="failed",
            progress=100,
            message=f"分析失败：{str(exc)[:200]}",
            error="analyze_failed",
            finished_at=datetime.datetime.now().isoformat(),
        )
    finally:
        _clear_active_aistocks_scan_task(slug, _ANALYZE_TASK_TYPE, task_id)


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

    @app.route("/serenity/aistocks/custom-stocks", methods=["POST"])
    @login_required
    def serenity_aistocks_custom_stocks_add():
        payload = request.get_json(silent=True) or {}
        code = _normalize_text(payload.get("code"))
        theme_name = _normalize_text(payload.get("theme_name"))
        if not code or not theme_name:
            return jsonify({"ok": False, "message": "股票代码和主题不能为空"}), 400

        stock_info = _resolve_custom_stock_info_from_code(code)
        if not stock_info:
            return jsonify({"ok": False, "message": "仅支持新增有效的 A 股代码"}), 400

        base_workbook = _load_workbook_payload()
        theme_slug = _slugify_sheet_name(theme_name)
        matched_sheet = next(
            (sheet for sheet in (base_workbook.get("sheets") or []) if sheet.get("sheet_slug") == theme_slug),
            None,
        )
        canonical_theme_name = _normalize_text(
            (matched_sheet or {}).get("sheet_name")
        ) or theme_name
        row = {
            "theme_name": canonical_theme_name,
            "theme_slug": theme_slug,
            "market": stock_info["market"],
            "code": stock_info["code"],
            "symbol": stock_info["symbol"],
            "stock_name": stock_info["stock_name"],
            "notes": "",
        }
        if not hasattr(db, "serenity_aistocks_custom_entry_add"):
            return jsonify({"ok": False, "message": "当前环境不支持自定义股票保存"}), 500
        added = db.serenity_aistocks_custom_entry_add(row)
        if not added:
            return jsonify({"ok": False, "message": "该股票已存在于目标主题中"}), 409
        return jsonify(
            {
                "ok": True,
                "sheet_slug": theme_slug,
                "sheet_name": canonical_theme_name,
                "message": "新增成功",
            }
        )

    @app.route("/serenity/aistocks/custom-stocks", methods=["DELETE"])
    @login_required
    def serenity_aistocks_custom_stocks_delete():
        payload = request.get_json(silent=True) or {}
        theme_slug = _normalize_text(payload.get("theme_slug"))
        market = _normalize_text(payload.get("market")).lower() or "a"
        code = _normalize_text(payload.get("code"))
        if market == "a":
            code = _normalize_quote_code("a", _normalize_a_share_excel_symbol(code))
        if not theme_slug or not market or not code:
            return jsonify({"ok": False, "message": "删除参数不完整"}), 400
        if not hasattr(db, "serenity_aistocks_custom_entry_delete"):
            return jsonify({"ok": False, "message": "当前环境不支持自定义股票删除"}), 500
        deleted = db.serenity_aistocks_custom_entry_delete(theme_slug, market, code)
        if not deleted:
            return jsonify({"ok": False, "theme_empty": False, "message": "未找到可删除的自定义股票"})
        workbook = load_serenity_aistocks_workbook()
        theme_exists = any(sheet.get("sheet_slug") == theme_slug for sheet in workbook.get("sheets") or [])
        return jsonify(
            {
                "ok": True,
                "theme_empty": not theme_exists,
                "message": "删除成功",
            }
        )

    @app.route("/serenity/aistocks/stock-search")
    @login_required
    def serenity_aistocks_stock_search():
        query = request.args.get("query")
        exchange = request.args.get("exchange", "a")
        limit_text = request.args.get("limit", "10")
        try:
            limit = int(limit_text)
        except (TypeError, ValueError):
            limit = 10
        return jsonify(
            {
                "results": _search_serenity_aistocks_symbols(
                    query=query or "",
                    exchange=exchange or "a",
                    limit=limit,
                )
            }
        )

    @app.route("/serenity/aistocks/recent-three-buy-times", methods=["POST"])
    @login_required
    def serenity_aistocks_recent_three_buy_times():
        payload = request.get_json(silent=True) or {}
        sheet_slug = _normalize_text(payload.get("sheet_slug"))
        active_task = _get_active_aistocks_scan_task(sheet_slug, "recent_three_buy")
        if active_task:
            return jsonify(
                {
                    "ok": True,
                    "task_id": _normalize_text(active_task.get("task_id")),
                    "task_type": "recent_three_buy",
                    "message": "当前主题已有扫描任务在运行",
                    "reused": True,
                }
            )
        task_id = uuid.uuid4().hex
        items = payload.get("items") or []
        task_snapshot = _set_aistocks_scan_task(
            task_id,
            task_type="recent_three_buy",
            sheet_slug=sheet_slug,
            sheet_name=_normalize_text(payload.get("sheet_name")),
            state="pending",
            message="任务已提交",
            progress=0,
            total_items=len(items),
            processed_items=0,
            hit_count=0,
            miss_count=0,
            partial_hits=[],
            partial_misses=[],
        )
        _set_active_aistocks_scan_task(sheet_slug, "recent_three_buy", task_snapshot)
        _AISTOCKS_SCAN_EXECUTOR.submit(_run_recent_three_buy_scan_task, task_id, items)
        return jsonify(
            {
                "ok": True,
                "task_id": task_id,
                "task_type": "recent_three_buy",
                "message": "3买扫描任务已启动",
                "reused": False,
            }
        )

    @app.route("/serenity/aistocks/recent-three-buy-times/task/<task_id>")
    @login_required
    def serenity_aistocks_recent_three_buy_task(task_id: str):
        task = _get_aistocks_scan_task(task_id)
        if not task or _normalize_text(task.get("task_type")) != "recent_three_buy":
            return jsonify({"ok": False, "message": "任务不存在或已过期"}), 404
        return jsonify({"ok": True, **task})

    @app.route("/serenity/aistocks/recent-beichi-times", methods=["POST"])
    @login_required
    def serenity_aistocks_recent_beichi_times():
        payload = request.get_json(silent=True) or {}
        sheet_slug = _normalize_text(payload.get("sheet_slug"))
        active_task = _get_active_aistocks_scan_task(sheet_slug, "recent_beichi")
        if active_task:
            return jsonify(
                {
                    "ok": True,
                    "task_id": _normalize_text(active_task.get("task_id")),
                    "task_type": "recent_beichi",
                    "message": "当前主题已有扫描任务在运行",
                    "reused": True,
                }
            )
        task_id = uuid.uuid4().hex
        items = payload.get("items") or []
        task_snapshot = _set_aistocks_scan_task(
            task_id,
            task_type="recent_beichi",
            sheet_slug=sheet_slug,
            sheet_name=_normalize_text(payload.get("sheet_name")),
            state="pending",
            message="任务已提交",
            progress=0,
            total_items=len(items),
            processed_items=0,
            hit_count=0,
            miss_count=0,
            partial_hits=[],
            partial_misses=[],
        )
        _set_active_aistocks_scan_task(sheet_slug, "recent_beichi", task_snapshot)
        _AISTOCKS_SCAN_EXECUTOR.submit(_run_recent_beichi_scan_task, task_id, items)
        return jsonify(
            {
                "ok": True,
                "task_id": task_id,
                "task_type": "recent_beichi",
                "message": "背驰扫描任务已启动",
                "reused": False,
            }
        )

    @app.route("/serenity/aistocks/recent-beichi-times/task/<task_id>")
    @login_required
    def serenity_aistocks_recent_beichi_task(task_id: str):
        task = _get_aistocks_scan_task(task_id)
        if not task or _normalize_text(task.get("task_type")) != "recent_beichi":
            return jsonify({"ok": False, "message": "任务不存在或已过期"}), 404
        return jsonify({"ok": True, **task})

    @app.route("/serenity/aistocks/analyze", methods=["POST"])
    @login_required
    def serenity_aistocks_analyze():
        payload = request.get_json(silent=True) or {}
        name = _normalize_text(payload.get("name"))
        code = _normalize_text(payload.get("code"))
        force = bool(payload.get("force"))
        if not name:
            return jsonify({"ok": False, "message": "股票名称不能为空"}), 400

        slug = _analyze_slug(name)
        active_task = _get_active_aistocks_scan_task(slug, _ANALYZE_TASK_TYPE)
        if active_task:
            return jsonify(
                {
                    "ok": True,
                    "task_id": _normalize_text(active_task.get("task_id")),
                    "task_type": _ANALYZE_TASK_TYPE,
                    "message": "该股票已有分析任务在运行",
                    "reused": True,
                }
            )

        task_id = uuid.uuid4().hex
        task_snapshot = _set_aistocks_scan_task(
            task_id,
            task_type=_ANALYZE_TASK_TYPE,
            sheet_slug=slug,
            stock_name=name,
            stock_code=code,
            state="pending",
            message="分析任务已提交",
            progress=0,
        )
        _set_active_aistocks_scan_task(slug, _ANALYZE_TASK_TYPE, task_snapshot)
        _AISTOCKS_SCAN_EXECUTOR.submit(_run_serenity_analyze_task, task_id, name, code, force)
        return jsonify(
            {
                "ok": True,
                "task_id": task_id,
                "task_type": _ANALYZE_TASK_TYPE,
                "message": "分析任务已启动",
                "reused": False,
            }
        )

    @app.route("/serenity/aistocks/analyze/task/<task_id>")
    @login_required
    def serenity_aistocks_analyze_task(task_id: str):
        task = _get_aistocks_scan_task(task_id)
        if not task or _normalize_text(task.get("task_type")) != _ANALYZE_TASK_TYPE:
            return jsonify({"ok": False, "message": "任务不存在或已过期"}), 404
        return jsonify({"ok": True, **task})
