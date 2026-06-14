#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGI Chat API
提供会话化流式对话接口
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_login import current_user, login_required
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool
from werkzeug.utils import secure_filename

from chanlun.config import get_data_path

from .hermes_bridge import HermesBridge

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat_api", __name__)
ChatBase = declarative_base()


class TableByChatSession(ChatBase):
    __tablename__ = "cl_chat_sessions"

    id = Column(String(40), primary_key=True, comment="会话ID")
    tenant_id = Column(String(64), nullable=False, index=True, comment="租户ID")
    user_id = Column(String(64), nullable=False, index=True, comment="用户ID")
    title = Column(String(200), nullable=False, default="新会话", comment="会话标题")
    context_market = Column(String(20), nullable=True, comment="上下文市场")
    context_code = Column(String(40), nullable=True, comment="上下文标的")
    context_theme = Column(String(80), nullable=True, comment="上下文主题")
    context_json = Column(Text, nullable=True, comment="扩展上下文")
    status = Column(String(20), nullable=False, default="active", index=True, comment="会话状态")
    last_message_at = Column(DateTime, nullable=False, default=datetime.datetime.now, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now, index=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
        index=True,
    )
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByChatMessage(ChatBase):
    __tablename__ = "cl_chat_messages"

    id = Column(String(40), primary_key=True, comment="消息ID")
    tenant_id = Column(String(64), nullable=False, index=True, comment="租户ID")
    user_id = Column(String(64), nullable=False, index=True, comment="用户ID")
    session_id = Column(String(40), nullable=False, index=True, comment="会话ID")
    role = Column(String(20), nullable=False, index=True, comment="角色")
    message_type = Column(String(32), nullable=False, default="assistant_text", index=True, comment="消息类型")
    content = Column(Text, nullable=True, comment="消息内容")
    structured_payload = Column(Text, nullable=True, comment="结构化内容")
    tool_name = Column(String(80), nullable=True, comment="工具名称")
    trace_id = Column(String(64), nullable=True, index=True, comment="调用链追踪ID")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now, index=True)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


class TableByChatAttachment(ChatBase):
    __tablename__ = "cl_chat_attachments"

    id = Column(String(40), primary_key=True, comment="附件ID")
    tenant_id = Column(String(64), nullable=False, index=True, comment="租户ID")
    user_id = Column(String(64), nullable=False, index=True, comment="用户ID")
    session_id = Column(String(40), nullable=False, index=True, comment="会话ID")
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    file_type = Column(String(32), nullable=True, comment="文件类型")
    storage_path = Column(Text, nullable=False, comment="存储路径")
    file_size = Column(Integer, nullable=False, default=0, comment="文件大小")
    parse_status = Column(String(20), nullable=False, default="stored", index=True, comment="解析状态")
    parsed_text = Column(Text, nullable=True, comment="解析文本")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now, index=True)
    __table_args__ = {"mysql_collate": "utf8mb4_general_ci"}


_CHAT_SESSION_FACTORY = None
_agent = None
_MEMORY_ENTRY_DELIMITER = "\n§\n"


def _get_chat_session_factory():
    global _CHAT_SESSION_FACTORY
    if _CHAT_SESSION_FACTORY is not None:
        return _CHAT_SESSION_FACTORY

    db_dir = get_data_path() / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "chat_sessions.sqlite"

    try:
        engine = create_engine(
            f"sqlite:///{str(db_path)}",
            echo=False,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_timeout=10,
        )
        ChatBase.metadata.create_all(engine)
        _CHAT_SESSION_FACTORY = sessionmaker(bind=engine)
    except Exception as e:
        logger.warning(f"初始化聊天存储失败，回退到内存数据库: {e}")
        engine = create_engine("sqlite:///:memory:", echo=False)
        ChatBase.metadata.create_all(engine)
        _CHAT_SESSION_FACTORY = sessionmaker(bind=engine)
    return _CHAT_SESSION_FACTORY


def get_agent():
    global _agent
    if _agent is None:
        _agent = HermesBridge()
    return _agent


def _json_dumps(value: Any) -> Optional[str]:
    if value in (None, "", [], {}):
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str]) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _build_uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _derive_session_title(text: str) -> str:
    normalized = " ".join((text or "").strip().split())
    if not normalized:
        return "新会话"
    return normalized[:24]


def _infer_context_from_text(text: str) -> Dict[str, str]:
    content = str(text or "").strip()
    if not content:
        return {}

    explicit_match = re.search(
        r"\b(a|hk|us|fx|futures|ny_futures|currency|currency_spot)\s*[:：]\s*([a-zA-Z0-9._-]+)",
        content,
        re.IGNORECASE,
    )
    if explicit_match:
        return {
            "market": explicit_match.group(1).lower(),
            "code": explicit_match.group(2).upper(),
        }

    compact = re.sub(r"\s+", "", content)
    slash_fx_match = re.search(r"\b([A-Za-z]{3})/([A-Za-z]{3})\b", compact)
    if slash_fx_match:
        return {
            "market": "fx",
            "code": f"{slash_fx_match.group(1)}{slash_fx_match.group(2)}".upper(),
        }

    currency_codes = {"AUD", "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "NZD", "CNH", "CNY", "HKD", "SGD"}
    fx_pair_match = re.search(r"\b([A-Z]{6})\b", content.upper())
    if fx_pair_match:
        pair = fx_pair_match.group(1)
        if pair[:3] in currency_codes and pair[3:] in currency_codes:
            return {"market": "fx", "code": pair}

    a_share_match = re.search(r"\b(?:SH|SZ)?\.?(\d{6})\b", content, re.IGNORECASE)
    if a_share_match:
        return {"market": "a", "code": a_share_match.group(1)}

    return {}


def _resolve_request_context(
    session_row: Optional[TableByChatSession],
    request_context: Optional[Dict[str, Any]],
    text: str,
) -> Dict[str, Any]:
    merged_context: Dict[str, Any] = {}
    if session_row is not None:
        merged_context.update(_json_loads(session_row.context_json) or {})
        if session_row.context_market and "market" not in merged_context:
            merged_context["market"] = session_row.context_market
        if session_row.context_code and "code" not in merged_context:
            merged_context["code"] = session_row.context_code
        if session_row.context_theme and "theme" not in merged_context:
            merged_context["theme"] = session_row.context_theme

    merged_context.update(
        {
            key: value
            for key, value in (request_context or {}).items()
            if value not in (None, "")
        }
    )

    inferred_context = _infer_context_from_text(text)
    if inferred_context:
        merged_context.update(
            {
                key: value
                for key, value in inferred_context.items()
                if value not in (None, "")
            }
        )

    return merged_context


def _current_identity() -> Dict[str, str]:
    tenant_id = str(request.headers.get("X-Tenant-Id") or "default").strip() or "default"
    user_id = ""
    if getattr(current_user, "is_authenticated", False):
        user_id = str(current_user.get_id() or "").strip()
    user_id = str(request.headers.get("X-User-Id") or user_id or "cl_pro").strip()
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
    }


def _serialize_session(row: TableByChatSession) -> Dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "title": row.title,
        "context_market": row.context_market,
        "context_code": row.context_code,
        "context_theme": row.context_theme,
        "context": _json_loads(row.context_json) or {},
        "status": row.status,
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_message(row: TableByChatMessage) -> Dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "role": row.role,
        "message_type": row.message_type,
        "content": row.content or "",
        "structured_payload": _json_loads(row.structured_payload) or {},
        "tool_name": row.tool_name,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_attachment(row: TableByChatAttachment) -> Dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "file_name": row.file_name,
        "file_type": row.file_type,
        "file_size": row.file_size,
        "parse_status": row.parse_status,
        "parsed_text_preview": (row.parsed_text or "")[:500],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _get_session_row(session_id: str, tenant_id: str, user_id: str) -> Optional[TableByChatSession]:
    with _get_chat_session_factory()() as session:
        return (
            session.query(TableByChatSession)
            .filter(
                TableByChatSession.id == session_id,
                TableByChatSession.tenant_id == tenant_id,
                TableByChatSession.user_id == user_id,
            )
            .first()
        )


