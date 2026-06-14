#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from chanlun import config as cl_config
from chanlun.tools.ai_analyse import AIAnalyse


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    response_text = _safe_str(value)
    if not response_text:
        raise ValueError("LLM 未返回有效内容")
    code_block = re.search(r"```json\s*([\s\S]*?)\s*```", response_text, re.IGNORECASE)
    if code_block:
        response_text = code_block.group(1).strip()
    return json.loads(response_text)


def _normalize_text_list(values: Any, fallback: List[str] | None = None, limit: int = 6) -> List[str]:
    fallback = fallback or []
    if not isinstance(values, list):
        values = []
    items = [_safe_str(item) for item in values if _safe_str(item)]
    return items[:limit] or fallback[:limit]


def _normalize_key_news(values: Any, fallback: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    fallback = fallback or []
    if not isinstance(values, list):
        values = []
    normalized: List[Dict[str, Any]] = []
    for item in values[:4]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": _safe_str(item.get("title")),
                "impact_reason": _safe_str(item.get("impact_reason") or item.get("reason") or item.get("summary")),
                "published_at": _safe_str(item.get("published_at") or item.get("time")),
            }
        )
    return normalized or fallback[:4]


def _normalize_tool_findings(values: Any, fallback: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    fallback = fallback or []
    if not isinstance(values, list):
        values = []
    normalized: List[Dict[str, Any]] = []
    for item in values[:8]:
        if isinstance(item, dict):
            label = _safe_str(item.get("label") or item.get("tool"))
            summary = _safe_str(item.get("summary"))
            highlights = _normalize_text_list(item.get("highlights"), [], limit=4)
        else:
            label = "研究工具"
            summary = _safe_str(item)
            highlights = []
        if not label and not summary:
            continue
        normalized.append({"label": label or "研究工具", "summary": summary, "highlights": highlights})
    return normalized or fallback[:8]


def _normalize_actor_profiles(values: Any, fallback: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    fallback = fallback or []
    if not isinstance(values, list):
        values = []
    normalized: List[Dict[str, Any]] = []
    for item in values[:6]:
        if not isinstance(item, dict):
            continue
        name = _safe_str(item.get("name"))
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "actor_type": _safe_str(item.get("actor_type") or "Actor"),
                "role": _safe_str(item.get("role")),
                "stance": _safe_str(item.get("stance")),
                "summary": _safe_str(item.get("summary")),
                "matched_news": _normalize_text_list(item.get("matched_news"), [], limit=3),
                "relevance_score": round(_safe_float(item.get("relevance_score")), 3),
            }
        )
    return normalized or fallback[:6]


def _normalize_agent_rounds(values: Any, fallback: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    fallback = fallback or []
    if not isinstance(values, list):
        values = []
    normalized: List[Dict[str, Any]] = []
    for item in values[:4]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "round_id": int(item.get("round_id", len(normalized) + 1) or len(normalized) + 1),
                "focus": _safe_str(item.get("focus")),
                "objective": _safe_str(item.get("objective")),
                "query_text": _safe_str(item.get("query_text")),
                "status": _safe_str(item.get("status") or "completed"),
                "search_terms": _normalize_text_list(item.get("search_terms"), [], limit=8),
                "new_headlines": _normalize_text_list(item.get("new_headlines"), [], limit=4),
                "evidence_gain": item.get("evidence_gain", {}) if isinstance(item.get("evidence_gain"), dict) else {},
                "searched_news_count": int(item.get("searched_news_count", 0) or 0),
            }
        )
    return normalized or fallback[:4]


