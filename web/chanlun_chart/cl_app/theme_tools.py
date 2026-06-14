#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_ACTOR_LIBRARY = [
    {"name": "美联储", "actor_type": "CentralBank", "keywords": ["美联储", "鲍威尔", "fomc", "fed"], "role": "影响美元方向、利率预期与全球风险资产估值"},
    {"name": "欧洲央行", "actor_type": "CentralBank", "keywords": ["欧洲央行", "ecb", "拉加德"], "role": "影响欧元利率路径与欧洲资产定价"},
    {"name": "日本央行", "actor_type": "CentralBank", "keywords": ["日本央行", "boj", "植田和男"], "role": "影响日元波动与全球套息交易"},
    {"name": "中国央行", "actor_type": "CentralBank", "keywords": ["中国央行", "人民银行", "央行"], "role": "影响人民币流动性、利率和风险偏好"},
    {"name": "特朗普", "actor_type": "PoliticalFigure", "keywords": ["特朗普", "trump"], "role": "影响贸易、选举预期与地缘政治风险"},
    {"name": "美国政府", "actor_type": "Government", "keywords": ["白宫", "美国政府", "财政部", "美国财长"], "role": "影响财政政策、监管与外交路径"},
    {"name": "伊朗", "actor_type": "GeopoliticalActor", "keywords": ["伊朗", "iran"], "role": "影响中东风险溢价与能源供给预期"},
    {"name": "以色列", "actor_type": "GeopoliticalActor", "keywords": ["以色列", "israel"], "role": "影响中东冲突升级与避险需求"},
    {"name": "俄罗斯", "actor_type": "GeopoliticalActor", "keywords": ["俄罗斯", "普京", "russia"], "role": "影响能源供给、地缘溢价与欧洲风险资产"},
    {"name": "乌克兰", "actor_type": "GeopoliticalActor", "keywords": ["乌克兰", "ukraine"], "role": "影响欧洲地缘风险与大宗商品波动"},
    {"name": "OPEC", "actor_type": "CommodityCartel", "keywords": ["opec", "欧佩克"], "role": "影响原油供给、库存预期与能源链定价"},
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_identity(value: str) -> str:
    return re.sub(r"[\W_]+", "", _normalize_text(value).lower())


def _tokenize_theme_keywords(theme_label: str) -> List[str]:
    text = _normalize_text(theme_label)
    if not text:
        return []
    base_tokens = [token.strip() for token in re.split(r"[\s,/|()\-_:：，、]+", text) if token.strip()]
    if text and text not in base_tokens:
        base_tokens.insert(0, text)
    seen = set()
    results: List[str] = []
    for token in base_tokens:
        key = token.lower()
        if key in seen or len(token) < 2:
            continue
        seen.add(key)
        results.append(token)
    return results[:12]