def _list_session_rows(tenant_id: str, user_id: str, limit: int = 30) -> List[TableByChatSession]:
    with _get_chat_session_factory()() as session:
        return (
            session.query(TableByChatSession)
            .filter(
                TableByChatSession.tenant_id == tenant_id,
                TableByChatSession.user_id == user_id,
            )
            .order_by(TableByChatSession.last_message_at.desc(), TableByChatSession.updated_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )


def _list_message_rows(session_id: str, tenant_id: str, user_id: str, limit: int = 200) -> List[TableByChatMessage]:
    with _get_chat_session_factory()() as session:
        return (
            session.query(TableByChatMessage)
            .filter(
                TableByChatMessage.session_id == session_id,
                TableByChatMessage.tenant_id == tenant_id,
                TableByChatMessage.user_id == user_id,
            )
            .order_by(TableByChatMessage.created_at.asc())
            .limit(max(1, min(limit, 500)))
            .all()
        )


def _list_attachment_rows(session_id: str, tenant_id: str, user_id: str, limit: int = 50) -> List[TableByChatAttachment]:
    with _get_chat_session_factory()() as session:
        return (
            session.query(TableByChatAttachment)
            .filter(
                TableByChatAttachment.session_id == session_id,
                TableByChatAttachment.tenant_id == tenant_id,
                TableByChatAttachment.user_id == user_id,
            )
            .order_by(TableByChatAttachment.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )


def _create_session_row(
    tenant_id: str,
    user_id: str,
    title: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> TableByChatSession:
    context = context or {}
    session_id = _build_uid("sess")
    now = datetime.datetime.now()
    with _get_chat_session_factory()() as session:
        row = TableByChatSession(
            id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title or "新会话",
            context_market=context.get("market"),
            context_code=context.get("code"),
            context_theme=context.get("theme"),
            context_json=_json_dumps(context),
            status="active",
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def _touch_session_row(
    session_id: str,
    tenant_id: str,
    user_id: str,
    text: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    context = context or {}
    now = datetime.datetime.now()
    with _get_chat_session_factory()() as session:
        row = (
            session.query(TableByChatSession)
            .filter(
                TableByChatSession.id == session_id,
                TableByChatSession.tenant_id == tenant_id,
                TableByChatSession.user_id == user_id,
            )
            .first()
        )
        if row is None:
            return
        if text and (not row.title or row.title == "新会话"):
            row.title = _derive_session_title(text)
        if context.get("market"):
            row.context_market = context.get("market")
        if context.get("code"):
            row.context_code = context.get("code")
        if context.get("theme"):
            row.context_theme = context.get("theme")
        if context:
            merged_context = _json_loads(row.context_json) or {}
            merged_context.update({k: v for k, v in context.items() if v not in (None, "")})
            row.context_json = _json_dumps(merged_context)
        row.last_message_at = now
        row.updated_at = now
        session.commit()


def _delete_session_row(session_id: str, tenant_id: str, user_id: str) -> bool:
    attachment_paths: List[str] = []
    with _get_chat_session_factory()() as session:
        row = (
            session.query(TableByChatSession)
            .filter(
                TableByChatSession.id == session_id,
                TableByChatSession.tenant_id == tenant_id,
                TableByChatSession.user_id == user_id,
            )
            .first()
        )
        if row is None:
            return False
        attachment_rows = (
            session.query(TableByChatAttachment)
            .filter(
                TableByChatAttachment.session_id == session_id,
                TableByChatAttachment.tenant_id == tenant_id,
                TableByChatAttachment.user_id == user_id,
            )
            .all()
        )
        attachment_paths = [str(item.storage_path or "").strip() for item in attachment_rows if str(item.storage_path or "").strip()]
        session.query(TableByChatMessage).filter(
            TableByChatMessage.session_id == session_id,
            TableByChatMessage.tenant_id == tenant_id,
            TableByChatMessage.user_id == user_id,
        ).delete()
        session.query(TableByChatAttachment).filter(
            TableByChatAttachment.session_id == session_id,
            TableByChatAttachment.tenant_id == tenant_id,
            TableByChatAttachment.user_id == user_id,
        ).delete()
        session.delete(row)
        session.commit()

    for file_path in attachment_paths:
        try:
            path_obj = Path(file_path)
            if path_obj.exists():
                path_obj.unlink()
            parent_dir = path_obj.parent
            while parent_dir != get_data_path() and parent_dir.exists():
                try:
                    parent_dir.rmdir()
                except OSError:
                    break
                parent_dir = parent_dir.parent
        except Exception:
            logger.warning(f"删除会话附件文件失败: {file_path}", exc_info=True)
    return True


def _insert_message_row(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    message_type: str,
    structured_payload: Optional[Dict[str, Any]] = None,
    tool_name: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = datetime.datetime.now()
    with _get_chat_session_factory()() as session:
        row = TableByChatMessage(
            id=_build_uid("msg"),
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            message_type=message_type,
            content=content,
            structured_payload=_json_dumps(structured_payload),
            tool_name=tool_name,
            trace_id=trace_id,
            created_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize_message(row)


def _extract_text_from_upload(file_name: str, content: bytes) -> tuple[str, str]:
    suffix = os.path.splitext(file_name or "")[-1].lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".ts"}:
        try:
            text = content.decode("utf-8")
            return "parsed", text[:20000]
        except Exception:
            return "stored", ""
    return "stored", ""


def _store_attachment_row(
    session_id: str,
    tenant_id: str,
    user_id: str,
    file_name: str,
    content: bytes,
) -> Dict[str, Any]:
    upload_dir = get_data_path() / "chat_uploads" / tenant_id / user_id / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    attachment_id = _build_uid("att")
    safe_name = secure_filename(file_name or "attachment")
    storage_name = f"{attachment_id}_{safe_name}"
    storage_path = upload_dir / storage_name
    storage_path.write_bytes(content)
    parse_status, parsed_text = _extract_text_from_upload(file_name, content)
    with _get_chat_session_factory()() as session:
        row = TableByChatAttachment(
            id=attachment_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            file_name=file_name or safe_name,
            file_type=os.path.splitext(file_name or "")[-1].lstrip(".").lower(),
            storage_path=str(storage_path),
            file_size=len(content or b""),
            parse_status=parse_status,
            parsed_text=parsed_text,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize_attachment(row)


def _build_agent_messages(history_rows: List[TableByChatMessage]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    for row in history_rows:
        if row.role not in {"user", "assistant"}:
            continue
        if row.message_type not in {"user_text", "assistant_text", "analysis_summary"}:
            continue
        content = str(row.content or "").strip()
        if not content:
            continue
        messages.append({"role": row.role, "content": content})
    return messages[-24:]


def _build_attachment_context_rows(session_id: str, tenant_id: str, user_id: str) -> List[Dict[str, Any]]:
    attachment_rows = _list_attachment_rows(session_id, tenant_id, user_id, limit=10)
    items: List[Dict[str, Any]] = []
    for row in attachment_rows:
        items.append(
            {
                "file_name": row.file_name,
                "file_type": row.file_type,
                "parse_status": row.parse_status,
                "parsed_text_preview": (row.parsed_text or "")[:1200],
            }
        )
    return items


def _append_attachment_context(
    agent_messages: List[Dict[str, str]],
    attachment_items: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    if not attachment_items:
        return agent_messages
    lines = ["[会话附件证据]"]
    for idx, item in enumerate(attachment_items[:5], start=1):
        lines.append(
            f"{idx}. 文件: {item.get('file_name') or ''} ({item.get('file_type') or 'unknown'})"
        )
        preview = str(item.get("parsed_text_preview") or "").strip()
        if preview:
            lines.append(preview[:600])
    context_message = {"role": "user", "content": "\n".join(lines)}
    if agent_messages:
        return agent_messages[:-1] + [context_message, agent_messages[-1]]
    return [context_message]


def _format_structured_analysis_result(
    analysis_type: str,
    result: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    summary = str(result.get("summary") or "").strip()
    if analysis_type == "theme_simulation":
        assistant_text = "市场观点已整理好。"
    elif analysis_type == "market_data_view":
        assistant_text = "价格图已准备好。"
    elif analysis_type == "historical_analysis":
        assistant_text = "历史回顾已整理好。"
    elif analysis_type == "drawdown_analysis":
        assistant_text = "回撤分析已整理好。"
    elif analysis_type == "event_chart_review":
        assistant_text = "历史事件图已整理好。"
    elif analysis_type == "db_latest_news":
        news_items = result.get("news_items") or []
        assistant_text = "最新重点新闻已整理好。" if news_items else "暂时没有更相关的重点新闻。"
    elif analysis_type == "db_report_lookup":
        report_items = result.get("report_items") or []
        assistant_text = "相关研究已整理好。" if report_items else "暂时没有找到更相关的研究。"
    elif analysis_type == "skill_create":
        assistant_text = "技能已创建。"
    else:
        assistant_text = summary or "分析已完成。"

    structured_payload = {
        "analysis_type": analysis_type,
        "result": result,
        "summary": summary,
    }
    return assistant_text, structured_payload


def _build_chart_cards(
    context: Dict[str, Any],
    analysis_type: str = "chat",
) -> List[Dict[str, Any]]:
    current_market = str(context.get("market") or context.get("current_market") or "").strip()
    current_code = str(context.get("code") or context.get("current_code") or "").strip()
    if not current_market or not current_code:
        return []
    frequency = str(context.get("frequency") or "30m").strip() or "30m"
    homepage_url = f"/?market={current_market}&code={current_code}&embedded=1"
    db_chart_url = f"/chart?market={current_market}&code={current_code}&frequency={frequency}"
    preferred_source = "db" if analysis_type in {"theme_simulation", "historical_analysis", "event_chart_review"} else "home"
    return [
        {
            "type": "price_chart",
            "title": f"{current_code} 价格图形",
            "market": current_market,
            "code": current_code,
            "frequency": frequency,
            "homepage_url": homepage_url,
            "db_chart_url": db_chart_url,
            "preferred_source": preferred_source,
        }
    ]


def _build_relevance_terms(text: str, context: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    for value in [
        context.get("market"),
        context.get("code"),
        context.get("theme"),
        text,
    ]:
        raw = str(value or "").strip()
        if not raw:
            continue
        terms.append(raw)
        terms.extend(re.findall(r"[A-Za-z]{3,12}|[\u4e00-\u9fff]{2,12}", raw))
    cleaned: List[str] = []
    ignored = {"看", "一下", "最新", "重要", "新闻", "报告", "研究", "图", "价格", "交易"}
    for term in terms:
        normalized = str(term).strip()
        if not normalized or normalized in ignored:
            continue
        if normalized.lower() in ignored:
            continue
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned[:12]


def _query_latest_db_news(text: str, context: Dict[str, Any], limit: int = 5) -> Dict[str, Any]:
    from cl_app import news_vector_api

    search_terms = _build_relevance_terms(text, context)
    query = str(context.get("code") or context.get("theme") or text or "").strip()
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=14)
    news_items = news_vector_api._search_news_from_relational_db(
        query=query,
        search_terms=search_terms,
        start_date=start_date,
        end_date=end_date,
        n_results=limit,
    )
    return {
        "summary": f"已从数据库找到 {len(news_items)} 条最新相关重要新闻" if news_items else "数据库里暂未找到最新相关重要新闻",
        "news_items": news_items,
        "source": "db_only",
    }


def _query_existing_market_reports(text: str, context: Dict[str, Any], limit: int = 5) -> Dict[str, Any]:
    from chanlun.db import db

    market = str(context.get("market") or "").strip() or None
    code = str(context.get("code") or "").strip() or None
    search_terms = _build_relevance_terms(text, context)
    rows = db.market_summary_query(limit=60, market=market, code=code)

    report_items: List[Dict[str, Any]] = []
    for row in rows:
        summary_type = str(getattr(row, "summary_type", "") or "")
        if summary_type not in {"market_analysis", "historical_analysis", "daily_news_summary"}:
            continue
        title = str(getattr(row, "title", "") or "")
        content = str(getattr(row, "content", "") or "")
        haystack = f"{title}\n{content}"
        score = 0.0
        if market and str(getattr(row, "market", "") or "") == market:
            score += 4.0
        if code and str(getattr(row, "code", "") or "").upper() == code.upper():
            score += 6.0
        for term in search_terms:
            if term and term.lower() in haystack.lower():
                score += 1.5
        created_at = getattr(row, "created_at", None)
        if created_at:
            age_days = max(0.0, (datetime.datetime.now() - created_at).total_seconds() / 86400.0)
            score += max(0.0, 5.0 - min(age_days, 5.0))
        if not market and not code and score <= 0:
            continue
        preview = re.sub(r"\s+", " ", content).strip() or title
        if len(preview) > 220:
            preview = preview[:220] + "..."
        report_items.append(
            {
                "summary_id": getattr(row, "id", None),
                "title": title or "研究报告",
                "summary_type": summary_type,
                "market": str(getattr(row, "market", "") or ""),
                "code": str(getattr(row, "code", "") or ""),
                "created_at": created_at.isoformat() if created_at else "",
                "preview": preview,
                "score": round(score, 4),
            }
        )

    report_items.sort(key=lambda item: (item.get("score", 0.0), item.get("created_at", "")), reverse=True)
    report_items = report_items[:limit]
    return {
        "summary": f"已从数据库找到 {len(report_items)} 份相关研究报告" if report_items else "数据库里暂未找到相关研究报告",
        "report_items": report_items,
        "source": "db_only",
    }


def _extract_lookback_hours(text: str, default: int = 72) -> int:
    normalized = str(text or "").lower()
    if not normalized:
        return default

    digit_match = re.search(r"(\d+)\s*(年|个月|月|周|天|日|小时|h|hour)", normalized)
    if digit_match:
        value = max(int(digit_match.group(1)), 1)
        unit = digit_match.group(2)
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
    if "一季" in normalized:
        return 24 * 90
    if "一月" in normalized or "一个月" in normalized:
        return 24 * 30
    if "一周" in normalized:
        return 24 * 7
    if "三天" in normalized:
        return 24 * 3
    if "两天" in normalized:
        return 48
    if "一天" in normalized or "今日" in normalized or "今天" in normalized:
        return 24
    return default


def _infer_analysis_frequency(context: Dict[str, Any], lookback_hours: int, preferred: str = "") -> str:
    preferred_value = str(preferred or context.get("frequency") or "").strip().lower()
    if preferred_value:
        return preferred_value
    if lookback_hours >= 24 * 180:
        return "1d"
    if lookback_hours >= 24 * 30:
        return "240m"
    if lookback_hours >= 24 * 7:
        return "60m"
    if lookback_hours >= 24:
        return "15m"
    return "5m"


def _query_drawdown_analysis(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    from cl_app import news_vector_api

    current_market = str(context.get("market") or "").strip()
    current_code = str(context.get("code") or "").strip().upper()
    if not current_market or not current_code:
        raise ValueError("缺少市场或标的代码")

    requested_hours = _extract_lookback_hours(text, default=24 * 30)
    lookback_hours = max(24, min(requested_hours, 24 * 365))
    frequency = _infer_analysis_frequency(context, lookback_hours)
    price_bars = news_vector_api._load_historical_price_bars(
        market=current_market,
        code=current_code,
        frequency=frequency,
        lookback_hours=lookback_hours,
        purpose="回撤分析",
    )
    if len(price_bars) < 10:
        raise ValueError("历史价格数据不足，暂时无法生成回撤分析")

    closes = []
    for bar in price_bars:
        close_value = news_vector_api._safe_float(bar.get("close"))
        open_value = news_vector_api._safe_float(bar.get("open"))
        price_value = close_value if close_value > 0 else open_value
        if price_value > 0:
            closes.append({"dt": bar.get("dt"), "price": price_value})
    if len(closes) < 10:
        raise ValueError("历史价格数据不足，暂时无法生成回撤分析")

    peak_index = 0
    trough_index = 0
    peak_price = closes[0]["price"]
    max_drawdown_pct = 0.0
    for idx, item in enumerate(closes):
        price_value = item["price"]
        if price_value >= peak_price:
            peak_price = price_value
            peak_index = idx
        drawdown_pct = 0.0
        if peak_price > 0:
            drawdown_pct = (price_value / peak_price - 1.0) * 100.0
        if drawdown_pct < max_drawdown_pct:
            max_drawdown_pct = drawdown_pct
            trough_index = idx

    peak_point = closes[peak_index]
    trough_point = closes[trough_index]
    recovery_index = None
    for idx in range(trough_index + 1, len(closes)):
        if closes[idx]["price"] >= peak_point["price"]:
            recovery_index = idx
            break
    recovery_point = closes[recovery_index] if recovery_index is not None else None

    start_point = closes[0]
    latest_point = closes[-1]
    period_return_pct = ((latest_point["price"] / start_point["price"]) - 1.0) * 100.0 if start_point["price"] else 0.0
    recovery_hours = None
    if recovery_point and isinstance(recovery_point["dt"], datetime.datetime) and isinstance(trough_point["dt"], datetime.datetime):
        recovery_hours = round((recovery_point["dt"] - trough_point["dt"]).total_seconds() / 3600.0, 2)

    related_news = _query_latest_db_news(text, context, limit=3).get("news_items", [])
    report_items = _query_existing_market_reports(text, context, limit=2).get("report_items", [])
    lookback_label = f"{int(lookback_hours / 24)}天" if lookback_hours >= 24 else f"{lookback_hours}小时"
    summary = (
        f"{current_code} 在最近{lookback_label}内的最大回撤为 {abs(max_drawdown_pct):.2f}%"
        + (f"，目前已在 {recovery_hours:.1f} 小时内修复高点。" if recovery_hours is not None else "，目前尚未完全修复前高。")
    )
    return {
        "summary": summary,
        "lookback_hours": lookback_hours,
        "lookback_label": lookback_label,
        "frequency": frequency,
        "max_drawdown_pct": round(abs(max_drawdown_pct), 4),
        "period_return_pct": round(period_return_pct, 4),
        "drawdown": {
            "peak_dt": peak_point["dt"].isoformat() if hasattr(peak_point["dt"], "isoformat") else str(peak_point["dt"]),
            "peak_price": round(peak_point["price"], 6),
            "trough_dt": trough_point["dt"].isoformat() if hasattr(trough_point["dt"], "isoformat") else str(trough_point["dt"]),
            "trough_price": round(trough_point["price"], 6),
            "recovery_dt": recovery_point["dt"].isoformat() if recovery_point and hasattr(recovery_point["dt"], "isoformat") else "",
            "recovery_price": round(recovery_point["price"], 6) if recovery_point else None,
            "recovery_hours": recovery_hours,
            "latest_dt": latest_point["dt"].isoformat() if hasattr(latest_point["dt"], "isoformat") else str(latest_point["dt"]),
            "latest_price": round(latest_point["price"], 6),
        },
        "news_items": related_news,
        "report_items": report_items,
    }


def _query_event_chart_review(text: str, context: Dict[str, Any], identity: Dict[str, str], session_id: str) -> Dict[str, Any]:
    from cl_app import news_vector_api

    current_market = str(context.get("market") or "").strip()
    current_code = str(context.get("code") or "").strip().upper()
    if not current_market or not current_code:
        raise ValueError("缺少市场或标的代码")

    requested_hours = _extract_lookback_hours(text, default=48)
    lookback_hours = max(12, min(requested_hours, 72))
    frequency = _infer_analysis_frequency(context, lookback_hours, preferred="5m" if lookback_hours <= 24 else "15m")
    payload = {
        "current_market": current_market,
        "current_code": current_code,
        "theme_label": context.get("theme") or text,
        "theme_text": text,
        "query": text,
        "lookback_hours": lookback_hours,
        "event_frequency": frequency,
        "tenant_id": identity["tenant_id"],
        "user_id": identity["user_id"],
        "session_id": session_id,
        "request_source": "web_chat",
    }
    result = news_vector_api._generate_historical_analysis_payload(payload)
    events = list(result.get("events") or [])[:3]
    similar_events = list(result.get("similar_events") or [])[:3]
    event_trade_templates = list(result.get("event_trade_templates") or [])[:3]
    report_items = _query_existing_market_reports(text, context, limit=2).get("report_items", [])
    event_summary = f"已整理最近{result.get('lookback_label') or f'{lookback_hours}小时'}内 {len(events)} 个关键事件窗口"
    if similar_events:
        event_summary += f"，并补充 {len(similar_events)} 个相似历史样本"
    return {
        "summary": event_summary,
        "summary_id": result.get("summary_id"),
        "lookback_hours": lookback_hours,
        "lookback_label": result.get("lookback_label") or f"{lookback_hours}小时",
        "event_frequency": result.get("event_frequency") or frequency,
        "events": events,
        "similar_events": similar_events,
        "event_trade_templates": event_trade_templates,
        "trader_decision": result.get("trader_decision") or {},
        "timesfm_forecast": result.get("timesfm_forecast") or {},
        "report_items": report_items,
    }


def _build_skill_suggestion(text: str, context: Dict[str, Any], analysis_type: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    code = str(context.get("code") or result.get("code") or "市场").strip().upper() or "市场"
    if analysis_type == "drawdown_analysis":
        return {
            "title": f"{code} 回撤复盘助手",
            "name": f"{code} 回撤复盘助手",
            "description": f"固定按回撤、恢复周期、相关新闻和已有研究复盘 {code}",
            "instructions": (
                f"当用户要求复盘 {code} 的回撤或风险时，先检查当前标的上下文，"
                "输出最大回撤、峰值与低点时间、是否修复前高，再补充相关新闻、已有研究和下一步风险提示。"
            ),
            "reason": "这类风险复盘流程很适合沉淀成可复用技能。",
        }
    if analysis_type in {"event_chart_review", "historical_analysis"}:
        return {
            "title": f"{code} 历史事件图助手",
            "name": f"{code} 历史事件图助手",
            "description": f"固定按事件窗口、相似样本和交易模板复盘 {code}",
            "instructions": (
                f"当用户查看 {code} 的历史事件图或历史事件回顾时，"
                "先整理关键事件窗口，再补充相似历史样本、事件后续演化和可执行交易模板，最后给出风险提示。"
            ),
            "reason": "如果你会反复查看事件图，这个技能可以直接复用整套流程。",
        }
    if analysis_type == "theme_simulation" and any(keyword in str(text or "") for keyword in ["以后", "每次", "默认", "按这个"]):
        return {
            "title": f"{code} 研究模板",
            "name": f"{code} 研究模板",
            "description": f"固定按你的偏好输出 {code} 的研究结论、证据、风险和动作",
            "instructions": (
                f"当用户要求分析 {code} 时，优先调用相关研究与图表能力，"
                "并按结论、证据、风险、动作四段结构输出。"
            ),
            "reason": "你刚刚表达了固定分析模板的意图，适合直接保存成技能。",
        }
    return None


def _build_trading_brief(analysis_type: str, context: Dict[str, Any], result: Dict[str, Any]) -> Optional[Dict[str, str]]:
    code = str(context.get("code") or result.get("code") or "当前标的").strip().upper() or "当前标的"
    if analysis_type == "drawdown_analysis":
        drawdown = result.get("drawdown") or {}
        max_drawdown = float(result.get("max_drawdown_pct") or 0.0)
        recovery_hours = drawdown.get("recovery_hours")
        return {
            "conclusion": f"{code} 最近阶段最大回撤约 {max_drawdown:.2f}%。",
            "evidence": (
                f"峰值在 {drawdown.get('peak_dt') or '--'}，低点在 {drawdown.get('trough_dt') or '--'}，"
                + (
                    f"低点后约 {float(recovery_hours):.1f} 小时修复前高。"
                    if recovery_hours not in (None, "")
                    else "目前尚未完全修复前高。"
                )
            ),
            "risk": "若再次接近前低且没有新的驱动修复，短线风险可能继续放大。",
            "action": "先看图确认回撤区间，再结合新闻与已有研究决定是否交易。",
        }
    if analysis_type == "event_chart_review":
        events = list(result.get("events") or [])
        similar_events = list(result.get("similar_events") or [])
        return {
            "conclusion": f"{code} 的历史事件图已整理，可直接用事件模板复盘。",
            "evidence": f"本次覆盖 {len(events)} 个关键事件窗口，并补充 {len(similar_events)} 个相似历史样本。",
            "risk": "历史相似不代表当前必然复制，事件节奏和宏观背景仍可能不同。",
            "action": "先看事件窗口与相似样本，再决定是否保存为常用事件分析技能。",
        }
    if analysis_type == "historical_analysis":
        event_count = int(result.get("event_count") or len(result.get("events") or []))
        return {
            "conclusion": f"{code} 的历史复盘已整理，可直接用来判断当前阶段位置。",
            "evidence": f"本次共提炼 {event_count} 个关键波动事件，并生成对应研究结论。",
            "risk": "历史复盘更适合辅助判断，不应替代当前盘面的实时验证。",
            "action": "结合当前价格图与事件主线，继续追问下一步交易偏向。",
        }
    if analysis_type == "theme_simulation":
        report = result.get("report") or {}
        trade_bias = report.get("trade_bias") or report.get("direction") or "已有观点输出"
        return {
            "conclusion": f"{code} 的研究观点已形成，当前偏向：{trade_bias}。",
            "evidence": str(result.get("summary") or "已汇总当前市场观点、研究与图表信号。").strip(),
            "risk": "主题推演依赖当前新闻与定价环境，驱动变化后需要重新评估。",
            "action": "查看图表与已有研究后，再决定是否直接跳转交易页面。",
        }
    if analysis_type == "market_data_view":
        return {
            "conclusion": f"{code} 的价格图与市场快照已准备好。",
            "evidence": str(result.get("summary") or "已加载当前标的价格图、盘面与相关入口。").strip(),
            "risk": "单看图形容易忽略消息面与历史背景，盘中波动也可能较快。",
            "action": "继续追问新闻、研究或历史事件，再决定是否交易。",
        }
    if analysis_type == "db_latest_news":
        news_items = list(result.get("news_items") or [])
        headlines = [str((item.get("metadata") or {}).get("title") or item.get("title") or "").strip() for item in news_items[:2]]
        return {
            "conclusion": f"{code} 的最新重点新闻已整理。",
            "evidence": "；".join([item for item in headlines if item]) or "已整理最新相关重要新闻。",
            "risk": "新闻影响存在时滞，且同一条新闻在不同阶段的市场反应可能不同。",
            "action": "先看新闻对应的价格图反应，再决定是否继续看研究或交易。",
        }
    if analysis_type == "db_report_lookup":
        report_items = list(result.get("report_items") or [])
        titles = [str(item.get("title") or "").strip() for item in report_items[:2]]
        return {
            "conclusion": f"{code} 的相关研究已找到。",
            "evidence": "；".join([item for item in titles if item]) or "已整理数据库里的相关研究。",
            "risk": "已有报告代表过去判断，使用前仍需结合当前盘面验证。",
            "action": "先看已有研究，再补一轮最新图表和新闻确认是否仍然有效。",
        }
    return None


def _count_recent_analysis_matches(identity: Dict[str, str], session_id: str, analysis_type: str, code: str = "") -> int:
    rows = _list_message_rows(session_id, identity["tenant_id"], identity["user_id"], limit=24)
    target_code = str(code or "").strip().upper()
    count = 0
    for row in reversed(rows):
        if row.message_type != "analysis_summary":
            continue
        payload = _json_loads(row.structured_payload) or {}
        if str(payload.get("analysis_type") or "") != analysis_type:
            continue
        if target_code:
            payload_code = str(((payload.get("result") or {}).get("code")) or "").strip().upper()
            if not payload_code:
                charts = payload.get("charts") or []
                if charts:
                    payload_code = str((charts[0] or {}).get("code") or "").strip().upper()
            if payload_code and payload_code != target_code:
                continue
        count += 1
        if count >= 3:
            return count
    return count


def _build_repeat_skill_suggestion(
    identity: Dict[str, str],
    session_id: str,
    context: Dict[str, Any],
    analysis_type: str,
    result: Dict[str, Any],
    base_suggestion: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    code = str(context.get("code") or result.get("code") or "").strip().upper()
    repeat_count = _count_recent_analysis_matches(identity, session_id, analysis_type, code)
    if repeat_count < 2:
        return base_suggestion
    suggestion = dict(base_suggestion or {})
    if not suggestion:
        title = f"{code or '市场'} 常用分析助手"
        suggestion = {
            "title": title,
            "name": title,
            "description": f"保存你最近高频使用的 {analysis_type} 工作流",
            "instructions": (
                f"当用户再次请求 {code or '当前标的'} 的 {analysis_type} 相关分析时，"
                "复用当前会话常见的分析步骤与输出结构，并保持结论、证据、风险、动作四段式输出。"
            ),
        }
    suggestion["reason"] = f"你最近已经多次执行这类分析，适合保存成技能，下次可以直接复用。"
    suggestion["repeat_count"] = repeat_count + 1
    return suggestion


def _run_analysis_request(
    analysis_type: str,
    text: str,
    context: Dict[str, Any],
    identity: Dict[str, str],
    session_id: str,
) -> tuple[str, Dict[str, Any]]:
    from cl_app import news_vector_api

    payload = {
        "current_market": context.get("market") or "",
        "current_code": context.get("code") or "",
        "theme_label": context.get("theme") or text,
        "theme_text": text,
        "tenant_id": identity["tenant_id"],
        "user_id": identity["user_id"],
        "session_id": session_id,
        "request_source": "web_chat",
    }
    if analysis_type == "theme_simulation":
        result = news_vector_api._generate_theme_simulation_payload(payload)
        existing_reports = _query_existing_market_reports(text, context, limit=3).get("report_items", [])
        if existing_reports:
            result["existing_reports"] = existing_reports
    elif analysis_type == "market_data_view":
        result = news_vector_api._build_market_data_view_payload(
            str(payload.get("current_market") or ""),
            str(payload.get("current_code") or ""),
            8,
        )
    elif analysis_type == "db_latest_news":
        result = _query_latest_db_news(text, context, limit=5)
    elif analysis_type == "db_report_lookup":
        result = _query_existing_market_reports(text, context, limit=5)
    elif analysis_type == "historical_analysis":
        result = news_vector_api._generate_historical_analysis_payload(payload)
    elif analysis_type == "drawdown_analysis":
        result = _query_drawdown_analysis(text, context)
    elif analysis_type == "event_chart_review":
        result = _query_event_chart_review(text, context, identity, session_id)
    elif analysis_type == "skill_create":
        skill = _create_skill(
            identity,
            {
                "name": context.get("theme") or text,
                "description": context.get("skill_description") or f"从聊天中创建的技能：{text[:32]}",
                "instructions": text,
                "session_id": session_id,
            },
        )
        result = {
            "summary": f"已创建技能 {skill['title']}",
            "skill": skill,
        }
    else:
        raise ValueError(f"不支持的分析类型: {analysis_type}")
    assistant_text, structured_payload = _format_structured_analysis_result(analysis_type, result)
    trading_brief = _build_trading_brief(analysis_type, context, result)
    if trading_brief:
        structured_payload["trading_brief"] = trading_brief
    skill_suggestion = _build_skill_suggestion(text, context, analysis_type, result)
    skill_suggestion = _build_repeat_skill_suggestion(identity, session_id, context, analysis_type, result, skill_suggestion)
    if skill_suggestion:
        structured_payload["skill_suggestion"] = skill_suggestion
    return assistant_text, structured_payload


def _auto_detect_analysis_type(text: str, context: Optional[Dict[str, Any]] = None) -> str:
    context = context or {}
    normalized = str(text or "").strip().lower()
    if not normalized:
        return "chat"

    if any(keyword in normalized for keyword in ["创建技能", "生成技能", "做成技能", "保存成技能", "create skill", "new skill"]):
        return "skill_create"

    if any(keyword in normalized for keyword in ["回撤", "最大跌幅", "最大回落", "drawdown"]):
        return "drawdown_analysis"

    if any(keyword in normalized for keyword in ["历史事件图", "事件图", "相似事件", "历史事件", "event chart"]):
        return "event_chart_review"

    if any(keyword in normalized for keyword in ["历史", "复盘", "回顾", "review", "history"]):
        return "historical_analysis"

    if any(keyword in normalized for keyword in ["新闻", "资讯", "快讯", "消息", "headline", "news"]):
        return "db_latest_news"

    if any(keyword in normalized for keyword in ["研究报告", "研报", "报告", "已有报告"]):
        return "db_report_lookup"

    has_market_context = bool(context.get("market") and context.get("code"))
    if has_market_context and any(
        keyword in normalized
        for keyword in ["价格图", "图表", "走势", "价格走势", "k线", "k線", "快照", "snapshot", "盘面", "price chart", "交易", "下单"]
    ):
        return "market_data_view"

    if has_market_context and any(
        keyword in normalized
        for keyword in ["推演", "主题", "分析", "为什么", "逻辑", "bias", "view", "展望", "研究"]
    ):
        return "theme_simulation"

    return "chat"


def _extract_text_from_request(data: Dict[str, Any]) -> str:
    if isinstance(data.get("message"), dict):
        return str(data["message"].get("content") or "").strip()
    if "content" in data:
        return str(data.get("content") or "").strip()
    messages = data.get("messages") or []
    if messages:
        return str((messages[-1] or {}).get("content") or "").strip()
    return ""


def _stream_agent_response(
    agent,
    messages: List[Dict[str, str]],
    session_id: str,
    identity: Dict[str, str],
    context: Optional[Dict[str, Any]] = None,
):
    try:
        return agent.stream_chat(
            message=str(messages[-1]["content"] if messages else ""),
            history=messages[:-1],
            session_id=session_id,
            tenant_id=identity["tenant_id"],
            user_id=identity["user_id"],
            context=context or {},
        )
    except TypeError:
        return agent.stream_chat(
            str(messages[-1]["content"] if messages else ""),
            messages[:-1],
            session_id,
            identity["tenant_id"],
            identity["user_id"],
        )
    except AttributeError:
        try:
            return agent.chat_stream(
                messages,
                session_id=session_id,
                tenant_id=identity["tenant_id"],
                user_id=identity["user_id"],
            )
        except TypeError:
            return agent.chat_stream(messages)


def _sse_json(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _get_user_hermes_home(identity: Dict[str, str]) -> Path:
    return HermesBridge.get_user_hermes_home(identity["tenant_id"], identity["user_id"])


def _get_user_memory_paths(identity: Dict[str, str]) -> Dict[str, Path]:
    base_dir = _get_user_hermes_home(identity) / "memories"
    base_dir.mkdir(parents=True, exist_ok=True)
    return {
        "memory": base_dir / "MEMORY.md",
        "user": base_dir / "USER.md",
    }


def _read_memory_entries(path: Path) -> List[str]:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return [item.strip() for item in content.split(_MEMORY_ENTRY_DELIMITER) if item.strip()]


def _write_memory_entries(path: Path, entries: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _MEMORY_ENTRY_DELIMITER.join([item.strip() for item in entries if item.strip()])
    path.write_text(text, encoding="utf-8")


def _get_memory_entries(identity: Dict[str, str]) -> Dict[str, List[str]]:
    paths = _get_user_memory_paths(identity)
    return {
        "memory": _read_memory_entries(paths["memory"]),
        "user": _read_memory_entries(paths["user"]),
    }


def _mutate_memory_entries(
    identity: Dict[str, str],
    target: str,
    action: str,
    content: str = "",
    old_text: str = "",
    new_content: str = "",
) -> Dict[str, Any]:
    if target not in {"memory", "user"}:
        raise ValueError("target 必须是 memory 或 user")
    paths = _get_user_memory_paths(identity)
    entries = _read_memory_entries(paths[target])
    if action == "add":
        content = content.strip()
        if not content:
            raise ValueError("content 不能为空")
        if content not in entries:
            entries.append(content)
    elif action == "replace":
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text or not new_content:
            raise ValueError("old_text 和 new_content 不能为空")
        replaced = False
        for idx, item in enumerate(entries):
            if old_text in item:
                entries[idx] = new_content
                replaced = True
                break
        if not replaced:
            raise ValueError("未找到要替换的记忆条目")
    elif action == "remove":
        old_text = old_text.strip() or content.strip()
        if not old_text:
            raise ValueError("删除时请提供 old_text 或 content")
        new_entries = [item for item in entries if old_text not in item]
        if len(new_entries) == len(entries):
            raise ValueError("未找到要删除的记忆条目")
        entries = new_entries
    else:
        raise ValueError("不支持的 action")
    _write_memory_entries(paths[target], entries)
    return {
        "target": target,
        "entries": entries,
    }


def _load_simple_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_simple_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _skills_config_path(identity: Dict[str, str]) -> Path:
    return _get_user_hermes_home(identity) / "config.yaml"


def _get_disabled_skills(identity: Dict[str, str]) -> List[str]:
    cfg = _load_simple_yaml(_skills_config_path(identity))
    skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
    disabled = skills_cfg.get("disabled") or []
    if isinstance(disabled, str):
        disabled = [disabled]
    return [str(item).strip() for item in disabled if str(item).strip()]


def _set_skill_enabled(identity: Dict[str, str], skill_name: str, enabled: bool) -> None:
    path = _skills_config_path(identity)
    cfg = _load_simple_yaml(path)
    skills_cfg = cfg.get("skills")
    if not isinstance(skills_cfg, dict):
        skills_cfg = {}
    disabled = set(_get_disabled_skills(identity))
    if enabled:
        disabled.discard(skill_name)
    else:
        disabled.add(skill_name)
    skills_cfg["disabled"] = sorted(disabled)
    cfg["skills"] = skills_cfg
    _save_simple_yaml(path, cfg)


def _slugify_skill_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:64] or f"skill-{uuid.uuid4().hex[:8]}"


def _skills_dir(identity: Dict[str, str]) -> Path:
    path = _get_user_hermes_home(identity) / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_skill_frontmatter(content: str) -> Dict[str, Any]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[3:end].strip()
    data: Dict[str, Any] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data


def _render_skill_markdown(name: str, description: str, instructions: str, source_notes: str = "") -> str:
    parts = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        f"# {name}",
        "",
        "## Purpose",
        description or "User-defined skill for Hermes Web Chat.",
        "",
        "## Instructions",
        instructions.strip() or "Follow the user's request with structured steps and return a concise answer.",
    ]
    if source_notes.strip():
        parts.extend(["", "## Source Notes", source_notes.strip()])
    return "\n".join(parts).strip() + "\n"


def _collect_session_messages_text(identity: Dict[str, str], session_id: str, limit: int = 12) -> str:
    rows = _list_message_rows(session_id, identity["tenant_id"], identity["user_id"], limit=limit)
    lines: List[str] = []
    for row in rows[-limit:]:
        role = "用户" if row.role == "user" else "助手"
        text = str(row.content or "").strip()
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines[:limit])


def _create_skill(identity: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_name = str(payload.get("name") or payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    instructions = str(payload.get("instructions") or payload.get("prompt") or payload.get("content") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if not raw_name:
        raw_name = _derive_session_title(description or instructions or "new skill")
    if not description:
        description = f"{raw_name} 的用户自定义技能"
    skill_name = _slugify_skill_name(raw_name)
    source_notes = ""
    if session_id:
        source_notes = _collect_session_messages_text(identity, session_id)
    skill_dir = _skills_dir(identity) / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        _render_skill_markdown(raw_name, description, instructions, source_notes),
        encoding="utf-8",
    )
    _set_skill_enabled(identity, skill_name, True)
    return _serialize_skill(identity, skill_dir)


def _serialize_skill(identity: Dict[str, str], skill_dir: Path) -> Dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
    frontmatter = _parse_skill_frontmatter(content)
    disabled = set(_get_disabled_skills(identity))
    description = str(frontmatter.get("description") or "").strip()
    return {
        "name": skill_dir.name,
        "title": str(frontmatter.get("name") or skill_dir.name),
        "description": description,
        "enabled": skill_dir.name not in disabled,
        "path": str(skill_dir),
        "has_skill_md": skill_md.exists(),
    }


def _list_skills(identity: Dict[str, str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for child in sorted(_skills_dir(identity).iterdir()):
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").exists():
            continue
        results.append(_serialize_skill(identity, child))
    return results


def _delete_skill(identity: Dict[str, str], skill_name: str) -> None:
    skill_dir = _skills_dir(identity) / skill_name
    if not skill_dir.exists():
        raise ValueError("skill 不存在")
    import shutil

    shutil.rmtree(skill_dir)
    _set_skill_enabled(identity, skill_name, True)


_get_chat_session_factory()


@chat_bp.route("/api/ai/chat/sessions", methods=["GET"])
@login_required
def list_chat_sessions():
    try:
        identity = _current_identity()
        limit = int(request.args.get("limit", 20) or 20)
        sessions = [_serialize_session(row) for row in _list_session_rows(identity["tenant_id"], identity["user_id"], limit)]
        return jsonify({"code": 0, "msg": "查询成功", "data": {"sessions": sessions}})
    except Exception as e:
        logger.error(f"查询会话列表失败: {e}")
        return jsonify({"code": 500, "msg": f"查询失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat/sessions", methods=["POST"])
@login_required
def create_chat_session():
    try:
        identity = _current_identity()
        payload = request.get_json(silent=True) or {}
        context = payload.get("context") or {}
        row = _create_session_row(
            tenant_id=identity["tenant_id"],
            user_id=identity["user_id"],
            title=str(payload.get("title") or "").strip(),
            context=context,
        )
        return jsonify({"code": 0, "msg": "创建成功", "data": {"session": _serialize_session(row)}})
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        return jsonify({"code": 500, "msg": f"创建失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat/sessions/<session_id>", methods=["GET"])
@login_required
def get_chat_session_detail(session_id: str):
    try:
        identity = _current_identity()
        row = _get_session_row(session_id, identity["tenant_id"], identity["user_id"])
        if row is None:
            return jsonify({"code": 404, "msg": "会话不存在", "data": None}), 404
        messages = [
            _serialize_message(msg)
            for msg in _list_message_rows(session_id, identity["tenant_id"], identity["user_id"])
        ]
        attachments = [
            _serialize_attachment(item)
            for item in _list_attachment_rows(session_id, identity["tenant_id"], identity["user_id"])
        ]
        return jsonify(
            {
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "session": _serialize_session(row),
                    "messages": messages,
                    "attachments": attachments,
                },
            }
        )
    except Exception as e:
        logger.error(f"查询会话详情失败: {e}")
        return jsonify({"code": 500, "msg": f"查询失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat/sessions/<session_id>", methods=["DELETE"])
@login_required
def delete_chat_session(session_id: str):
    try:
        identity = _current_identity()
        deleted = _delete_session_row(session_id, identity["tenant_id"], identity["user_id"])
        if not deleted:
            return jsonify({"code": 404, "msg": "会话不存在", "data": None}), 404
        return jsonify({"code": 0, "msg": "删除成功", "data": {"id": session_id}})
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return jsonify({"code": 500, "msg": f"删除失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat/sessions/<session_id>/messages", methods=["POST"])
@login_required
def create_chat_message(session_id: str):
    try:
        identity = _current_identity()
        payload = request.get_json(silent=True) or {}
        row = _get_session_row(session_id, identity["tenant_id"], identity["user_id"])
        if row is None:
            return jsonify({"code": 404, "msg": "会话不存在", "data": None}), 404

        text = _extract_text_from_request(payload)
        if not text:
            return jsonify({"code": 400, "msg": "消息内容不能为空", "data": None}), 400

        context = _resolve_request_context(row, payload.get("context") or {}, text)
        options = payload.get("options") or {}
        requested_analysis_type = str(options.get("analysis_type") or "").strip()
        analysis_type = requested_analysis_type or _auto_detect_analysis_type(text, context)
        trace_id = str(request.headers.get("X-Trace-Id") or _build_uid("trc"))
        _insert_message_row(
            session_id=session_id,
            tenant_id=identity["tenant_id"],
            user_id=identity["user_id"],
            role="user",
            content=text,
            message_type="user_text",
            trace_id=trace_id,
        )
        _touch_session_row(
            session_id=session_id,
            tenant_id=identity["tenant_id"],
            user_id=identity["user_id"],
            text=text,
            context=context,
        )

        history_rows = _list_message_rows(session_id, identity["tenant_id"], identity["user_id"])
        agent_messages = _build_agent_messages(history_rows)
        attachment_items = _build_attachment_context_rows(session_id, identity["tenant_id"], identity["user_id"])
        agent_messages = _append_attachment_context(agent_messages, attachment_items)

        def generate():
            citations: List[Dict[str, Any]] = []
            assistant_chunks: List[str] = []
            last_error: Optional[str] = None
            structured_payload: Dict[str, Any] = {}
            try:
                if analysis_type != "chat":
                    yield _sse_json({"type": "thinking", "content": f"正在执行{analysis_type}..."})
                    assistant_text, structured_payload = _run_analysis_request(
                        analysis_type=analysis_type,
                        text=text,
                        context=context,
                        identity=identity,
                        session_id=session_id,
                    )
                    assistant_chunks.append(assistant_text)
                    charts = _build_chart_cards(context, analysis_type)
                    if charts:
                        structured_payload["charts"] = charts
                    yield _sse_json({"type": "analysis_result", "analysis_type": analysis_type, "data": structured_payload})
                    for chart in charts:
                        yield _sse_json({"type": "chart", "data": chart})
                    yield _sse_json({"type": "content", "content": assistant_text})
                else:
                    agent = get_agent()
                    charts = _build_chart_cards(context, analysis_type)
                    for chart in charts:
                        yield _sse_json({"type": "chart", "data": chart})
                    for chunk_str in _stream_agent_response(agent, agent_messages, session_id, identity, context):
                        try:
                            payload_obj = json.loads(chunk_str)
                        except Exception:
                            payload_obj = {"type": "content", "content": chunk_str}
                        if payload_obj.get("type") == "content":
                            assistant_chunks.append(str(payload_obj.get("content") or ""))
                        elif payload_obj.get("type") == "citation":
                            citations.append(payload_obj)
                        elif payload_obj.get("type") == "error":
                            last_error = str(payload_obj.get("content") or "聊天生成失败")
                        yield f"data: {json.dumps(payload_obj, ensure_ascii=False)}\n\n"
            except Exception as e:
                last_error = str(e)
                logger.error(f"Chat session stream error: {e}")
                yield _sse_json({"type": "error", "content": last_error})
            finally:
                assistant_text = "".join(assistant_chunks).strip()
                if assistant_text or citations or last_error or structured_payload:
                    final_payload = dict(structured_payload or {})
                    if analysis_type == "chat":
                        charts = _build_chart_cards(context, analysis_type)
                        if charts:
                            final_payload["charts"] = charts
                    if citations:
                        final_payload["citations"] = citations
                    if last_error:
                        final_payload["error"] = last_error
                    _insert_message_row(
                        session_id=session_id,
                        tenant_id=identity["tenant_id"],
                        user_id=identity["user_id"],
                        role="assistant",
                        content=assistant_text or (last_error or ""),
                        message_type="analysis_summary" if analysis_type != "chat" else "assistant_text",
                        structured_payload=final_payload,
                        trace_id=trace_id,
                    )
                    _touch_session_row(
                        session_id=session_id,
                        tenant_id=identity["tenant_id"],
                        user_id=identity["user_id"],
                    )
                yield "data: [DONE]\n\n"

        return Response(stream_with_context(generate()), mimetype="text/event-stream")
    except Exception as e:
        logger.error(f"创建聊天消息失败: {e}")
        return jsonify({"code": 500, "msg": f"发送失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat/sessions/<session_id>/attachments", methods=["GET"])
@login_required
def list_chat_attachments(session_id: str):
    try:
        identity = _current_identity()
        row = _get_session_row(session_id, identity["tenant_id"], identity["user_id"])
        if row is None:
            return jsonify({"code": 404, "msg": "会话不存在", "data": None}), 404
        attachments = [
            _serialize_attachment(item)
            for item in _list_attachment_rows(session_id, identity["tenant_id"], identity["user_id"])
        ]
        return jsonify({"code": 0, "msg": "查询成功", "data": {"attachments": attachments}})
    except Exception as e:
        logger.error(f"查询会话附件失败: {e}")
        return jsonify({"code": 500, "msg": f"查询失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat/sessions/<session_id>/attachments", methods=["POST"])
@login_required
def upload_chat_attachment(session_id: str):
    try:
        identity = _current_identity()
        row = _get_session_row(session_id, identity["tenant_id"], identity["user_id"])
        if row is None:
            return jsonify({"code": 404, "msg": "会话不存在", "data": None}), 404
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"code": 400, "msg": "请选择附件", "data": None}), 400
        content = uploaded.read()
        if not content:
            return jsonify({"code": 400, "msg": "附件内容不能为空", "data": None}), 400
        attachment = _store_attachment_row(
            session_id=session_id,
            tenant_id=identity["tenant_id"],
            user_id=identity["user_id"],
            file_name=uploaded.filename,
            content=content,
        )
        return jsonify({"code": 0, "msg": "上传成功", "data": {"attachment": attachment}})
    except Exception as e:
        logger.error(f"上传会话附件失败: {e}")
        return jsonify({"code": 500, "msg": f"上传失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/hermes/memories", methods=["GET"])
@login_required
def list_hermes_memories():
    try:
        identity = _current_identity()
        return jsonify({"code": 0, "msg": "查询成功", "data": _get_memory_entries(identity)})
    except Exception as e:
        logger.error(f"查询 Hermes 记忆失败: {e}")
        return jsonify({"code": 500, "msg": f"查询失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/hermes/memories", methods=["POST"])
@login_required
def mutate_hermes_memories():
    try:
        identity = _current_identity()
        payload = request.get_json(silent=True) or {}
        result = _mutate_memory_entries(
            identity=identity,
            target=str(payload.get("target") or "memory"),
            action=str(payload.get("action") or "add"),
            content=str(payload.get("content") or ""),
            old_text=str(payload.get("old_text") or ""),
            new_content=str(payload.get("new_content") or ""),
        )
        return jsonify({"code": 0, "msg": "操作成功", "data": result})
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error(f"操作 Hermes 记忆失败: {e}")
        return jsonify({"code": 500, "msg": f"操作失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/hermes/skills", methods=["GET"])
@login_required
def list_hermes_skills():
    try:
        identity = _current_identity()
        HermesBridge.ensure_default_skills(identity["tenant_id"], identity["user_id"])
        skills = _list_skills(identity)
        return jsonify({"code": 0, "msg": "查询成功", "data": {"skills": skills}})
    except Exception as e:
        logger.error(f"查询 Hermes skills 失败: {e}")
        return jsonify({"code": 500, "msg": f"查询失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/hermes/skills", methods=["POST"])
@login_required
def create_hermes_skill():
    try:
        identity = _current_identity()
        payload = request.get_json(silent=True) or {}
        skill = _create_skill(identity, payload)
        return jsonify({"code": 0, "msg": "创建成功", "data": {"skill": skill}})
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error(f"创建 Hermes skill 失败: {e}")
        return jsonify({"code": 500, "msg": f"创建失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/hermes/skills/<skill_name>/status", methods=["POST"])
@login_required
def update_hermes_skill_status(skill_name: str):
    try:
        identity = _current_identity()
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled", True))
        _set_skill_enabled(identity, skill_name, enabled)
        skills = _list_skills(identity)
        target = next((item for item in skills if item["name"] == skill_name), None)
        return jsonify({"code": 0, "msg": "更新成功", "data": {"skill": target}})
    except Exception as e:
        logger.error(f"更新 Hermes skill 状态失败: {e}")
        return jsonify({"code": 500, "msg": f"更新失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/hermes/skills/<skill_name>", methods=["DELETE"])
@login_required
def delete_hermes_skill(skill_name: str):
    try:
        identity = _current_identity()
        _delete_skill(identity, skill_name)
        return jsonify({"code": 0, "msg": "删除成功", "data": {"name": skill_name}})
    except ValueError as e:
        return jsonify({"code": 404, "msg": str(e), "data": None}), 404
    except Exception as e:
        logger.error(f"删除 Hermes skill 失败: {e}")
        return jsonify({"code": 500, "msg": f"删除失败: {e}", "data": None}), 500


@chat_bp.route("/api/ai/chat", methods=["POST"])
@login_required
def chat():
    """
    兼容旧版流式对话接口
    Input: { "messages": [...] }
    Output: SSE Stream
    """
    try:
        data = request.get_json(silent=True) or {}
        messages = data.get("messages", [])

        if not messages:
            return jsonify({"error": "No messages provided"}), 400
        identity = _current_identity()
        session_id = str(data.get("session_id") or _build_uid("sess_compat"))

        def generate():
            agent = get_agent()
            for chunk_str in _stream_agent_response(agent, messages, session_id, identity, data.get("context") or {}):
                yield f"data: {chunk_str}\n\n"
            yield "data: [DONE]\n\n"

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    except Exception as e:
        logger.error(f"Chat API error: {e}")
        return jsonify({"error": str(e)}), 500
