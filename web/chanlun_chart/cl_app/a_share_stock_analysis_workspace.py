from __future__ import annotations

import datetime as dt
from typing import Any

from chanlun.db import db


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    text = _normalize_text(value)
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    text = _normalize_text(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def sync_workspace_stock_analysis_payload(payload: dict[str, Any]) -> dict[str, int]:
    news_inserted = 0
    financial_reports_inserted = 0
    financial_rows_inserted = 0

    for item in payload.get("news_items") or []:
        tags = [
            "workspace",
            "stock-analysis",
            _normalize_text(item.get("entity_type")),
            _normalize_text(item.get("identifier")),
        ]
        news_payload = {
            "story_id": _normalize_text(item.get("story_id")),
            "title": _normalize_text(item.get("title")),
            "body": _normalize_text(item.get("body")),
            "source": _normalize_text(item.get("source")) or "Refinitiv Workspace",
            "published_at": _parse_datetime(item.get("published_at")),
            "language": _normalize_text(item.get("language")) or "zh",
            "tags": ",".join([tag for tag in tags if tag]),
        }
        if db.news_insert(news_payload):
            news_inserted += 1

    for report in payload.get("financial_reports") or []:
        report_date = _parse_date(report.get("report_date"))
        financials = report.get("financials") or []
        if not report_date or not financials:
            continue
        success = db.company_financials_insert(
            code=_normalize_text(report.get("identifier")),
            name=_normalize_text(report.get("company_name")) or _normalize_text(report.get("display_name")),
            statement_type=_normalize_text(report.get("statement_type")) or "Workspace Statement",
            report_date=report_date,
            financials=[
                {
                    "item_name": _normalize_text(item.get("item_name")),
                    "item_value": float(item.get("item_value") or 0),
                }
                for item in financials
                if _normalize_text(item.get("item_name"))
            ],
        )
        if success:
            financial_reports_inserted += 1
            financial_rows_inserted += len(financials)

    return {
        "news_inserted": news_inserted,
        "financial_reports_inserted": financial_reports_inserted,
        "financial_rows_inserted": financial_rows_inserted,
    }