def _dedupe_news(news_items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    seen = set()
    results: List[Dict[str, Any]] = []
    for item in news_items or []:
        title = _normalize_text(item.get("title"))
        identity = _normalize_identity(title) or _normalize_identity(item.get("summary") or "")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def _count_direction(news_items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for item in news_items or []:
        direction = _normalize_text(item.get("impact_direction")).lower()
        if direction not in counts:
            direction = "neutral"
        counts[direction] += 1
    return counts


def _direction_label(direction: str) -> str:
    return {"bullish": "利多", "bearish": "利空", "neutral": "中性"}.get(direction, "中性")


def _build_news_brief(item: Dict[str, Any]) -> str:
    title = _normalize_text(item.get("title")) or "未命名新闻"
    summary = _normalize_text(item.get("direction_reason") or item.get("summary"))[:70]
    published_at = _normalize_text(item.get("published_at"))
    if summary and published_at:
        return f"{title}（{published_at}）：{summary}"
    if summary:
        return f"{title}：{summary}"
    return title


def _build_user_evidence_brief(item: Dict[str, Any]) -> str:
    title = _normalize_text(item.get("title")) or _normalize_text(item.get("file_name")) or "用户材料"
    source_label = _normalize_text(item.get("source_label") or item.get("file_type") or "文档证据")
    summary = _normalize_text(item.get("summary") or item.get("excerpt"))[:80]
    if summary:
        return f"{title}（{source_label}）：{summary}"
    return f"{title}（{source_label}）"


def resolve_theme_definition(
    theme_label: str,
    topic_definitions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    target_text = _normalize_text(theme_label)
    normalized_target = target_text.lower()
    for topic in topic_definitions or []:
        label = _normalize_text(topic.get("label"))
        if not label:
            continue
        if label.lower() == normalized_target or _normalize_text(topic.get("id")).lower() == normalized_target:
            return {
                "id": _normalize_text(topic.get("id")) or _normalize_identity(label) or "custom-theme",
                "label": label,
                "description": _normalize_text(topic.get("description")),
                "keywords": [str(item).strip() for item in topic.get("keywords", []) if str(item).strip()],
                "source": "configured_topic",
            }
    return {
        "id": _normalize_identity(target_text) or "custom-theme",
        "label": target_text or "自定义主题",
        "description": "",
        "keywords": _tokenize_theme_keywords(target_text),
        "source": "ad_hoc_theme",
    }


def filter_theme_news(
    news_items: List[Dict[str, Any]],
    theme_definition: Dict[str, Any],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    keywords = [str(item).strip() for item in theme_definition.get("keywords", []) if str(item).strip()]
    theme_label = _normalize_text(theme_definition.get("label"))
    combined_keywords = [theme_label] + keywords if theme_label else keywords
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in news_items or []:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        title = _normalize_text(item.get("title") or metadata.get("title"))
        summary = _normalize_text(
            item.get("summary") or item.get("direction_reason") or item.get("body") or item.get("content") or item.get("document")
        )
        haystack = f"{title} {summary}".lower()
        hits = [keyword for keyword in combined_keywords if keyword and keyword.lower() in haystack]
        if not hits:
            continue
        identity = _normalize_identity(title)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        enriched = dict(item)
        enriched["title"] = title
        enriched["summary"] = summary
        enriched["published_at"] = _normalize_text(item.get("published_at") or metadata.get("published_at"))
        enriched["importance_score"] = _safe_float(item.get("importance_score") or metadata.get("importance_score"))
        enriched["theme_hits"] = hits[:6]
        enriched["theme_score"] = len(hits) + _safe_float(enriched.get("importance_score"))
        deduped.append(enriched)
    deduped.sort(
        key=lambda news: (
            _safe_float(news.get("theme_score")),
            _safe_float(news.get("importance_score")),
            _normalize_text(news.get("published_at")),
        ),
        reverse=True,
    )
    return deduped[:limit]


def build_theme_entities(
    asset_context: Dict[str, Any],
    theme_definition: Dict[str, Any],
    news_items: List[Dict[str, Any]],
    uploaded_evidence: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    asset_name = _normalize_text(asset_context.get("asset_name") or asset_context.get("current_code"))
    if asset_name:
        entities.append(
            {
                "entity_type": "Asset",
                "name": asset_name,
                "role": "核心交易资产",
                "summary": f"当前推演围绕 {asset_name} 对主题 `{theme_definition.get('label', '')}` 的价格影响展开。",
            }
        )
    if theme_definition.get("label"):
        entities.append(
            {
                "entity_type": "Theme",
                "name": theme_definition.get("label"),
                "role": "核心主题",
                "summary": theme_definition.get("description") or f"围绕 `{theme_definition.get('label')}` 的新闻与传播影响。",
            }
        )
    for news in news_items[:3]:
        title = _normalize_text(news.get("title"))
        if not title:
            continue
        entities.append(
            {
                "entity_type": "Catalyst",
                "name": title,
                "role": "催化事件",
                "summary": _normalize_text(news.get("direction_reason") or news.get("summary") or news.get("body"))[:160],
            }
        )
    for evidence in (uploaded_evidence or [])[:2]:
        evidence_title = _normalize_text(evidence.get("title") or evidence.get("file_name"))
        if not evidence_title:
            continue
        entities.append(
            {
                "entity_type": "UserEvidence",
                "name": evidence_title,
                "role": "用户上传材料",
                "summary": _normalize_text(evidence.get("summary") or evidence.get("excerpt"))[:160],
            }
        )
    return entities[:8]


def build_propagation_chain(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    news_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    theme_label = _normalize_text(theme_definition.get("label")) or "主题事件"
    asset_name = _normalize_text(asset_context.get("asset_name") or asset_context.get("current_code") or "目标资产")
    direction = _normalize_text(asset_context.get("price_direction")) or "neutral"
    direction_label = {"bullish": "偏上行", "bearish": "偏下行", "neutral": "偏震荡"}.get(direction, "偏震荡")
    primary_news = news_items[0] if news_items else {}
    catalyst_title = _normalize_text(primary_news.get("title")) or f"{theme_label}相关事件"
    chain = [
        {
            "step": 1,
            "stage": "主题触发",
            "summary": f"{theme_label} 被市场重新聚焦，核心催化为：{catalyst_title}。",
        },
        {
            "step": 2,
            "stage": "叙事扩散",
            "summary": f"相关消息开始强化主题叙事，影响从新闻标题扩展到市场预期和资产解释框架。",
        },
        {
            "step": 3,
            "stage": "资产定价",
            "summary": f"{asset_name} 当前价格行为显示 {direction_label}，说明主题已经开始进入该资产的交易定价。",
        },
    ]
    if len(news_items) >= 2:
        chain.append(
            {
                "step": 4,
                "stage": "二阶传播",
                "summary": f"后续新闻若继续增加，主题可能从单点事件扩展为连续驱动，进一步影响关联资产与市场情绪。",
            }
        )
    return chain


def build_theme_actor_profiles(
    theme_definition: Dict[str, Any],
    news_items: List[Dict[str, Any]],
    limit: int = 6,
) -> List[Dict[str, Any]]:
    actor_profiles: List[Dict[str, Any]] = []
    for actor in _ACTOR_LIBRARY:
        matched_news = []
        score = 0.0
        direction_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
        for item in news_items or []:
            haystack = f"{_normalize_text(item.get('title'))} {_normalize_text(item.get('summary'))}".lower()
            hits = [keyword for keyword in actor.get("keywords", []) if keyword.lower() in haystack]
            if not hits:
                continue
            matched_news.append(item)
            score += len(hits) + _safe_float(item.get("importance_score"))
            direction = _normalize_text(item.get("impact_direction")).lower()
            if direction not in direction_counts:
                direction = "neutral"
            direction_counts[direction] += 1
        if not matched_news:
            continue
        dominant_direction = max(direction_counts.items(), key=lambda item: item[1])[0]
        if direction_counts[dominant_direction] <= 0:
            dominant_direction = "neutral"
        stance = {
            "bullish": "更偏推动风险偏好或价格上行",
            "bearish": "更偏压制风险偏好或价格下行",
            "neutral": "更多体现为波动放大与等待确认",
        }[dominant_direction]
        actor_profiles.append(
            {
                "name": actor["name"],
                "actor_type": actor["actor_type"],
                "role": actor["role"],
                "stance": stance,
                "summary": f"{actor['name']} 在当前主题样本中出现 {len(matched_news)} 次，{stance}。",
                "matched_news": [_normalize_text(item.get("title")) for item in matched_news[:3] if _normalize_text(item.get("title"))],
                "relevance_score": round(score, 3),
            }
        )
    if actor_profiles:
        actor_profiles.sort(key=lambda item: (item.get("relevance_score", 0.0), len(item.get("matched_news", []))), reverse=True)
        return actor_profiles[:limit]
    theme_label = _normalize_text(theme_definition.get("label"))
    if not theme_label:
        return []
    return [
        {
            "name": theme_label,
            "actor_type": "ThemeDriver",
            "role": "当前主题的直接驱动主体",
            "stance": "等待更多证据确认方向",
            "summary": f"当前尚未识别出明确政策/国家/央行主体，先将 `{theme_label}` 视为主题本身驱动。",
            "matched_news": [_normalize_text(item.get("title")) for item in news_items[:2] if _normalize_text(item.get("title"))],
            "relevance_score": 1.0,
        }
    ]


def build_theme_cross_asset_signals(
    cross_asset_watch: Optional[List[Dict[str, Any]]],
    limit: int = 4,
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    if isinstance(cross_asset_watch, dict):
        source_items = cross_asset_watch.get("items") or cross_asset_watch.get("references") or []
    elif isinstance(cross_asset_watch, list):
        source_items = cross_asset_watch
    else:
        source_items = []
    for item in source_items[:limit]:
        name = _normalize_text(item.get("name") or item.get("code"))
        if not name:
            continue
        signals.append(
            {
                "name": name,
                "code": _normalize_text(item.get("code")),
                "alignment_label": _normalize_text(item.get("alignment_label") or item.get("status_label") or "联动观察"),
                "change_5m_pct": _safe_float(item.get("change_5m_pct")),
                "change_30m_pct": _safe_float(item.get("change_30m_pct")),
                "summary": _normalize_text(item.get("reason") or item.get("status_label") or f"{name} 被纳入联动观察。"),
            }
        )
    return signals


def build_theme_evidence_matrix(
    asset_context: Dict[str, Any],
    direct_news: List[Dict[str, Any]],
    driver_news: List[Dict[str, Any]],
    background_news: List[Dict[str, Any]],
    uploaded_evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    uploaded_evidence = uploaded_evidence or []
    combined_news = direct_news + driver_news + background_news + uploaded_evidence
    direction_counts = _count_direction(combined_news)
    dominant_direction = max(direction_counts.items(), key=lambda item: item[1])[0]
    if direction_counts[dominant_direction] <= 0:
        dominant_direction = "neutral"
    price_direction = _normalize_text(asset_context.get("price_direction")).lower() or "neutral"
    contradiction_flags: List[str] = []
    if not direct_news:
        contradiction_flags.append("当前缺少直接证据新闻，更多依赖驱动链条与背景验证。")
    if dominant_direction != "neutral" and price_direction not in ("", "neutral") and dominant_direction != price_direction:
        contradiction_flags.append(
            f"新闻主方向偏{_direction_label(dominant_direction)}，但价格当前表现为 {price_direction}，需要警惕抢跑或反身性回吐。"
        )
    if not contradiction_flags and direction_counts["neutral"] >= max(direction_counts["bullish"], direction_counts["bearish"]):
        contradiction_flags.append("现有证据偏中性，主题更像波动放大器，暂不宜过度下注单边。")
    return {
        "total_news": len(combined_news),
        "bucket_counts": {
            "direct": len(direct_news),
            "driver": len(driver_news),
            "background": len(background_news),
            "uploaded": len(uploaded_evidence),
        },
        "direction_counts": direction_counts,
        "dominant_direction": dominant_direction,
        "headline_titles": [_normalize_text(item.get("title")) for item in combined_news[:4] if _normalize_text(item.get("title"))],
        "contradiction_flags": contradiction_flags,
    }


def build_theme_similar_cases(
    background_news: List[Dict[str, Any]],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for item in _dedupe_news(background_news, limit):
        title = _normalize_text(item.get("title"))
        if not title:
            continue
        cases.append(
            {
                "title": title,
                "published_at": _normalize_text(item.get("published_at")),
                "summary": _normalize_text(item.get("summary") or item.get("direction_reason"))[:120],
                "why_relevant": "可用作类似事件参照，帮助判断本次主题是否会延续、钝化或反转。",
            }
        )
    return cases


def build_theme_research_tools(
    asset_context: Dict[str, Any],
    direct_news: List[Dict[str, Any]],
    driver_news: List[Dict[str, Any]],
    background_news: List[Dict[str, Any]],
    cross_asset_signals: List[Dict[str, Any]],
    uploaded_evidence: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    uploaded_evidence = uploaded_evidence or []
    evidence_matrix = build_theme_evidence_matrix(asset_context, direct_news, driver_news, background_news, uploaded_evidence)
    direct_headlines = [_build_news_brief(item) for item in direct_news[:3]]
    driver_headlines = [_build_news_brief(item) for item in driver_news[:3]]
    tools.append(
        {
            "tool": "theme_news_scan",
            "label": "主题证据扫描",
            "summary": f"直接证据 {len(direct_news)} 条，驱动证据 {len(driver_news)} 条，新闻主方向为 {_direction_label(evidence_matrix['dominant_direction'])}。",
            "highlights": direct_headlines or ["暂无足够直接证据，需继续观察后续催化。"],
            "confidence": 0.72 if direct_news else 0.42,
        }
    )
    if uploaded_evidence:
        tools.append(
            {
                "tool": "uploaded_material_probe",
                "label": "用户材料证据",
                "summary": f"用户上传材料 {len(uploaded_evidence)} 份，已纳入本轮主题推演证据池。",
                "highlights": [_build_user_evidence_brief(item) for item in uploaded_evidence[:3]],
                "confidence": 0.78,
            }
        )
    tools.append(
        {
            "tool": "driver_chain_probe",
            "label": "传导链复核",
            "summary": "检查主题是否已经从单条消息扩散到宏观叙事、政策预期或产业链定价。",
            "highlights": driver_headlines or ["当前传导链仍偏短，尚未形成强共识。"],
            "confidence": 0.68 if driver_news else 0.38,
        }
    )
    tools.append(
        {
            "tool": "cross_asset_probe",
            "label": "跨资产共振",
            "summary": "验证是否存在汇率、利率、黄金、原油或股指等联动信号来支持主题持续。",
            "highlights": [
                f"{item['name']}：{item['alignment_label']} · 5分钟 {item['change_5m_pct']:+.3f}% · 30分钟 {item['change_30m_pct']:+.3f}%"
                for item in cross_asset_signals[:3]
            ]
            or ["暂无明显跨资产共振，当前主题更依赖单资产定价。"],
            "confidence": 0.7 if cross_asset_signals else 0.35,
        }
    )
    tools.append(
        {
            "tool": "analog_case_search",
            "label": "类似事件搜索",
            "summary": "抽取历史相近叙事作为参照，帮助判断这次是持续主线还是一次性冲击。",
            "highlights": [_build_news_brief(item) for item in background_news[:3]] or ["当前缺少足够相似样本，需谨慎外推。"],
            "confidence": 0.58 if background_news else 0.3,
        }
    )
    if evidence_matrix["contradiction_flags"]:
        tools.append(
            {
                "tool": "contradiction_check",
                "label": "背离检查",
                "summary": "复核新闻、价格与跨资产信号之间是否存在背离。",
                "highlights": evidence_matrix["contradiction_flags"][:3],
                "confidence": 0.6,
            }
        )
    return tools


def _dedupe_terms(terms: List[str], limit: int = 12) -> List[str]:
    results: List[str] = []
    seen = set()
    for term in terms:
        normalized_term = _normalize_text(term)
        identity = normalized_term.lower()
        if not normalized_term or identity in seen:
            continue
        seen.add(identity)
        results.append(normalized_term)
        if len(results) >= limit:
            break
    return results


def _asset_probe_terms(asset_context: Dict[str, Any]) -> List[str]:
    current_code = _normalize_text(asset_context.get("current_code")).upper()
    asset_name = _normalize_text(asset_context.get("asset_name"))
    base_terms = [asset_name, current_code]
    asset_probe_map = {
        "EURUSD": ["美元指数", "美债收益率", "欧洲央行", "欧元"],
        "USDJPY": ["美元指数", "美债收益率", "日本央行", "日元"],
        "XAU": ["美元指数", "美债收益率", "实际利率", "避险"],
        "CL": ["OPEC", "原油库存", "中东局势", "布伦特"],
        "USDCNY": ["人民币", "中美关系", "中国央行", "美元指数"],
    }
    return _dedupe_terms(base_terms + asset_probe_map.get(current_code, ["美元", "利率", "风险情绪", "避险"]), limit=8)


def _extract_focus_terms(theme_definition: Dict[str, Any], toolkit_payload: Dict[str, Any]) -> Dict[str, List[str]]:
    theme_terms = [theme_definition.get("label", "")] + list(theme_definition.get("keywords", []) or [])
    actor_terms = [item.get("name", "") for item in (toolkit_payload.get("actor_profiles") or [])[:3]]
    headline_terms: List[str] = []
    for item in (toolkit_payload.get("theme_news") or [])[:3]:
        headline_terms.extend(_tokenize_theme_keywords(_normalize_text(item.get("title"))))
    return {
        "theme_terms": _dedupe_terms(theme_terms, limit=8),
        "actor_terms": _dedupe_terms(actor_terms, limit=4),
        "headline_terms": _dedupe_terms(headline_terms, limit=8),
    }


def build_theme_research_rounds(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    toolkit_payload: Dict[str, Any],
    completed_focuses: Optional[List[str]] = None,
    max_rounds: int = 2,
) -> List[Dict[str, Any]]:
    completed_focuses = completed_focuses or []
    evidence_matrix = toolkit_payload.get("evidence_matrix", {}) or {}
    contradiction_flags = evidence_matrix.get("contradiction_flags", []) or []
    direct_count = len(toolkit_payload.get("direct_theme_news", []) or [])
    background_count = len(toolkit_payload.get("background_theme_news", []) or [])
    cross_asset_count = len(toolkit_payload.get("cross_asset_signals", []) or [])
    focus_terms = _extract_focus_terms(theme_definition, toolkit_payload)
    probe_terms = _asset_probe_terms(asset_context)
    theme_label = _normalize_text(theme_definition.get("label")) or "主题"
    asset_name = _normalize_text(asset_context.get("asset_name") or asset_context.get("current_code")) or "目标资产"
    round_candidates: List[Dict[str, Any]] = [
        {
            "focus": "direct_evidence",
            "objective": "补强当前主题的直接催化和一手证据",
            "query_text": f"{theme_label} {asset_name}",
            "search_terms": _dedupe_terms(
                focus_terms["theme_terms"] + focus_terms["actor_terms"] + focus_terms["headline_terms"] + [asset_name, "政策", "讲话", "声明"],
                limit=14,
            ),
            "triggered_by": {
                "direct_count": direct_count,
                "contradictions": contradiction_flags[:2],
            },
        },
        {
            "focus": "cross_asset_and_analog",
            "objective": "补跨资产验证和类似事件参照",
            "query_text": f"{theme_label} 联动资产",
            "search_terms": _dedupe_terms(
                focus_terms["theme_terms"] + focus_terms["actor_terms"] + probe_terms + ["历史", "再度", "联动"],
                limit=14,
            ),
            "triggered_by": {
                "cross_asset_count": cross_asset_count,
                "background_count": background_count,
            },
        },
    ]
    prioritized_candidates: List[Dict[str, Any]] = []
    for candidate in round_candidates:
        if candidate["focus"] in completed_focuses:
            continue
        priority = 0
        if candidate["focus"] == "direct_evidence":
            priority = 3 if direct_count < 2 else 2 if contradiction_flags else 1
        elif candidate["focus"] == "cross_asset_and_analog":
            priority = 3 if cross_asset_count < 2 or background_count < 2 else 1
        candidate["priority"] = priority
        prioritized_candidates.append(candidate)
    prioritized_candidates.sort(key=lambda item: item.get("priority", 0), reverse=True)
    rounds: List[Dict[str, Any]] = []
    for index, candidate in enumerate(prioritized_candidates[:max_rounds], start=1):
        rounds.append(
            {
                "round_id": index,
                "focus": candidate["focus"],
                "objective": candidate["objective"],
                "query_text": candidate["query_text"],
                "search_terms": candidate["search_terms"],
                "priority": candidate["priority"],
                "triggered_by": candidate["triggered_by"],
            }
        )
    return rounds


def build_theme_toolkit_payload(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    direct_news: List[Dict[str, Any]],
    driver_news: List[Dict[str, Any]],
    background_news: Optional[List[Dict[str, Any]]] = None,
    cross_asset_watch: Optional[List[Dict[str, Any]]] = None,
    uploaded_evidence: Optional[List[Dict[str, Any]]] = None,
    max_news: int = 8,
) -> Dict[str, Any]:
    direct_matches = filter_theme_news(direct_news, theme_definition, limit=max_news)
    driver_matches = filter_theme_news(driver_news, theme_definition, limit=max_news)
    background_matches = filter_theme_news(background_news or [], theme_definition, limit=max_news)
    uploaded_matches = filter_theme_news(uploaded_evidence or [], theme_definition, limit=max_news)
    combined_news = sorted(
        direct_matches + driver_matches + background_matches + uploaded_matches,
        key=lambda item: (
            _safe_float(item.get("theme_score")),
            _safe_float(item.get("importance_score")),
            _normalize_text(item.get("published_at")),
        ),
        reverse=True,
    )
    combined_news = _dedupe_news(combined_news, max_news)
    entities = build_theme_entities(asset_context, theme_definition, combined_news, uploaded_matches)
    propagation_chain = build_propagation_chain(theme_definition, asset_context, combined_news)
    actor_profiles = build_theme_actor_profiles(theme_definition, combined_news)
    cross_asset_signals = build_theme_cross_asset_signals(cross_asset_watch)
    evidence_matrix = build_theme_evidence_matrix(asset_context, direct_matches, driver_matches, background_matches, uploaded_matches)
    similar_cases = build_theme_similar_cases(background_matches)
    research_tools = build_theme_research_tools(
        asset_context=asset_context,
        direct_news=direct_matches,
        driver_news=driver_matches,
        background_news=background_matches,
        cross_asset_signals=cross_asset_signals,
        uploaded_evidence=uploaded_matches,
    )
    research_digest = (
        f"直接证据 {len(direct_matches)} 条，驱动链 {len(driver_matches)} 条，背景参照 {len(background_matches)} 条；"
        f"用户材料 {len(uploaded_matches)} 份；当前共振资产 {len(cross_asset_signals)} 个，识别主体 {len(actor_profiles)} 个。"
    )
    return {
        "theme_definition": theme_definition,
        "theme_news": combined_news[:max_news],
        "direct_theme_news": direct_matches,
        "driver_theme_news": driver_matches,
        "background_theme_news": background_matches,
        "uploaded_theme_evidence": uploaded_matches,
        "entities": entities,
        "propagation_chain": propagation_chain,
        "actor_profiles": actor_profiles,
        "cross_asset_signals": cross_asset_signals,
        "evidence_matrix": evidence_matrix,
        "similar_cases": similar_cases,
        "research_tools": research_tools,
        "research_digest": research_digest,
    }