def _normalize_uploaded_evidence(values: Any, fallback: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    fallback = fallback or []
    if not isinstance(values, list):
        values = []
    normalized: List[Dict[str, Any]] = []
    for item in values[:4]:
        if not isinstance(item, dict):
            continue
        title = _safe_str(item.get("title") or item.get("file_name"))
        if not title:
            continue
        normalized.append(
            {
                "evidence_id": _safe_str(item.get("evidence_id")),
                "title": title,
                "file_name": _safe_str(item.get("file_name") or title),
                "file_type": _safe_str(item.get("file_type")),
                "source_label": _safe_str(item.get("source_label") or "用户上传材料"),
                "summary": _safe_str(item.get("summary") or item.get("excerpt")),
                "content": _safe_str(item.get("content"))[:1200],
            }
        )
    return normalized or fallback[:4]


def _normalize_market_data_snapshot(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "asset": value.get("asset", {}) if isinstance(value.get("asset"), dict) else {},
        "summary": value.get("summary", {}) if isinstance(value.get("summary"), dict) else {},
        "data_catalog": [item for item in (value.get("data_catalog") or []) if isinstance(item, dict)][:12],
        "analysis_playbook": [item for item in (value.get("analysis_playbook") or []) if isinstance(item, dict)][:6],
        "events": [item for item in (value.get("events") or []) if isinstance(item, dict)][:4],
        "factors": [item for item in (value.get("factors") or []) if isinstance(item, dict)][:4],
        "structure_metrics": [item for item in (value.get("structure_metrics") or []) if isinstance(item, dict)][:4],
        "price_reactions": [item for item in (value.get("price_reactions") or []) if isinstance(item, dict)][:4],
        "agent_logs": [item for item in (value.get("agent_logs") or []) if isinstance(item, dict)][:4],
        "updated_at": _safe_str(value.get("updated_at")),
    }


def _build_market_data_digest(snapshot: Any) -> Dict[str, Any]:
    normalized = _normalize_market_data_snapshot(snapshot)
    summary = normalized.get("summary", {}) or {}
    event_count = int(summary.get("event_count", 0) or 0)
    factor_count = int(summary.get("factor_count", 0) or 0)
    metric_count = int(summary.get("metric_count", 0) or 0)
    reaction_count = int(summary.get("reaction_count", 0) or 0)
    log_count = int(summary.get("agent_log_count", 0) or 0)
    catalog = normalized.get("data_catalog") or []
    playbook = normalized.get("analysis_playbook") or []
    synced_catalog = [item for item in catalog if int(item.get("count", 0) or 0) > 0]
    synced_labels = [_safe_str(item.get("label")) for item in synced_catalog if _safe_str(item.get("label"))]
    if event_count + factor_count + metric_count + reaction_count + log_count <= 0 and not synced_catalog:
        return {"summary": "", "highlights": [], "catalog_overview": [], "analysis_focus": [], "snapshot": normalized}

    description_parts = [
        f"市场数据底座已补充 {event_count} 条事件、{factor_count} 条因子、{metric_count} 条结构指标、{reaction_count} 条价格验证、{log_count} 条 Agent 日志。"
    ]
    highlights: List[str] = []
    catalog_overview: List[str] = []
    analysis_focus: List[str] = []

    if synced_labels:
        description_parts.append("已覆盖数据类型：" + "、".join(synced_labels[:5]) + (" 等。" if len(synced_labels) > 5 else "。"))
        for item in synced_catalog[:4]:
            label = _safe_str(item.get("label"))
            analysis = _safe_str(item.get("analysis"))
            if label:
                catalog_overview.append(f"{label}：{analysis or '已同步，可直接纳入分析。'}")
    for item in playbook[:3]:
        step = _safe_str(item.get("step"))
        focus = _safe_str(item.get("focus"))
        method = _safe_str(item.get("method"))
        if step or focus or method:
            analysis_focus.append(" / ".join([part for part in [step, focus, method] if part]))

    first_event = (normalized.get("events") or [{}])[0]
    event_title = _safe_str(first_event.get("title"))
    if event_title:
        highlights.append(f"事件：{event_title}")

    first_factor = (normalized.get("factors") or [{}])[0]
    factor_name = _safe_str(first_factor.get("factor_name"))
    factor_value = first_factor.get("value")
    factor_unit = _safe_str(first_factor.get("unit"))
    if factor_name:
        factor_value_text = ""
        if factor_value not in {None, ""}:
            try:
                factor_value_text = f"={float(factor_value):.3f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                factor_value_text = f"={factor_value}"
        highlights.append(f"因子：{factor_name}{factor_value_text}{factor_unit}")

    first_metric = (normalized.get("structure_metrics") or [{}])[0]
    metric_name = _safe_str(first_metric.get("metric_name"))
    metric_value = first_metric.get("metric_value")
    if metric_name:
        metric_value_text = ""
        if metric_value not in {None, ""}:
            try:
                metric_value_text = f"={float(metric_value):.3f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                metric_value_text = f"={metric_value}"
        highlights.append(f"结构：{metric_name}{metric_value_text}")

    first_reaction = (normalized.get("price_reactions") or [{}])[0]
    reaction_label = _safe_str(first_reaction.get("reaction_label"))
    reaction_return = first_reaction.get("return_30m_pct")
    if reaction_label:
        reaction_text = ""
        if reaction_return not in {None, ""}:
            try:
                reaction_text = f" 30分钟{float(reaction_return):+.3f}%"
            except (TypeError, ValueError):
                reaction_text = f" 30分钟{reaction_return}"
        highlights.append(f"验证：{reaction_label}{reaction_text}")

    if highlights:
        description_parts.append("；".join(highlights[:3]))
    return {
        "summary": " ".join(part for part in description_parts if part),
        "highlights": highlights[:4],
        "catalog_overview": catalog_overview[:4],
        "analysis_focus": analysis_focus[:3],
        "snapshot": normalized,
    }


def _get_metric_value(snapshot: Dict[str, Any], metric_name: str, default: float = 0.0) -> float:
    for item in (snapshot or {}).get("structure_metrics", []) or []:
        if not isinstance(item, dict):
            continue
        if _safe_str(item.get("metric_name")) == metric_name:
            return _safe_float(item.get("metric_value"), default)
    return default


def _build_fx_decision_template(
    asset_context: Dict[str, Any],
    theme_definition: Dict[str, Any],
    report: Dict[str, Any],
    research_payload: Dict[str, Any],
) -> Dict[str, Any]:
    if _safe_str(asset_context.get("current_market")).lower() != "fx":
        return {}
    theme_multi_agent_panel = research_payload.get("theme_multi_agent_panel", {}) or {}
    route_context = theme_multi_agent_panel.get("route_context", {}) if isinstance(theme_multi_agent_panel.get("route_context"), dict) else {}
    market_snapshot = _normalize_market_data_snapshot(research_payload.get("market_data_snapshot"))
    temporal_evidence = research_payload.get("temporal_evidence", {}) or {}
    theme_news = research_payload.get("theme_news", []) or []
    pair_label = _safe_str(route_context.get("pair_label")) or _safe_str(route_context.get("pair_code")) or _safe_str(asset_context.get("current_code")) or "当前货币对"
    pair_role = _safe_str(route_context.get("pair_role")) or "相对强弱与专属机制"
    route_label = _safe_str(route_context.get("route_label")) or _safe_str(asset_context.get("fx_theme_route_label")) or "均衡观察"
    policy_rate_diff = _get_metric_value(market_snapshot, "policy_rate_differential")
    policy_surprise_diff = _get_metric_value(market_snapshot, "policy_surprise_differential")
    usd_pressure = _get_metric_value(market_snapshot, "usd_counter_currency_pressure")
    cftc_bias = _get_metric_value(market_snapshot, "cftc_positioning_bias")
    dominant_move = _safe_float(temporal_evidence.get("avg_dominant_move_pct"), 0.0)
    alignment_rate = _safe_float(temporal_evidence.get("alignment_rate"), 0.0)
    base_currency = _safe_str(asset_context.get("base_currency"))
    quote_currency = _safe_str(asset_context.get("quote_currency"))
    primary_driver = f"{route_label}：当前优先按 {pair_role} 解释 {pair_label}。"
    if route_label == "央行路径":
        primary_driver = f"央行路径：比较 {base_currency or 'base'} 与 {quote_currency or 'quote'} 的政策利差，当前差值 {policy_rate_diff:+.2f}。"
    elif route_label == "数据预期差":
        primary_driver = f"数据预期差：宏观 surprise 差值 {policy_surprise_diff:+.2f}，重点看是否把主题从事件推成路径重估。"
    elif route_label == "风险偏好":
        primary_driver = f"风险偏好：主题先影响避险流，再通过 {pair_role} 传导到 {pair_label}。"
    elif route_label == "政策干预":
        primary_driver = f"政策干预：{pair_label} 需要优先看官方约束与口径，不能只按市场自发定价理解。"
    elif route_label == "增长与商品链":
        primary_driver = f"增长与商品链：先看中国/商品链变化，再看其如何改变 {pair_label} 的相对强弱。"
    elif route_label == "美元主线":
        primary_driver = f"美元主线：美元压力值 {usd_pressure:+.2f}，需要先判断美元系统方向，再判断货币对映射。"
    first_theme_news = theme_news[0] if theme_news else {}
    trigger_text = _safe_str(first_theme_news.get("title")) or _safe_str(theme_definition.get("label")) or "当前主题催化"
    trigger_signal = f"{trigger_text} 是当前直接触发器，需配合时间验证与后续增量消息确认。"
    if _safe_str(temporal_evidence.get("summary")):
        trigger_signal = _safe_str(temporal_evidence.get("summary"))
    amplifier_parts: List[str] = []
    if abs(cftc_bias) >= 0.2:
        amplifier_parts.append(f"CFTC/拥挤度 {cftc_bias:+.2f}")
    if abs(usd_pressure) >= 0.2:
        amplifier_parts.append(f"美元压力 {usd_pressure:+.2f}")
    if dominant_move >= 0.3:
        amplifier_parts.append(f"6小时主导波动 {dominant_move:.3f}%")
    if alignment_rate >= 0.55:
        amplifier_parts.append(f"时间验证一致率 {alignment_rate * 100:.0f}%")
    amplifier = "；".join(amplifier_parts) or "当前放大器仍偏弱，说明主题更像结构判断而非拥挤交易。"
    invalidation_rules = [
        f"若 {pair_label} 的价格方向与 {route_label} 叙事持续背离，当前主轴失效。",
        "若后续同主题催化没有继续增加，说明本轮更像一次性冲击。",
    ]
    if route_label == "央行路径":
        invalidation_rules.insert(0, "若利差与政策路径重新逆转，当前方向判断需要立刻降权。")
    elif route_label == "政策干预":
        invalidation_rules.insert(0, "若官方口径降温或干预预期消失，政策主线需要立刻重估。")
    elif route_label == "增长与商品链":
        invalidation_rules.insert(0, "若商品与风险资产不再共振，增长与商品链逻辑容易失真。")
    execution_bias = _safe_str(report.get("trade_bias")) or "观望"
    return {
        "route_label": route_label,
        "pair_label": pair_label,
        "pair_role": pair_role,
        "primary_driver": primary_driver,
        "trigger_signal": trigger_signal,
        "amplifier": amplifier,
        "execution_bias": execution_bias,
        "invalidation_rules": invalidation_rules[:4],
    }


def _build_memory_summary(research_memory: Dict[str, Any]) -> str:
    if not research_memory:
        return "这是该主题的首次研究，会话内尚未形成历史记忆。"
    last_bias = _safe_str(research_memory.get("last_trade_bias")) or "观望"
    run_count = int(research_memory.get("run_count", 0) or 0)
    bias_distribution = research_memory.get("bias_distribution", {}) or {}
    dominant_bias = max(bias_distribution.items(), key=lambda item: item[1])[0] if bias_distribution else last_bias
    recent_theme_shift = _safe_str(research_memory.get("theme_shift")) or "当前没有显著偏向切换。"
    return f"该主题已累计研究 {run_count} 次，最近一次结论为 {last_bias}，历史主偏向为 {dominant_bias}。{recent_theme_shift}"


def _build_report_sections(
    report: Dict[str, Any],
    research_payload: Dict[str, Any],
    research_memory: Dict[str, Any],
) -> List[Dict[str, Any]]:
    evidence_matrix = research_payload.get("evidence_matrix", {}) or {}
    bucket_counts = evidence_matrix.get("bucket_counts", {}) or {}
    actor_profiles = _normalize_actor_profiles(research_payload.get("actor_profiles"))
    tool_findings = _normalize_tool_findings(research_payload.get("research_tools"))
    uploaded_evidence = _normalize_uploaded_evidence(research_payload.get("uploaded_theme_evidence"))
    temporal_evidence = research_payload.get("temporal_evidence", {}) or {}
    market_data_digest = _build_market_data_digest(research_payload.get("market_data_snapshot"))
    fx_decision_template = report.get("fx_decision_template", {}) if isinstance(report.get("fx_decision_template"), dict) else {}
    comprehensive_reasoning = research_payload.get("comprehensive_reasoning", {}) if isinstance(research_payload.get("comprehensive_reasoning"), dict) else {}
    arbiter_execution = comprehensive_reasoning.get("arbiter_execution", {}) if isinstance(comprehensive_reasoning.get("arbiter_execution"), dict) else {}
    cross_asset_evidence = comprehensive_reasoning.get("cross_asset_evidence", {}) if isinstance(comprehensive_reasoning.get("cross_asset_evidence"), dict) else {}
    section_one_points = [
        _safe_str(report.get("summary")),
        f"交易偏向：{_safe_str(report.get('trade_bias')) or '观望'}",
        _safe_str(report.get("price_interpretation")),
        _safe_str(comprehensive_reasoning.get("summary")),
        (
            "外汇主轴：" + "；".join(
                [
                    _safe_str(fx_decision_template.get("primary_driver")),
                    _safe_str(fx_decision_template.get("trigger_signal")),
                    _safe_str(fx_decision_template.get("amplifier")),
                ]
            )
        ) if fx_decision_template else "",
    ]
    section_two_points = [
        f"证据结构：直接 {int(bucket_counts.get('direct', 0) or 0)} 条，驱动 {int(bucket_counts.get('driver', 0) or 0)} 条，背景 {int(bucket_counts.get('background', 0) or 0)} 条，用户材料 {int(bucket_counts.get('uploaded', 0) or 0)} 份。",
        "工具结论：" + "；".join([item.get("summary", "") for item in tool_findings[:2] if _safe_str(item.get("summary"))]),
        "主体层：" + "；".join([f"{item.get('name', '')}{'：' + item.get('stance', '') if _safe_str(item.get('stance')) else ''}" for item in actor_profiles[:3] if _safe_str(item.get("name"))]),
        ("用户材料：" + "；".join([f"{item.get('title', '')}：{item.get('summary', '')}" for item in uploaded_evidence[:2] if _safe_str(item.get("title"))])) if uploaded_evidence else "",
        _safe_str(temporal_evidence.get("summary")),
        market_data_digest.get("summary", ""),
        "数据类型：" + "；".join(market_data_digest.get("catalog_overview", [])[:3]) if market_data_digest.get("catalog_overview") else "",
    ]
    section_three_points = [
        _safe_str(report.get("followthrough_view")),
        "市场数据验证：" + "；".join(market_data_digest.get("highlights", [])[:3]) if market_data_digest.get("highlights") else "",
        "分析顺序：" + "；".join(market_data_digest.get("analysis_focus", [])[:3]) if market_data_digest.get("analysis_focus") else "",
        "执行计划：" + "；".join(_normalize_text_list(report.get("execution_plan"), [], limit=3)),
        "失效条件：" + "；".join(_normalize_text_list(report.get("invalidations"), [], limit=3)),
        ("跨资产佐证：" + _safe_str(cross_asset_evidence.get("corroboration_summary"))) if cross_asset_evidence else "",
        ("定价阶段：" + _safe_str(arbiter_execution.get("pricing_stage"))) if arbiter_execution else "",
        ("外汇失效：" + "；".join(_normalize_text_list(fx_decision_template.get("invalidation_rules"), [], limit=3))) if fx_decision_template else "",
    ]
    section_four_points = [
        "风险提示：" + "；".join(_normalize_text_list(report.get("risk_flags"), [], limit=4)),
        _safe_str(report.get("memory_takeaway")) or _build_memory_summary(research_memory),
        _safe_str(report.get("agent_round_summary")),
    ]
    raw_sections = [
        {"id": "market_view", "title": "市场结论", "objective": "快速回答这条主题现在对资产意味着什么", "points": section_one_points},
        {"id": "evidence_stack", "title": "证据与主体", "objective": "说明当前结论依赖了哪些证据、主体与工具", "points": section_two_points},
        {"id": "scenario_plan", "title": "推演与执行", "objective": "给出未来推演、执行路径与失效条件", "points": section_three_points},
        {"id": "risk_memory", "title": "风险与记忆", "objective": "提示风险、偏向切换与多轮补证据结果", "points": section_four_points},
    ]
    sections: List[Dict[str, Any]] = []
    for index, section in enumerate(raw_sections, start=1):
        points = [item for item in [_safe_str(point) for point in section.get("points", [])] if item]
        sections.append(
            {
                "section_id": section["id"],
                "order": index,
                "title": section["title"],
                "objective": section["objective"],
                "content": "；".join(points) if points else "暂无内容。",
                "highlights": points[:4],
            }
        )
    return sections


def _build_agent_journal(
    report: Dict[str, Any],
    research_payload: Dict[str, Any],
    research_memory: Dict[str, Any],
) -> List[Dict[str, Any]]:
    uploaded_evidence = _normalize_uploaded_evidence(research_payload.get("uploaded_theme_evidence"))
    market_data_digest = _build_market_data_digest(research_payload.get("market_data_snapshot"))
    journal: List[Dict[str, Any]] = [
        {
            "stage": "planner",
            "label": "证据规划",
            "summary": f"按 { _safe_str(research_payload.get('planner_source')) or 'evidence_gap_heuristic'} 识别证据缺口并规划补证据轮次。",
        }
    ]
    if uploaded_evidence:
        journal.append(
            {
                "stage": "uploaded_evidence",
                "label": "用户材料入池",
                "summary": f"已将 {len(uploaded_evidence)} 份用户上传材料纳入证据池，优先读取其摘要与原文片段。",
            }
        )
    if market_data_digest.get("summary"):
        journal.append(
            {
                "stage": "market_data",
                "label": "市场数据底座",
                "summary": " ".join(
                    [
                        market_data_digest.get("summary", ""),
                        "；".join(market_data_digest.get("analysis_focus", [])[:2]) if market_data_digest.get("analysis_focus") else "",
                    ]
                ).strip(),
            }
        )
    for item in _normalize_agent_rounds(research_payload.get("agent_rounds"))[:4]:
        evidence_gain = item.get("evidence_gain", {}) or {}
        journal.append(
            {
                "stage": "research_round",
                "label": f"第{int(item.get('round_id', 0) or 0)}轮补证据",
                "summary": (
                    f"{_safe_str(item.get('objective') or item.get('focus'))}；"
                    f"命中 {int(item.get('searched_news_count', 0) or 0)} 条，"
                    f"净新增 {int(evidence_gain.get('delta', 0) or 0)} 条。"
                ),
            }
        )
    journal.append(
        {
            "stage": "reasoning",
            "label": "结构化推演",
            "summary": f"形成 `{_safe_str(report.get('trade_bias')) or '观望'}` 结论，信心 {round(_safe_float(report.get('confidence_score'), 0.45), 3)}。",
        }
    )
    if research_memory:
        journal.append(
            {
                "stage": "memory",
                "label": "研究记忆",
                "summary": _safe_str(report.get("memory_takeaway")) or _build_memory_summary(research_memory),
            }
        )
    return journal


def _build_research_agent_payload(
    report: Dict[str, Any],
    research_payload: Dict[str, Any],
    research_memory: Dict[str, Any],
) -> Dict[str, Any]:
    tool_findings = _normalize_tool_findings(research_payload.get("research_tools"))
    actor_profiles = _normalize_actor_profiles(research_payload.get("actor_profiles"))
    agent_rounds = _normalize_agent_rounds(research_payload.get("agent_rounds"))
    uploaded_evidence = _normalize_uploaded_evidence(research_payload.get("uploaded_theme_evidence"))
    temporal_evidence = research_payload.get("temporal_evidence", {}) or {}
    market_data_digest = _build_market_data_digest(research_payload.get("market_data_snapshot"))
    theme_multi_agent_panel = research_payload.get("theme_multi_agent_panel", {}) or {}
    comprehensive_reasoning = research_payload.get("comprehensive_reasoning", {}) if isinstance(research_payload.get("comprehensive_reasoning"), dict) else {}
    fx_decision_template = report.get("fx_decision_template", {}) if isinstance(report.get("fx_decision_template"), dict) else {}
    memory_summary = _safe_str(report.get("memory_takeaway")) or _build_memory_summary(research_memory)
    report_sections = _build_report_sections(report, research_payload, research_memory)
    agent_journal = _build_agent_journal(report, research_payload, research_memory)
    return {
        "version": "v2",
        "mode": "manual_multi_round",
        "status": "ready",
        "planner_source": _safe_str(research_payload.get("planner_source")) or "evidence_gap_heuristic",
        "rounds_completed": int(research_payload.get("rounds_completed", len(agent_rounds)) or len(agent_rounds)),
        "agent_summary": _safe_str(report.get("summary")),
        "tool_findings": tool_findings,
        "actor_profiles": actor_profiles,
        "agent_rounds": agent_rounds,
        "cross_asset_signals": research_payload.get("cross_asset_signals", [])[:4],
        "similar_cases": research_payload.get("similar_cases", [])[:4],
        "uploaded_evidence": uploaded_evidence,
        "temporal_evidence": temporal_evidence,
        "theme_multi_agent_panel": theme_multi_agent_panel,
        "active_theme_agents": (theme_multi_agent_panel.get("active_agents") or [])[:8],
        "theme_agent_outputs": (theme_multi_agent_panel.get("agent_outputs") or [])[:8],
        "theme_agent_arbiter": theme_multi_agent_panel.get("arbiter", {}) if isinstance(theme_multi_agent_panel.get("arbiter"), dict) else {},
        "comprehensive_reasoning": comprehensive_reasoning,
        "fx_decision_template": fx_decision_template,
        "market_data_snapshot": market_data_digest.get("snapshot", {}),
        "market_data_digest": {
            "summary": market_data_digest.get("summary", ""),
            "highlights": market_data_digest.get("highlights", []),
            "catalog_overview": market_data_digest.get("catalog_overview", []),
            "analysis_focus": market_data_digest.get("analysis_focus", []),
        },
        "market_data_catalog": market_data_digest.get("snapshot", {}).get("data_catalog", []),
        "market_data_playbook": market_data_digest.get("snapshot", {}).get("analysis_playbook", []),
        "evidence_matrix": research_payload.get("evidence_matrix", {}) or {},
        "research_digest": _safe_str(research_payload.get("research_digest")),
        "memory_summary": memory_summary,
        "memory_snapshot": research_memory,
        "report_sections": report_sections,
        "agent_journal": agent_journal,
        "manual_trigger_only": True,
        "trader_card": {
            "bias": _safe_str(report.get("trade_bias")) or "观望",
            "confidence_score": round(_safe_float(report.get("confidence_score"), 0.45), 3),
            "future_view": _safe_str(report.get("followthrough_view")),
            "execution_plan": _normalize_text_list(report.get("execution_plan"), [], limit=4),
            "invalidations": _normalize_text_list(report.get("invalidations"), [], limit=4),
        },
    }


def _build_theme_reasoning_prompt(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    theme_news: List[Dict[str, Any]],
    propagation_chain: List[Dict[str, Any]],
    ontology: Dict[str, Any],
    retrieval_summary: Dict[str, Any],
    research_payload: Dict[str, Any],
    research_memory: Dict[str, Any],
) -> str:
    theme_label = _safe_str(theme_definition.get("label")) or "自定义主题"
    asset_name = _safe_str(asset_context.get("asset_name") or asset_context.get("current_code")) or "目标资产"
    evidence_news = [
        {
            "title": _safe_str(item.get("title")),
            "summary": _safe_str(item.get("summary") or item.get("direction_reason")),
            "published_at": _safe_str(item.get("published_at")),
            "theme_hits": item.get("theme_hits", []),
        }
        for item in (theme_news or [])[:6]
    ]
    market_data_digest = _build_market_data_digest(research_payload.get("market_data_snapshot"))
    theme_multi_agent_panel = research_payload.get("theme_multi_agent_panel", {}) or {}
    comprehensive_reasoning = research_payload.get("comprehensive_reasoning", {}) if isinstance(research_payload.get("comprehensive_reasoning"), dict) else {}
    fx_decision_template = _build_fx_decision_template(asset_context, theme_definition, {}, research_payload)
    prompt_payload = {
        "theme": theme_definition,
        "asset_context": asset_context,
        "theme_news": evidence_news,
        "propagation_chain": propagation_chain[:6],
        "ontology_nodes": (ontology.get("nodes") or [])[:12],
        "ontology_edges": (ontology.get("edges") or [])[:14],
        "retrieval_summary": retrieval_summary,
        "research_tools": (research_payload.get("research_tools") or [])[:5],
        "actor_profiles": (research_payload.get("actor_profiles") or [])[:5],
        "cross_asset_signals": (research_payload.get("cross_asset_signals") or [])[:4],
        "similar_cases": (research_payload.get("similar_cases") or [])[:3],
        "evidence_matrix": research_payload.get("evidence_matrix", {}),
        "agent_rounds": _normalize_agent_rounds(research_payload.get("agent_rounds")),
        "planner_source": _safe_str(research_payload.get("planner_source")) or "evidence_gap_heuristic",
        "uploaded_evidence": _normalize_uploaded_evidence(research_payload.get("uploaded_theme_evidence")),
        "temporal_evidence": research_payload.get("temporal_evidence", {}) or {},
        "theme_multi_agent_panel": {
            "active_agents": (theme_multi_agent_panel.get("active_agents") or [])[:8],
            "agent_outputs": (theme_multi_agent_panel.get("agent_outputs") or [])[:8],
            "arbiter": theme_multi_agent_panel.get("arbiter", {}) if isinstance(theme_multi_agent_panel.get("arbiter"), dict) else {},
            "consensus": theme_multi_agent_panel.get("consensus", {}) if isinstance(theme_multi_agent_panel.get("consensus"), dict) else {},
            "route_context": theme_multi_agent_panel.get("route_context", {}) if isinstance(theme_multi_agent_panel.get("route_context"), dict) else {},
        },
        "comprehensive_reasoning": comprehensive_reasoning,
        "fx_decision_template": fx_decision_template,
        "market_data_snapshot": market_data_digest.get("snapshot", {}),
        "market_data_digest": {
            "summary": market_data_digest.get("summary", ""),
            "highlights": market_data_digest.get("highlights", []),
            "catalog_overview": market_data_digest.get("catalog_overview", []),
            "analysis_focus": market_data_digest.get("analysis_focus", []),
        },
        "market_data_catalog": market_data_digest.get("snapshot", {}).get("data_catalog", []),
        "market_data_playbook": market_data_digest.get("snapshot", {}).get("analysis_playbook", []),
        "research_memory": {
            "run_count": research_memory.get("run_count", 0),
            "last_trade_bias": research_memory.get("last_trade_bias", ""),
            "theme_shift": research_memory.get("theme_shift", ""),
            "recent_runs": (research_memory.get("recent_runs") or [])[:3],
        },
    }
    schema = {
        "summary": "一句话结论，必须明确该主题当前对资产的核心影响",
        "trade_bias": "顺势看多/顺势看空/观望",
        "news_summary": "将证据新闻压缩成可读总结",
        "relationship_chain": ["主题->主体->资产 的因果链条，3-5条"],
        "future_reasoning": "未来24小时后续推演，说明继续发酵还是一次性冲击",
        "future_scenarios": ["基准情景", "强化情景", "失效情景"],
        "execution_plan": ["可执行动作1", "可执行动作2", "可执行动作3"],
        "risk_flags": ["风险1", "风险2"],
        "key_drivers": ["关键驱动1", "关键驱动2"],
        "invalidations": ["什么情况说明主题失效"],
        "tool_insights": ["Research Agent 各工具给出的核心发现"],
        "market_data_insights": ["市场数据底座中的事件/因子/结构/验证结论"],
        "market_data_catalog": ["市场数据底座各类型数据的用途与覆盖状态"],
        "analysis_playbook": ["最适合当前资产的市场数据分析顺序"],
        "actor_signals": ["关键主体对资产意味着什么"],
        "multi_agent_consensus": "多 Agent 裁决结论、共识来源与冲突点",
        "comprehensive_reasoning": {
            "summary": "规则层对主题路由、跨资产佐证与执行裁决的综合摘要",
            "router": {"route_label": "当前主题路由", "focus": "主解释框架"},
            "cross_asset_evidence": {"regime_label": "跨资产状态", "confirmation_score": 0.0, "corroboration_summary": "跨资产佐证摘要"},
            "arbiter_execution": {"pricing_stage": "定价阶段", "execution_bias": "执行偏向", "main_driver": "主驱动", "invalidation_triggers": ["失效条件"]},
        },
        "fx_decision_template": {
            "route_label": "外汇路由",
            "pair_label": "货币对专属框架",
            "primary_driver": "主轴驱动",
            "trigger_signal": "触发器",
            "amplifier": "放大器",
            "execution_bias": "执行偏向",
            "invalidation_rules": ["失效条件1", "失效条件2"],
        },
        "agent_round_summary": "多轮补证据后，哪些轮次真正补到了关键证据",
        "memory_takeaway": "结合历史研究记忆给出一句提醒",
        "confidence_score": 0.0,
        "key_news": [{"title": "", "impact_reason": "", "published_at": ""}],
    }
    return (
        "你是职业交易员的主题研究代理。请参考 MiroFish 的方法：先读取工具结果，再综合图谱、本体、跨资产和历史记忆给出结论。"
        "不要写空话，不要新闻搬运，不要解释过程，只输出对交易有价值的结构化结果。"
        "输出必须是 JSON，不要输出任何额外解释。\n\n"
        f"当前主题：{theme_label}\n"
        f"目标资产：{asset_name}\n"
        "请基于以下 Research Agent 证据做推演：\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False)}\n\n"
        "输出 JSON 字段要求：\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "要求：\n"
        "1. relationship_chain 必须写出具体传导链，不要只写抽象判断\n"
        "2. future_reasoning 必须对未来24小时做方向性推演\n"
        "3. execution_plan 只保留最有用的3条\n"
        "4. tool_insights 需要体现你真正使用了工具层证据\n"
        "5. actor_signals 需要体现谁在驱动这条主题主线\n"
        "6. market_data_insights 需要体现你真正读取了市场数据底座里的事件、因子、结构或价格验证\n"
        "7. market_data_catalog 需要说明当前资产最关键的数据类型及其作用\n"
        "8. analysis_playbook 需要给出最适合当前资产的分析顺序\n"
        "9. multi_agent_consensus 需要体现多 Agent 共识、冲突与裁决边界\n"
        "10. comprehensive_reasoning 必须综合规则层的主题路由、跨资产佐证和执行裁决\n"
        "11. 若当前资产是外汇，fx_decision_template 必须区分主轴驱动、触发器、放大器、执行偏向和失效条件\n"
        "12. agent_round_summary 需要说明多轮补证据后哪些证据改变了结论\n"
        "13. confidence_score 为0到1之间的小数\n"
        "14. key_news 只保留最关键的2到4条"
    )


def _run_gemini_theme_reasoning(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    theme_news: List[Dict[str, Any]],
    propagation_chain: List[Dict[str, Any]],
    ontology: Dict[str, Any],
    retrieval_summary: Dict[str, Any],
    research_payload: Dict[str, Any],
    research_memory: Dict[str, Any],
) -> Dict[str, Any]:
    model_name = _safe_str(getattr(cl_config, "OPENROUTER_AI_MODEL", ""))
    api_key = _safe_str(getattr(cl_config, "OPENROUTER_AI_KEYS", ""))
    if not api_key or not model_name:
        return {
            "enabled": False,
            "provider": "openrouter",
            "model": model_name,
            "message": "OpenRouter 未配置，无法启用 Gemini 主题推演",
            "data": {},
        }
    if "gemini" not in model_name.lower():
        return {
            "enabled": False,
            "provider": "openrouter",
            "model": model_name,
            "message": f"当前 OpenRouter 模型不是 Gemini：{model_name}",
            "data": {},
        }
    ai_client = AIAnalyse(_safe_str(asset_context.get("current_market")) or "a")
    prompt = _build_theme_reasoning_prompt(
        theme_definition=theme_definition,
        asset_context=asset_context,
        theme_news=theme_news,
        propagation_chain=propagation_chain,
        ontology=ontology,
        retrieval_summary=retrieval_summary,
        research_payload=research_payload,
        research_memory=research_memory,
    )
    ai_result = ai_client.req_openrouter_ai_model(prompt)
    if not isinstance(ai_result, dict) or not ai_result.get("ok"):
        return {
            "enabled": False,
            "provider": "openrouter",
            "model": model_name,
            "message": _safe_str((ai_result or {}).get("msg")) or "Gemini 推演失败",
            "data": {},
        }
    try:
        parsed = _extract_json_payload(ai_result.get("msg"))
    except Exception as exc:
        return {
            "enabled": False,
            "provider": "openrouter",
            "model": _safe_str(ai_result.get("model")) or model_name,
            "message": f"Gemini 返回结果无法解析: {exc}",
            "data": {},
        }
    return {
        "enabled": True,
        "provider": "openrouter",
        "model": _safe_str(ai_result.get("model")) or model_name,
        "message": "Gemini 主题推演已启用",
        "data": parsed,
    }


def build_theme_reasoning_report(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    theme_news: List[Dict[str, Any]],
    propagation_chain: List[Dict[str, Any]],
    ontology: Dict[str, Any],
    retrieval_summary: Dict[str, Any] | None = None,
    research_payload: Dict[str, Any] | None = None,
    research_memory: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    research_payload = research_payload or {}
    research_memory = research_memory or {}
    asset_name = _safe_str(asset_context.get("asset_name") or asset_context.get("current_code")) or "目标资产"
    direction = _safe_str(asset_context.get("price_direction") or "neutral").lower()
    direction_label = {"bullish": "偏上行", "bearish": "偏下行", "neutral": "偏震荡"}.get(direction, "偏震荡")
    latest_change_pct = _safe_float(asset_context.get("latest_change_pct"))
    theme_label = _safe_str(theme_definition.get("label")) or "自定义主题"
    direct_count = len(theme_news or [])
    trade_bias = "观望"
    if direction == "bullish" and direct_count >= 2:
        trade_bias = "顺势看多"
    elif direction == "bearish" and direct_count >= 2:
        trade_bias = "顺势看空"

    key_news = theme_news[:3]
    retrieval_summary = retrieval_summary or {}
    news_summary = "；".join(
        [
            f"{idx + 1}. {str(item.get('title') or '')}"
            for idx, item in enumerate(key_news)
            if str(item.get("title") or "").strip()
        ]
    ) or "当前窗口内尚未提炼出足够强的主题证据，需要继续观察新催化。"
    evidence_matrix = research_payload.get("evidence_matrix", {}) or {}
    temporal_evidence = research_payload.get("temporal_evidence", {}) or {}
    market_data_digest = _build_market_data_digest(research_payload.get("market_data_snapshot"))
    theme_multi_agent_panel = research_payload.get("theme_multi_agent_panel", {}) or {}
    theme_agent_arbiter = theme_multi_agent_panel.get("arbiter", {}) if isinstance(theme_multi_agent_panel.get("arbiter"), dict) else {}
    theme_agent_consensus = theme_multi_agent_panel.get("consensus", {}) if isinstance(theme_multi_agent_panel.get("consensus"), dict) else {}
    comprehensive_reasoning = research_payload.get("comprehensive_reasoning", {}) if isinstance(research_payload.get("comprehensive_reasoning"), dict) else {}
    comprehensive_arbiter = comprehensive_reasoning.get("arbiter_execution", {}) if isinstance(comprehensive_reasoning.get("arbiter_execution"), dict) else {}
    cross_asset_evidence = comprehensive_reasoning.get("cross_asset_evidence", {}) if isinstance(comprehensive_reasoning.get("cross_asset_evidence"), dict) else {}
    contradiction_flags = _normalize_text_list(evidence_matrix.get("contradiction_flags"), [], limit=3)
    risk_flags = [
        "若后续同主题新闻没有继续增加，当前主题更可能是一跳冲击而非持续主线。",
        "若价格方向与主题叙事出现背离，需要警惕市场已经提前交易或消息可信度不足。",
    ] + contradiction_flags
    if direct_count >= 4:
        risk_flags.append("主题新闻密度较高，短线波动可能被放大，需防止追价。")

    tool_insights = [
        f"{_safe_str(item.get('label'))}：{_safe_str(item.get('summary'))}"
        for item in (research_payload.get("research_tools") or [])[:4]
        if _safe_str(item.get("summary"))
    ]
    if market_data_digest.get("summary"):
        tool_insights.append(f"市场数据底座：{market_data_digest.get('summary')}")
    if market_data_digest.get("analysis_focus"):
        tool_insights.append("底座分析框架：" + "；".join(market_data_digest.get("analysis_focus", [])[:2]))
    if _safe_str(theme_agent_arbiter.get("summary")):
        tool_insights.append("多 Agent 裁决：" + _safe_str(theme_agent_arbiter.get("summary")))
    if _safe_str(comprehensive_reasoning.get("summary")):
        tool_insights.append("全面推演：" + _safe_str(comprehensive_reasoning.get("summary")))
    actor_signals = [
        f"{_safe_str(item.get('name'))}：{_safe_str(item.get('stance') or item.get('summary'))}"
        for item in (research_payload.get("actor_profiles") or [])[:4]
        if _safe_str(item.get("name"))
    ]
    agent_rounds = _normalize_agent_rounds(research_payload.get("agent_rounds"))
    agent_round_summary = "；".join(
        [
            f"第{int(item.get('round_id', index + 1))}轮聚焦{_safe_str(item.get('objective') or item.get('focus'))}，补到 {int((item.get('evidence_gain') or {}).get('delta', 0) or 0)} 条净新增证据。"
            for index, item in enumerate(agent_rounds[:3])
        ]
    ) or "当前未触发额外补证据轮次。"
    memory_takeaway = _build_memory_summary(research_memory)
    summary = (
        f"{theme_label} 当前已对 {asset_name} 形成 {direction_label} 影响，"
        f"近端价格变动 {latest_change_pct:+.3f}% ，"
        f"已提取 {direct_count} 条主题相关证据，交易偏向为 `{trade_bias}`。"
    )
    temporal_summary = _safe_str(asset_context.get("temporal_reaction_summary")) or _safe_str(temporal_evidence.get("summary"))
    market_data_summary = market_data_digest.get("summary", "")
    base_report = {
        "summary": summary,
        "trade_bias": trade_bias,
        "price_interpretation": (
            f"{asset_name} 当前表现为 {direction_label}，说明 `{theme_label}` 已开始进入定价，"
            f"{temporal_summary or '但是否持续仍取决于主题扩散是否继续。'}"
            f"{(' ' + market_data_summary) if market_data_summary else ''}"
        ),
        "news_summary": news_summary,
        "followthrough_view": (
            f"若未来 {int(retrieval_summary.get('lookback_hours', 24) or 24)} 小时内继续出现同主题催化，"
            f"`{theme_label}` 更可能从单点事件升级为持续主线；否则更接近一次性冲击。"
        ),
        "execution_plan": [
            _safe_str(comprehensive_arbiter.get("main_driver")) or f"先跟踪 `{theme_label}` 后续是否出现同方向的新催化。",
            f"若 {asset_name} 价格继续沿当前方向扩展，优先按 `{_safe_str(comprehensive_arbiter.get('execution_bias')) or '顺势跟踪'}` 执行，而非逆向抢反转。",
            "若新消息中断且价格回吐，说明这更像一次性消息冲击，应降低主线权重。",
        ],
        "key_news": [
            {
                "title": str(item.get("title") or ""),
                "impact_reason": str(item.get("summary") or item.get("direction_reason") or ""),
                "published_at": str(item.get("published_at") or ""),
            }
            for item in key_news
        ],
        "risk_flags": _normalize_text_list(risk_flags, [], limit=6),
        "propagation_chain": propagation_chain,
        "ontology_brief": {
            "entity_count": int(ontology.get("entity_count", 0) or 0),
            "relation_count": int(ontology.get("relation_count", 0) or 0),
        },
        "retrieval_summary": retrieval_summary,
        "relationship_chain": (
            [
                f"{item.get('stage', '阶段')}：{item.get('summary', '暂无')}"
                for item in propagation_chain[:4]
            ]
            if propagation_chain
            else []
        ),
        "future_scenarios": [],
        "key_drivers": [],
        "invalidations": _normalize_text_list(comprehensive_arbiter.get("invalidation_triggers"), [], limit=4),
        "tool_insights": tool_insights,
        "market_data_summary": market_data_summary,
        "market_data_insights": market_data_digest.get("highlights", []),
        "market_data_catalog": market_data_digest.get("catalog_overview", []),
        "analysis_playbook": market_data_digest.get("analysis_focus", []),
        "multi_agent_consensus": _safe_str(theme_agent_arbiter.get("summary")) or _safe_str(theme_agent_consensus.get("stance")),
        "comprehensive_reasoning": comprehensive_reasoning,
        "cross_asset_corroboration": _safe_str(cross_asset_evidence.get("corroboration_summary")),
        "actor_signals": actor_signals,
        "agent_round_summary": agent_round_summary,
        "memory_takeaway": memory_takeaway,
        "temporal_summary": temporal_summary,
        "fx_decision_template": {},
        "confidence_score": 0.45,
        "ai_status": {
            "enabled": False,
            "provider": "rule_engine",
            "model": "",
            "message": "当前为规则推演",
        },
        "reasoning_source": "rule_engine",
    }
    base_report["fx_decision_template"] = _build_fx_decision_template(asset_context, theme_definition, base_report, research_payload)
    llm_result = _run_gemini_theme_reasoning(
        theme_definition=theme_definition,
        asset_context=asset_context,
        theme_news=theme_news,
        propagation_chain=propagation_chain,
        ontology=ontology,
        retrieval_summary=retrieval_summary,
        research_payload=research_payload,
        research_memory=research_memory,
    )
    if not llm_result.get("enabled"):
        base_report["ai_status"] = {
            "enabled": False,
            "provider": llm_result.get("provider", "openrouter"),
            "model": _safe_str(llm_result.get("model")),
            "message": _safe_str(llm_result.get("message")) or "Gemini 推演未启用",
        }
        base_report["research_agent"] = _build_research_agent_payload(base_report, research_payload, research_memory)
        return base_report

    llm_data = llm_result.get("data", {}) or {}
    base_report.update(
        {
            "summary": _safe_str(llm_data.get("summary")) or base_report["summary"],
            "trade_bias": _safe_str(llm_data.get("trade_bias")) or base_report["trade_bias"],
            "news_summary": _safe_str(llm_data.get("news_summary")) or base_report["news_summary"],
            "followthrough_view": _safe_str(llm_data.get("future_reasoning")) or base_report["followthrough_view"],
            "execution_plan": _normalize_text_list(llm_data.get("execution_plan"), base_report["execution_plan"], limit=4),
            "risk_flags": _normalize_text_list(llm_data.get("risk_flags"), base_report["risk_flags"], limit=6),
            "relationship_chain": _normalize_text_list(llm_data.get("relationship_chain"), base_report["relationship_chain"], limit=5),
            "future_scenarios": _normalize_text_list(llm_data.get("future_scenarios"), [], limit=4),
            "key_drivers": _normalize_text_list(llm_data.get("key_drivers"), [], limit=5),
            "invalidations": _normalize_text_list(llm_data.get("invalidations"), [], limit=4),
            "tool_insights": _normalize_text_list(llm_data.get("tool_insights"), base_report["tool_insights"], limit=5),
            "market_data_insights": _normalize_text_list(llm_data.get("market_data_insights"), base_report["market_data_insights"], limit=5),
            "market_data_catalog": _normalize_text_list(llm_data.get("market_data_catalog"), base_report["market_data_catalog"], limit=5),
            "analysis_playbook": _normalize_text_list(llm_data.get("analysis_playbook"), base_report["analysis_playbook"], limit=4),
            "actor_signals": _normalize_text_list(llm_data.get("actor_signals"), base_report["actor_signals"], limit=5),
            "multi_agent_consensus": _safe_str(llm_data.get("multi_agent_consensus")) or base_report["multi_agent_consensus"],
            "comprehensive_reasoning": llm_data.get("comprehensive_reasoning") if isinstance(llm_data.get("comprehensive_reasoning"), dict) and llm_data.get("comprehensive_reasoning") else base_report["comprehensive_reasoning"],
            "fx_decision_template": llm_data.get("fx_decision_template") if isinstance(llm_data.get("fx_decision_template"), dict) and llm_data.get("fx_decision_template") else base_report["fx_decision_template"],
            "agent_round_summary": _safe_str(llm_data.get("agent_round_summary")) or base_report["agent_round_summary"],
            "memory_takeaway": _safe_str(llm_data.get("memory_takeaway")) or base_report["memory_takeaway"],
            "key_news": _normalize_key_news(llm_data.get("key_news"), base_report["key_news"]),
            "confidence_score": max(0.0, min(_safe_float(llm_data.get("confidence_score"), base_report["confidence_score"]), 1.0)),
            "ai_status": {
                "enabled": True,
                "provider": llm_result.get("provider", "openrouter"),
                "model": _safe_str(llm_result.get("model")),
                "message": _safe_str(llm_result.get("message")) or "Gemini 推演已启用",
            },
            "reasoning_source": "gemini_llm",
        }
    )
    base_report["research_agent"] = _build_research_agent_payload(base_report, research_payload, research_memory)
    return base_report
