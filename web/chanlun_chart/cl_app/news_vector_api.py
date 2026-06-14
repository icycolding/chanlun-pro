#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻向量数据库API模块
提供向量数据库相关的API接口，包括语义搜索、相似新闻查找、情感分析等功能
"""

import datetime
import io
import json
import os
import time
import base64
import re
import hashlib
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any, Union
# from fix_chroma_timezone import response
from flask import request, jsonify
from flask_login import login_required, current_user
import logging
# from chanlun.tools.ai_analyze import req_llm_ai_model # 移到函数内部，按需导入
from chanlun.tools.ai_analyse import AIAnalyse  # 原始AI分析类
from chanlun.db import db
from .news_vector_db import get_vector_db
from .asset_news_mapping import (
    deduplicate_terms as asset_deduplicate_terms,
    build_asset_link_rows,
    get_asset_context_terms,
    infer_asset_impact_direction,
    infer_news_asset_links,
    normalize_asset_code as asset_normalize_asset_code,
)
from .timesfm_service import (
    build_event_forecast,
    build_forecast_risk_overlay,
    build_timesfm_covariates,
    generate_timesfm_forecast_bundle,
    get_timesfm_native_runtime_status,
)
from .theme_tools import (
    build_theme_research_rounds,
    build_theme_toolkit_payload,
    resolve_theme_definition,
)
from .theme_ontology_service import build_theme_ontology
from .theme_reasoning_agent import build_theme_reasoning_report
from .market_data_adapter import (
    AkshareMarketDataAdapter,
    get_akshare_futures_symbol_name,
    normalize_akshare_futures_symbol,
)
from chanlun.exchange import get_exchange, Market
from chanlun import config
from datetime import datetime, timedelta
from cl_app.enhanced_market_search import EnhancedMarketSearch

# 配置日志
logger = logging.getLogger(__name__)

_MARKET_SUMMARY_TASKS: Dict[str, Dict[str, Any]] = {}
_MARKET_SUMMARY_TASK_LOCK = threading.Lock()
_MARKET_SUMMARY_TASK_KEEP_LIMIT = 20
_SUMMARY_TASK_CACHE_PREFIX = "news_summary_task:"
_SUMMARY_TASK_EXPIRE_SECONDS = 24 * 3600
_SUMMARY_RESULT_CACHE_PREFIX = "news_summary_result:"
_SUMMARY_RESULT_EXPIRE_SECONDS = 6 * 3600
_PRICE_BAR_FALLBACK_LOG_STATE: Dict[str, float] = {}
_PRICE_BAR_FALLBACK_LOG_INTERVAL_SECONDS = 600
_THEME_RESEARCH_MEMORY_PREFIX = "theme_research_memory:"
_THEME_RESEARCH_MEMORY_EXPIRE_SECONDS = 14 * 24 * 3600


def _trim_market_summary_tasks() -> None:
    if len(_MARKET_SUMMARY_TASKS) <= _MARKET_SUMMARY_TASK_KEEP_LIMIT:
        return

    ordered_ids = sorted(
        _MARKET_SUMMARY_TASKS.keys(),
        key=lambda task_id: _MARKET_SUMMARY_TASKS[task_id].get("updated_at", ""),
    )
    for task_id in ordered_ids[:-_MARKET_SUMMARY_TASK_KEEP_LIMIT]:
        _MARKET_SUMMARY_TASKS.pop(task_id, None)


def _summary_task_cache_key(task_id: str) -> str:
    return f"{_SUMMARY_TASK_CACHE_PREFIX}{task_id}"


def _save_summary_task_to_cache(task_id: str, task: Dict[str, Any]) -> None:
    try:
        db.cache_set(
            _summary_task_cache_key(task_id),
            task,
            expire=int(time.time()) + _SUMMARY_TASK_EXPIRE_SECONDS,
        )
    except Exception as e:
        logger.warning(f"保存总结任务缓存失败: {str(e)}")


def _set_market_summary_task(task_key: str, **updates: Any) -> Dict[str, Any]:
    with _MARKET_SUMMARY_TASK_LOCK:
        task = _MARKET_SUMMARY_TASKS.setdefault(task_key, {})
        task.setdefault("task_id", task_key)
        task.update(updates)
        task["updated_at"] = datetime.now().isoformat()
        _trim_market_summary_tasks()
        task_snapshot = dict(task)
    _save_summary_task_to_cache(task_key, task_snapshot)
    return task_snapshot


def _get_market_summary_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _MARKET_SUMMARY_TASK_LOCK:
        task = _MARKET_SUMMARY_TASKS.get(task_id)
        if task:
            return dict(task)

    cached_task = db.cache_get(_summary_task_cache_key(task_id))
    if cached_task:
        with _MARKET_SUMMARY_TASK_LOCK:
            _MARKET_SUMMARY_TASKS[task_id] = dict(cached_task)
        return dict(cached_task)

    return None


def _summary_result_cache_key(task_type: str, payload: Dict[str, Any]) -> str:
    normalized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    cache_digest = hashlib.md5(normalized_payload.encode("utf-8")).hexdigest()
    return f"{_SUMMARY_RESULT_CACHE_PREFIX}{task_type}:{cache_digest}"


def _log_price_bar_fallback(
    purpose: str,
    fallback_type: str,
    market: str,
    code: str,
    resolved_code: str,
    frequency: str,
    count: int,
) -> None:
    now_ts = time.time()
    log_key = "|".join(
        [
            purpose or "价格分析",
            fallback_type,
            market or "",
            code or "",
            resolved_code or "",
            frequency or "",
        ]
    )
    last_logged_at = _PRICE_BAR_FALLBACK_LOG_STATE.get(log_key, 0.0)
    if now_ts - last_logged_at < _PRICE_BAR_FALLBACK_LOG_INTERVAL_SECONDS:
        return
    _PRICE_BAR_FALLBACK_LOG_STATE[log_key] = now_ts
    logger.info(
        "%s价格数据不足，回退到%s market=%s code=%s resolved_code=%s frequency=%s count=%s",
        purpose or "价格分析",
        fallback_type,
        market,
        code,
        resolved_code,
        frequency,
        count,
    )


def _load_summary_result_cache(task_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cache_key = _summary_result_cache_key(task_type, payload)
    cached_result = db.cache_get(cache_key)
    if not cached_result:
        return None

    should_probe_native_refresh = False
    native_enabled = False
    backend_name = ""
    if task_type == "market_summary":
        if cached_result.get("timesfm_forecast"):
            should_probe_native_refresh = True
            backend_name = str(((cached_result.get("timesfm_forecast") or {}).get("backend", "") or ""))
            native_enabled = bool(
                (((cached_result.get("timesfm_forecast") or {}).get("backend_details") or {}).get("native_enabled"))
            )
    elif task_type in {"timesfm_forecast", "timesfm_event_forecast"}:
        should_probe_native_refresh = True
        backend_name = str((cached_result.get("backend", "") or ""))
        native_enabled = bool(((cached_result.get("backend_details") or {}).get("native_enabled")))
    if backend_name == "timesfm_proxy":
        return None
    if should_probe_native_refresh and not native_enabled:
        runtime_status = get_timesfm_native_runtime_status()
        if runtime_status.get("available") and backend_name == "timesfm_native_unavailable":
            return None

    result = dict(cached_result)
    result["cache_hit"] = True
    return result


def _save_summary_result_cache(task_type: str, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
    cache_key = _summary_result_cache_key(task_type, payload)
    cache_result = dict(result)
    cache_result["cache_hit"] = False
    cache_result["cached_at"] = datetime.now().isoformat()
    try:
        db.cache_set(
            cache_key,
            cache_result,
            expire=int(time.time()) + _SUMMARY_RESULT_EXPIRE_SECONDS,
        )
    except Exception as e:
        logger.warning(f"保存总结结果缓存失败: {str(e)}")


def _theme_research_memory_key(current_market: str, current_code: str, theme_id: str) -> str:
    return f"{_THEME_RESEARCH_MEMORY_PREFIX}{current_market}:{current_code}:{theme_id}"


def _build_theme_research_memory_summary(memory: Dict[str, Any]) -> str:
    if not memory:
        return "这是该主题的首次研究，会话内尚未形成历史记忆。"
    run_count = int(memory.get("run_count", 0) or 0)
    last_trade_bias = str(memory.get("last_trade_bias") or "观望")
    theme_shift = str(memory.get("theme_shift") or "").strip()
    return f"该主题已累计研究 {run_count} 次，最近一次结论为 {last_trade_bias}。{theme_shift or '当前结论保持稳定。'}"


def _load_theme_research_memory(
    current_market: str,
    current_code: str,
    theme_definition: Dict[str, Any],
) -> Dict[str, Any]:
    theme_id = str(theme_definition.get("id") or theme_definition.get("label") or "custom-theme").strip()
    if not current_market or not current_code or not theme_id:
        return {}
    memory = db.cache_get(_theme_research_memory_key(current_market, current_code, theme_id)) or {}
    if not isinstance(memory, dict):
        return {}
    memory["memory_summary"] = _build_theme_research_memory_summary(memory)
    return memory


def _save_theme_research_memory(
    current_market: str,
    current_code: str,
    theme_definition: Dict[str, Any],
    report: Dict[str, Any],
    toolkit_payload: Dict[str, Any],
    retrieval_summary: Dict[str, Any],
) -> Dict[str, Any]:
    theme_id = str(theme_definition.get("id") or theme_definition.get("label") or "custom-theme").strip()
    if not current_market or not current_code or not theme_id:
        return {}
    cache_key = _theme_research_memory_key(current_market, current_code, theme_id)
    current_memory = db.cache_get(cache_key) or {}
    if not isinstance(current_memory, dict):
        current_memory = {}
    updated_at = datetime.now().isoformat()
    last_trade_bias = str(report.get("trade_bias") or "观望")
    previous_trade_bias = str(current_memory.get("last_trade_bias") or "").strip()
    recent_runs = list(current_memory.get("recent_runs") or [])
    recent_runs.insert(
        0,
        {
            "updated_at": updated_at,
            "summary": str(report.get("summary") or ""),
            "trade_bias": last_trade_bias,
            "confidence_score": float(report.get("confidence_score") or 0.0),
            "evidence_count": len(toolkit_payload.get("theme_news", []) or []),
            "tool_count": len(toolkit_payload.get("research_tools", []) or []),
            "search_terms": list(retrieval_summary.get("search_terms") or [])[:8],
            "headline_titles": [str(item.get("title") or "") for item in (toolkit_payload.get("theme_news") or [])[:3]],
        },
    )
    recent_runs = recent_runs[:6]
    bias_distribution = {"顺势看多": 0, "顺势看空": 0, "观望": 0}
    for item in recent_runs:
        bias = str(item.get("trade_bias") or "观望")
        if bias not in bias_distribution:
            bias_distribution[bias] = 0
        bias_distribution[bias] += 1
    theme_shift = (
        f"结论由 {previous_trade_bias} 切换为 {last_trade_bias}，说明最新证据正在改变市场解读。"
        if previous_trade_bias and previous_trade_bias != last_trade_bias
        else f"最近结论继续维持 {last_trade_bias}。"
    )
    memory = {
        "theme_id": theme_id,
        "theme_label": str(theme_definition.get("label") or ""),
        "current_market": current_market,
        "current_code": current_code,
        "run_count": int(current_memory.get("run_count", 0) or 0) + 1,
        "last_updated": updated_at,
        "last_trade_bias": last_trade_bias,
        "last_summary": str(report.get("summary") or ""),
        "last_confidence_score": float(report.get("confidence_score") or 0.0),
        "bias_distribution": bias_distribution,
        "theme_shift": theme_shift,
        "recent_runs": recent_runs,
    }
    memory["memory_summary"] = _build_theme_research_memory_summary(memory)
    try:
        db.cache_set(cache_key, memory, expire=int(time.time()) + _THEME_RESEARCH_MEMORY_EXPIRE_SECONDS)
    except Exception as e:
        logger.warning(f"保存主题研究记忆失败: {str(e)}")
    return memory


def own_query_llm(query: str, product_code: Optional[str], product_info: Optional[Dict[str, Any]] = None) -> str:
        
        # 2. 定义强大的Prompt模板，指导LLM进行思考
    prompt_template = """
    你是一位顶级的金融情报分析师，专长是为特定的金融资产构建全面的、多语言的信息检索策略。

    你的任务是：根据用户提供的**【目标资产】**，生成一个结构化的**【新闻检索计划】**。这个计划将用于后续的向量数据库混合搜索。

    **【目标资产】**: {product_info}

    **【新闻检索计划】**必须包含以下几个部分，并以JSON格式严格输出：

    1.  `primary_semantic_query` (string): 一个核心的、语义丰富的长查询，用于向量相似度搜索。这个查询应概括影响该资产所有可能的关键驱动因素。
    2.  `keywords_zh` (list of strings): 一个中文关键词列表。这些词是与资产最直接相关的核心概念。
    3.  `keywords_en` (list of strings): 一个英文关键词列表。内容应与中文关键词列表相对应，用于跨语言检索。

    **思考指南 (请在内部遵循此逻辑，但不要在输出中展示):**
    - 对于**外汇** (如EURUSD)，要考虑两个经济体（欧洲、美国）、各自的央行（ECB, FED）、关键经济数据（CPI, 非农）和领导人（拉加德, 鲍威尔）。
    - 对于**股票** (如浦发银行)，要考虑其所在行业（银行业）、国家宏观政策（货币政策、房地产）、公司基本面（盈利、不良贷款）和监管环境。
    - 对于**大宗商品** (如黄金)，要考虑其金融属性（通胀对冲、避险）、与美元的关系（DXY）、利率环境（实际利率）和供需（央行购金）。
    - 对于**指数** (如上证指数)，要考虑构成指数的权重板块、整体经济状况和市场情绪。

    ---
    现在，请为以下目标资产生成新闻检索计划。请严格按照JSON格式输出，不要有任何额外的说明或注释。

    **【目标资产】**: {product_info_json}
    """
    response = llm.invoke(prompt_template.format(product_info=product_info))
    return response.content
def _create_optimized_search_query(query: str, product_code: Optional[str], product_info: Optional[Dict[str, Any]] = None) -> str:
    """
    一个统一的函数，用于创建优化的搜索查询。
    它整合了产品信息获取、查询增强和特定优化规则。

    Args:
        query: 用户的原始查询字符串。
        product_code: 用户指定的产品代码，可能为空。

    Returns:
        str: 经过优化的、用于向量搜索的最终查询字符串。
    """
    # 步骤 1: 获取产品信息
    # 如果外部没有提供产品信息，则内部获取
    if product_info is None:
        code_to_lookup = product_code.strip().upper() if product_code else query.strip().upper()
        product_info = _get_product_info(code_to_lookup)
    print('product_info',product_info)
    # 步骤 2: 构建增强的搜索查询
    keywords = set()
    # 添加原始查询
    keywords.add(query.strip())

    if product_info and product_info.get('type') != 'unknown':
        # 添加产品信息中的关键词
        if 'keywords' in product_info and product_info['keywords']:
            for kw in product_info['keywords']:
                keywords.add(kw)
        
        # 添加中英文名称
        for name_key in ['name_cn', 'name_en', 'cn_name', 'en_name']:
            if name_key in product_info:
                keywords.add(product_info[name_key])

        # 对于外汇，添加货币对的另一种写法
        if product_info.get('type') == 'forex':
            base = product_info.get('base_currency')
            quote = product_info.get('quote_currency')
            if base and quote:
                keywords.add(f'{base}/{quote}')

    # 移除空字符串并合并
    keywords.discard('')
    enhanced_query = ' '.join(sorted(list(keywords)))

    # 步骤 3: 针对货币搜索进行特定优化
    optimizations = {
        '欧美': '欧元 美元',
        '镑美': '英镑 美元',
        '美日': '美元 日元',
        '澳美': '澳元 美元',
        '美加': '美元 加元',
        '美瑞': '美元 瑞郎',
        '沪金': '黄金期货',
    }
    
    optimized_query = enhanced_query
    for term, replacement in optimizations.items():
        if term in optimized_query:
            # 使用括号和OR逻辑增强，而不是简单替换
            optimized_query += f' OR ({replacement})'
            
    logger.debug(f"Optimized query from '{query}' with code '{product_code}' to '{optimized_query}'")
    return optimized_query,product_info


def _deduplicate_terms(terms: List[str]) -> List[str]:
    return asset_deduplicate_terms(terms)


def _build_news_search_terms(
    query: str = "",
    product_code: Optional[str] = None,
    product_info: Optional[Dict[str, Any]] = None,
    stock_info: Optional[Dict[str, Any]] = None,
) -> List[str]:
    terms = []

    if query:
        terms.append(query)
        for token in re.split(r"[\s,/|()]+", query):
            if len(token.strip()) >= 2:
                terms.append(token.strip())

    if product_code:
        terms.extend(
            [
                product_code,
                product_code.replace("FE.", ""),
                product_code.replace("KH.", ""),
                product_code.replace("SH.", ""),
                product_code.replace("SZ.", ""),
            ]
        )

    if stock_info:
        terms.extend(
            [
                stock_info.get("name", ""),
                stock_info.get("code", ""),
            ]
        )

    if product_info:
        for key in [
            "name_cn",
            "name_en",
            "cn_name",
            "en_name",
            "description",
            "symbol",
        ]:
            terms.append(product_info.get(key, ""))
        terms.extend(product_info.get("keywords", []) or [])

    return _deduplicate_terms(terms)


def _normalize_asset_code(product_code: Optional[str]) -> str:
    return asset_normalize_asset_code(product_code)


def _enrich_product_info_with_akshare_symbol(product_info: Dict[str, Any], product_code: str) -> Dict[str, Any]:
    info = dict(product_info or {})
    symbol_candidates = [
        info.get("akshare_symbol"),
        info.get("symbol"),
        info.get("name_cn"),
        info.get("cn_name"),
        info.get("name_en"),
        product_code,
        info.get("original_code"),
    ]
    akshare_symbol = ""
    for candidate in symbol_candidates:
        akshare_symbol = normalize_akshare_futures_symbol(candidate)
        if akshare_symbol:
            break
    info["akshare_symbol"] = akshare_symbol
    if akshare_symbol and not info.get("symbol") and str(info.get("type") or "").lower() in {"futures", "commodity", "commodity_futures", "股指期货", "futures_index"}:
        info["symbol"] = akshare_symbol
    if akshare_symbol:
        info["akshare_name_cn"] = get_akshare_futures_symbol_name(akshare_symbol) or str(info.get("name_cn") or info.get("cn_name") or "")
    return info


def _build_fx_market_data_profile(current_code: str, product_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    info = dict(product_info or {})
    canonical_code = _normalize_asset_code(current_code or info.get("symbol") or info.get("canonical_code"))
    base_currency = str(info.get("base_currency") or "").strip().upper()
    quote_currency = str(info.get("quote_currency") or "").strip().upper()
    bank_mapping = {
        "USD": "federal_reserve",
        "EUR": "ecb",
        "GBP": "boe",
        "JPY": "boj",
        "AUD": "rba",
        "NZD": "rbnz",
        "CHF": "snb",
        "CAD": "boc",
        "CNY": "pboc",
        "CNH": "pboc",
    }
    central_banks: List[str] = []
    for currency in [base_currency, quote_currency]:
        bank = bank_mapping.get(currency)
        if bank and bank not in central_banks:
            central_banks.append(bank)

    aliases = [
        canonical_code,
        str(info.get("symbol") or "").strip().upper(),
        str(info.get("name_cn") or "").strip(),
        str(info.get("name_en") or "").strip(),
    ]
    aliases.extend(info.get("aliases", []) or [])
    aliases.extend([base_currency, quote_currency])
    if canonical_code == "USDCNY":
        aliases.extend(["USDCNH", "USD/CNY", "USD/CNH", "美元兑人民币", "美元兑离岸人民币"])
    if canonical_code == "USDCNH":
        aliases.extend(["USDCNY", "USD/CNH", "USD/CNY", "美元兑离岸人民币", "美元兑人民币"])
    normalized_aliases: List[str] = []
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if alias_text and alias_text not in normalized_aliases:
            normalized_aliases.append(alias_text)

    cftc_symbol = ""
    if base_currency and base_currency != "USD":
        cftc_symbol = base_currency
    elif quote_currency:
        cftc_symbol = quote_currency
    if canonical_code in {"USDCNY", "USDCNH"}:
        cftc_symbol = ""

    return {
        "canonical_code": canonical_code,
        "aliases": normalized_aliases,
        "central_banks": central_banks,
        "cftc_symbol": cftc_symbol,
        "base_currency": base_currency,
        "quote_currency": quote_currency,
    }


def _build_fx_pair_specialist_profile(current_code: str, product_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fx_profile = _build_fx_market_data_profile(current_code, product_info)
    canonical_code = str(fx_profile.get("canonical_code") or current_code or "").strip().upper()
    base_currency = str(fx_profile.get("base_currency") or "").strip().upper()
    quote_currency = str(fx_profile.get("quote_currency") or "").strip().upper()
    profile = {
        "pair_code": canonical_code,
        "label": "货币对专属 Agent",
        "role": "货币对结构与特殊机制",
        "description": "聚焦该货币对独有的传导链和失效条件。",
        "focus_points": ["相对强弱", "特殊政策约束", "跨资产验证", "失效条件"],
        "theme_keywords": [canonical_code, base_currency, quote_currency],
    }
    mapping = {
        "EURUSD": {
            "label": "欧美相对增长 Agent",
            "role": "欧美增长与利差相对强弱",
            "description": "聚焦美联储与欧洲央行路径、欧美增长差和美元主线。",
            "focus_points": ["欧央行路径", "欧美利差", "欧元区增长", "美元主线"],
            "theme_keywords": ["欧元", "欧洲央行", "德国国债", "美元", "美债", "欧元区"],
        },
        "GBPUSD": {
            "label": "英镑通胀路径 Agent",
            "role": "英国通胀黏性与英美利差",
            "description": "聚焦英国工资与通胀黏性、BoE 路径和美元主线。",
            "focus_points": ["英国通胀", "工资", "BoE", "英美利差"],
            "theme_keywords": ["英镑", "英国央行", "工资", "CPI", "英国国债"],
        },
        "USDJPY": {
            "label": "日元干预 Agent",
            "role": "美债收益率与日央行干预机制",
            "description": "聚焦美债收益率、日央行口径、套息交易和平准干预。",
            "focus_points": ["美债收益率", "日央行", "干预", "套息交易"],
            "theme_keywords": ["日元", "日本央行", "干预", "财务省", "美债", "收益率"],
        },
        "AUDUSD": {
            "label": "澳元商品链 Agent",
            "role": "中国增长与商品链传导",
            "description": "聚焦 RBA、中国增长、铁矿石/铜和全球风险偏好。",
            "focus_points": ["RBA", "中国增长", "铁矿石", "铜", "风险偏好"],
            "theme_keywords": ["澳元", "澳洲联储", "中国", "铁矿石", "铜", "风险偏好"],
        },
        "NZDUSD": {
            "label": "纽元风险偏好 Agent",
            "role": "纽元利率与风险偏好传导",
            "description": "聚焦 RBNZ、乳制品出口、风险资产和美元主线。",
            "focus_points": ["RBNZ", "风险偏好", "出口价格", "美元主线"],
            "theme_keywords": ["纽元", "新西兰联储", "乳制品", "风险偏好", "美元"],
        },
        "USDCNH": {
            "label": "离岸人民币政策 Agent",
            "role": "中间价与离岸流动性",
            "description": "聚焦 PBOC 中间价、稳汇率意图、离岸流动性和政策预期。",
            "focus_points": ["中间价", "离岸流动性", "稳汇率", "政策预期"],
            "theme_keywords": ["离岸人民币", "中间价", "央行", "稳汇率", "CNH", "中国政策"],
        },
        "USDCNY": {
            "label": "人民币政策 Agent",
            "role": "中间价与在岸政策约束",
            "description": "聚焦 PBOC 中间价、稳汇率意图和在岸政策约束。",
            "focus_points": ["中间价", "在岸人民币", "稳汇率", "政策约束"],
            "theme_keywords": ["人民币", "中间价", "央行", "稳汇率", "CNY", "中国政策"],
        },
    }
    return {**profile, **mapping.get(canonical_code, {})}


def _classify_fx_theme_route(
    current_code: str,
    theme_definition: Dict[str, Any],
    product_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pair_profile = _build_fx_pair_specialist_profile(current_code, product_info)
    theme_text_parts = [
        str(theme_definition.get("label") or ""),
        str(theme_definition.get("description") or ""),
    ]
    theme_text_parts.extend([str(item or "") for item in (theme_definition.get("keywords") or []) if str(item or "").strip()])
    theme_text = " ".join(theme_text_parts).lower()
    route = {
        "theme_type": "balanced_monitoring",
        "label": "均衡观察",
        "preferred_agent_ids": ["fx_macro_policy", "fx_macro_surprise", "fx_usd_regime", "fx_positioning", "fx_pair_specialist"],
        "preferred_agent_types": ["macro_policy", "macro_surprise", "usd_regime", "positioning", "pair_specialist"],
    }
    if any(keyword in theme_text for keyword in ["中间价", "干预", "维稳", "离岸", "在岸", "资本流动"]):
        route = {
            "theme_type": "policy_intervention",
            "label": "政策干预",
            "preferred_agent_ids": ["fx_pair_specialist", "fx_positioning", "fx_macro_policy", "fx_usd_regime"],
            "preferred_agent_types": ["pair_specialist", "positioning", "macro_policy", "usd_regime"],
        }
    elif any(keyword in theme_text for keyword in ["讲话", "议息", "纪要", "点阵图", "央行", "降息", "加息", "利率"]):
        route = {
            "theme_type": "policy_path",
            "label": "央行路径",
            "preferred_agent_ids": ["fx_macro_policy", "fx_usd_regime", "fx_positioning", "fx_pair_specialist"],
            "preferred_agent_types": ["macro_policy", "usd_regime", "positioning", "pair_specialist"],
        }
    elif any(keyword in theme_text for keyword in ["非农", "cpi", "通胀", "pmi", "gdp", "零售", "就业", "失业率", "数据"]):
        route = {
            "theme_type": "macro_surprise",
            "label": "数据预期差",
            "preferred_agent_ids": ["fx_macro_surprise", "fx_macro_policy", "fx_usd_regime", "fx_positioning", "fx_pair_specialist"],
            "preferred_agent_types": ["macro_surprise", "macro_policy", "usd_regime", "positioning", "pair_specialist"],
        }
    elif any(keyword in theme_text for keyword in ["战争", "冲突", "制裁", "关税", "特朗普", "袭击", "地缘"]):
        route = {
            "theme_type": "risk_event",
            "label": "风险偏好",
            "preferred_agent_ids": ["fx_risk_sentiment", "fx_cross_asset", "fx_usd_regime", "fx_pair_specialist", "macro_geopolitics"],
            "preferred_agent_types": ["risk_sentiment", "cross_asset", "usd_regime", "pair_specialist", "geopolitics"],
        }
    elif any(keyword in theme_text for keyword in ["中国", "铁矿石", "铜", "原油", "opec", "刺激", "出口", "大宗"]):
        route = {
            "theme_type": "commodity_growth",
            "label": "增长与商品链",
            "preferred_agent_ids": ["fx_pair_specialist", "fx_cross_asset", "fx_risk_sentiment", "fx_macro_policy"],
            "preferred_agent_types": ["pair_specialist", "cross_asset", "risk_sentiment", "macro_policy"],
        }
    elif any(keyword in theme_text for keyword in ["美元", "dxy", "美债", "实际利率", "美元流动性"]):
        route = {
            "theme_type": "usd_regime",
            "label": "美元主线",
            "preferred_agent_ids": ["fx_usd_regime", "fx_macro_policy", "fx_positioning", "fx_pair_specialist"],
            "preferred_agent_types": ["usd_regime", "macro_policy", "positioning", "pair_specialist"],
        }
    route["pair_profile"] = pair_profile
    route["pair_code"] = str(pair_profile.get("pair_code") or current_code or "").strip().upper()
    return route


def _get_market_data_metric_map(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    metric_map: Dict[str, Dict[str, Any]] = {}
    for item in (snapshot or {}).get("structure_metrics", []) or []:
        if not isinstance(item, dict):
            continue
        metric_name = str(item.get("metric_name") or "").strip()
        if metric_name and metric_name not in metric_map:
            metric_map[metric_name] = item
    return metric_map


def _describe_theme_agent_selection(
    agent_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    theme_definition: Dict[str, Any],
) -> str:
    current_market = str(asset_context.get("current_market") or "")
    current_code = str(asset_context.get("current_code") or "")
    product_info = _get_product_info(current_code, current_market) if current_market or current_code else {}
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    agent_type = str(agent_definition.get("agent_type") or "")
    agent_id = str(agent_definition.get("id") or "")
    selection_parts: List[str] = []
    if agent_type in _THEME_AGENT_MANDATORY_TYPES:
        selection_parts.append("系统基础视角")
    if asset_class == "fx":
        fx_route = _classify_fx_theme_route(current_code, theme_definition, product_info)
        if agent_id in set(fx_route.get("preferred_agent_ids") or []) or agent_type in set(fx_route.get("preferred_agent_types") or []):
            selection_parts.append(f"匹配外汇主题路由「{str(fx_route.get('label') or '均衡观察')}」")
        pair_profile = fx_route.get("pair_profile", {}) if isinstance(fx_route, dict) else {}
        if agent_type == "pair_specialist" and pair_profile:
            selection_parts.append(f"针对 {str(pair_profile.get('pair_code') or current_code or '该货币对')} 的专属机制")
    theme_keywords = [str(keyword).strip() for keyword in (agent_definition.get("theme_keywords") or []) if str(keyword).strip()]
    theme_terms = " ".join(
        [
            str(theme_definition.get("label") or ""),
            str(theme_definition.get("description") or ""),
            " ".join([str(item) for item in (theme_definition.get("keywords") or []) if str(item).strip()]),
        ]
    ).lower()
    matched_keywords = [keyword for keyword in theme_keywords if keyword.lower() in theme_terms][:2]
    if matched_keywords:
        selection_parts.append("命中关键词：" + "、".join(matched_keywords))
    if not selection_parts:
        selection_parts.append("作为补充视角纳入当前主题推演")
    return "；".join(selection_parts)


def _get_forex_context_terms(currency_code: str) -> Dict[str, List[str]]:
    context = get_asset_context_terms(currency_code)
    return {
        "aliases": context.get("aliases", [currency_code]),
        "drivers": context.get("drivers", []),
    }


def _build_asset_search_plan(
    query: str,
    product_code: Optional[str],
    market: str,
    product_info: Optional[Dict[str, Any]],
    stock_info: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    normalized_code = _normalize_asset_code(product_code or query)
    base_terms = _build_news_search_terms(
        query=query,
        product_code=normalized_code,
        product_info=product_info,
        stock_info=stock_info,
    )

    plan = {
        "canonical_code": normalized_code,
        "direct_terms": base_terms[:],
        "driver_terms": [],
        "vector_queries": [],
        "db_queries": [],
    }

    if (product_info or {}).get("type") == "forex":
        base_currency = (product_info or {}).get("base_currency", "")
        quote_currency = (product_info or {}).get("quote_currency", "")
        pair_aliases = [
            normalized_code,
            f"{base_currency}{quote_currency}",
            f"{base_currency}/{quote_currency}" if base_currency and quote_currency else "",
            (product_info or {}).get("name_cn", ""),
            (product_info or {}).get("name_en", ""),
            f"{_get_forex_context_terms(base_currency).get('aliases', [''])[1] if len(_get_forex_context_terms(base_currency).get('aliases', [])) > 1 else ''}兑{_get_forex_context_terms(quote_currency).get('aliases', [''])[1] if len(_get_forex_context_terms(quote_currency).get('aliases', [])) > 1 else ''}",
        ]

        if normalized_code in {"USDCNY", "USDCNH"}:
            pair_aliases.extend(
                [
                    "USDCNY",
                    "USD/CNY",
                    "USDCNH",
                    "USD/CNH",
                    "美元兑人民币",
                    "美元兑离岸人民币",
                    "美元兑在岸人民币",
                    "离岸人民币",
                    "在岸人民币",
                    "人民币汇率",
                ]
            )

        base_context = _get_forex_context_terms(base_currency)
        quote_context = _get_forex_context_terms(quote_currency)
        driver_terms = (
            base_context.get("aliases", [])
            + quote_context.get("aliases", [])
            + base_context.get("drivers", [])
            + quote_context.get("drivers", [])
            + (product_info or {}).get("driver_keywords", [])
        )

        plan["direct_terms"] = _deduplicate_terms(pair_aliases + base_terms)
        plan["driver_terms"] = _deduplicate_terms(driver_terms)
        direct_query = " ".join(plan["direct_terms"][:8])
        macro_query = " ".join(_deduplicate_terms(plan["direct_terms"][:4] + plan["driver_terms"][:8]))

        plan["vector_queries"] = [
            {
                "stage": "direct",
                "query": direct_query,
                "keywords": plan["direct_terms"][:10],
                "bonus": 18.0,
                "n_results": 24,
            },
            {
                "stage": "driver",
                "query": macro_query,
                "keywords": _deduplicate_terms(plan["direct_terms"][:4] + plan["driver_terms"][:10]),
                "bonus": 8.0,
                "n_results": 18,
            },
        ]
        plan["db_queries"] = [
            {
                "stage": "direct_db",
                "query_text": direct_query,
                "keywords": plan["direct_terms"][:10],
                "bonus": 16.0,
            },
            {
                "stage": "driver_db",
                "query_text": macro_query,
                "keywords": _deduplicate_terms(plan["direct_terms"][:4] + plan["driver_terms"][:10]),
                "bonus": 6.0,
            },
        ]
        return plan

    plan["direct_terms"] = base_terms
    default_query = " ".join(base_terms[:6]) if base_terms else query
    plan["vector_queries"] = [
        {
            "stage": "default",
            "query": default_query,
            "keywords": base_terms[:12],
            "bonus": 10.0,
            "n_results": 24,
        }
    ]
    plan["db_queries"] = [
        {
            "stage": "default_db",
            "query_text": query,
            "keywords": base_terms[:12],
            "bonus": 8.0,
        }
    ]
    return plan


def _merge_search_batches(search_batches: List[Dict[str, Any]], n_results: int) -> List[Dict[str, Any]]:
    aggregated: Dict[str, Dict[str, Any]] = {}

    for batch in search_batches:
        stage = batch.get("stage", "default")
        bonus = float(batch.get("bonus", 0.0))
        for index, result in enumerate(batch.get("results", [])):
            metadata = result.get("metadata", {})
            news_id = metadata.get("news_id") or result.get("id")
            if not news_id:
                continue

            base_score = float(result.get("score", 0.0))
            ranked_score = base_score + bonus + max(0.0, 12.0 - float(index))
            if news_id not in aggregated:
                aggregated[news_id] = {
                    **result,
                    "score": ranked_score,
                    "search_stages": [stage],
                }
                continue

            aggregated[news_id]["score"] = max(aggregated[news_id]["score"], ranked_score)
            aggregated[news_id]["search_stages"] = _deduplicate_terms(
                aggregated[news_id].get("search_stages", []) + [stage]
            )

    merged_results = list(aggregated.values())
    merged_results.sort(
        key=lambda item: (
            item.get("score", 0.0),
            item.get("metadata", {}).get("published_at", ""),
        ),
        reverse=True,
    )
    return merged_results[:n_results]


def _format_db_news_item(news, score: float = 0.0) -> Dict[str, Any]:
    published_at = news.published_at.isoformat() if news.published_at else ""
    asset_links = infer_news_asset_links(
        title=news.title or "",
        body=news.body or "",
    )
    return {
        "id": news.news_id or str(news.id),
        "document": news.body or news.title or "",
        "metadata": {
            "news_id": news.news_id or str(news.id),
            "title": news.title or "",
            "source": news.source or "",
            "published_at": published_at,
            "category": news.category or "",
            "sentiment_score": float(news.sentiment_score or 0.0),
            "importance_score": float(news.importance_score or 0.0),
            "language": news.language or "zh",
            "story_id": news.story_id or "",
            "tags": news.tags or "",
            "direct_assets": asset_links.get("direct_assets", []),
            "driver_assets": asset_links.get("driver_assets", []),
            "matched_terms": asset_links.get("matched_terms", []),
        },
        "score": float(score),
        "distance": max(0.0, 1.0 - min(float(score) / 100.0, 1.0)),
    }


def _score_db_news(news, search_terms: List[str]) -> float:
    text = " ".join(
        [
            news.title or "",
            news.body or "",
            news.tags or "",
            news.source or "",
        ]
    ).lower()
    asset_links = infer_news_asset_links(
        title=news.title or "",
        body=news.body or "",
    )
    direct_assets = {
        _normalize_asset_code(asset) for asset in asset_links.get("direct_assets", [])
    }
    driver_assets = {
        _normalize_asset_code(asset) for asset in asset_links.get("driver_assets", [])
    }

    score = 0.0
    for term in search_terms:
        term_lower = term.lower()
        if not term_lower:
            continue
        normalized_term = _normalize_asset_code(term)
        if normalized_term and normalized_term in direct_assets:
            score += 35.0
        elif normalized_term and normalized_term in driver_assets:
            score += 14.0
        if term_lower in (news.title or "").lower():
            score += 20.0
        elif term_lower in text:
            score += 8.0

    score += float(news.importance_score or 0.0) * 10.0

    if news.published_at:
        age_days = max(
            0.0,
            (datetime.now() - news.published_at).total_seconds() / 86400.0,
        )
        score += max(0.0, 10.0 - min(age_days, 10.0))

    return round(score, 4)


def _search_news_from_relational_db(
    query: str,
    search_terms: List[str],
    start_date: datetime,
    end_date: datetime,
    n_results: int,
) -> List[Dict[str, Any]]:
    db_rows = db.news_search(
        query_text=query,
        keywords=search_terms,
        limit=max(n_results * 4, 40),
        start_date=start_date,
        end_date=end_date,
    )

    ranked_results = []
    for news in db_rows:
        score = _score_db_news(news, search_terms)
        ranked_results.append(_format_db_news_item(news, score))

    ranked_results.sort(
        key=lambda item: (
            item.get("score", 0.0),
            item.get("metadata", {}).get("published_at", ""),
        ),
        reverse=True,
    )
    return ranked_results[:n_results]


def _warmup_vector_db(vector_db, news_results: List[Dict[str, Any]]) -> int:
    if vector_db is None or not getattr(vector_db, "is_ready", lambda: False)():
        return 0

    inserted_count = 0
    for news in news_results[: min(len(news_results), 10)]:
        metadata = news.get("metadata", {})
        if vector_db.add_news(
            {
                "news_id": metadata.get("news_id") or news.get("id"),
                "story_id": metadata.get("story_id"),
                "title": metadata.get("title"),
                "body": news.get("document") or metadata.get("title"),
                "source": metadata.get("source"),
                "published_at": metadata.get("published_at"),
                "language": metadata.get("language", "zh"),
                "category": metadata.get("category"),
                "tags": metadata.get("tags"),
                "sentiment_score": metadata.get("sentiment_score", 0.0),
                "importance_score": metadata.get("importance_score", 0.0),
            }
        ):
            inserted_count += 1

    return inserted_count


def _get_vector_news_impl(
    code: str,
    market: str,
    days: int = 7,
    n_results: int = 50,
    query: Optional[str] = None,
    product_info: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    logger.info(f"开始为 {market}-{code} 检索新闻（混合检索版本）...")

    try:
        normalized_code = _normalize_asset_code(code)
        ex = get_exchange(Market(market))
        stock_info = ex.stock_info(code) or {}
        if not stock_info and not query:
            logger.error(f"无法获取资产信息: {code}")
            return []

        search_query = query or stock_info.get("name") or stock_info.get("code") or code
        if product_info is None:
            product_info = _get_product_info((normalized_code or query or "").strip().upper())

        search_plan = _build_asset_search_plan(
            query=search_query,
            product_code=normalized_code,
            market=market,
            product_info=product_info,
            stock_info=stock_info,
        )
        search_terms = _deduplicate_terms(
            search_plan.get("direct_terms", []) + search_plan.get("driver_terms", [])
        )[:16]

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        vector_db = get_vector_db()
        vector_ready = getattr(vector_db, "is_ready", lambda: False)()
        # logger.info(
        #     f"新闻搜索参数 code={normalized_code} direct_terms={search_plan.get('direct_terms', [])[:8]} "
        #     f"driver_terms={search_plan.get('driver_terms', [])[:8]} "
        #     f"vector_ready={vector_ready}"
        # )

        search_batches = []
        if vector_ready:
            for vector_query in search_plan.get("vector_queries", []):
                query_text = vector_query.get("query", "").strip()
                if not query_text:
                    continue
                query_results = vector_db.semantic_search(
                    query=query_text,
                    n_results=min(max(vector_query.get("n_results", n_results * 2), 12), 80),
                    keywords=vector_query.get("keywords", []),
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                )
                if query_results:
                    search_batches.append(
                        {
                            "stage": vector_query.get("stage"),
                            "bonus": vector_query.get("bonus", 0.0),
                            "results": query_results,
                        }
                    )

        db_results = []
        for db_query in search_plan.get("db_queries", []):
            query_text = db_query.get("query_text", "").strip()
            if not query_text:
                continue
            query_results = _search_news_from_relational_db(
                query=query_text,
                search_terms=db_query.get("keywords", search_terms),
                start_date=start_date,
                end_date=end_date,
                n_results=max(n_results, 20),
            )
            if query_results:
                db_results.extend(query_results)
                search_batches.append(
                    {
                        "stage": db_query.get("stage"),
                        "bonus": db_query.get("bonus", 0.0),
                        "results": query_results,
                    }
                )

        final_results = _merge_search_batches(search_batches, n_results)
        if vector_ready and final_results:
            existing_vector_hits = sum(
                len(batch.get("results", []))
                for batch in search_batches
                if str(batch.get("stage", "")).startswith(("direct", "driver"))
                and not str(batch.get("stage", "")).endswith("_db")
            )
            if existing_vector_hits < max(3, n_results // 2):
                warmed_count = _warmup_vector_db(vector_db, final_results)
                logger.info(f"关系库/混合结果已回灌向量库 {warmed_count} 条")

        logger.info(
            f"为 {code} 检索到 {len(final_results)} 条相关新闻 "
            f"(batches={len(search_batches)}, db={len(db_results)})"
        )
        return final_results

    except Exception as e:
        logger.error(f"检索新闻时出错: {e}", exc_info=True)
        return []


def get_vector_news(
    code: str,
    market: str,
    days: int = 7,
    n_results: int = 50,
    query: Optional[str] = None,
    product_info: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    return _get_vector_news_impl(
        code=code,
        market=market,
        days=days,
        n_results=n_results,
        query=query,
        product_info=product_info,
    )


def _bucket_news_evidence(
    news_list: List[Dict[str, Any]],
    canonical_asset: str,
) -> Dict[str, List[Dict[str, Any]]]:
    normalized_asset = _normalize_asset_code(canonical_asset)
    buckets = {
        "direct": [],
        "driver": [],
        "background": [],
    }

    for news in news_list:
        news = dict(news)
        metadata = news.get("metadata", {})
        direct_assets = {
            _normalize_asset_code(asset)
            for asset in metadata.get("direct_assets", []) or []
        }
        driver_assets = {
            _normalize_asset_code(asset)
            for asset in metadata.get("driver_assets", []) or []
        }
        direction_info = infer_asset_impact_direction(
            title=metadata.get("title", ""),
            body=news.get("document", ""),
            canonical_asset=normalized_asset,
        )
        news["impact_direction"] = direction_info.get("impact_direction", "neutral")
        news["direction_score"] = direction_info.get("direction_score", 0.0)
        news["direction_reason"] = direction_info.get("reason", "")

        if normalized_asset and normalized_asset in direct_assets:
            buckets["direct"].append(news)
        elif normalized_asset and normalized_asset in driver_assets:
            buckets["driver"].append(news)
        else:
            buckets["background"].append(news)

    return buckets


def _guess_market_from_product_info(product_info: Dict[str, Any]) -> str:
    asset_type = (product_info or {}).get("type", "")
    if asset_type == "forex":
        return "fx"
    if asset_type in {"futures", "commodity", "precious_metal", "股指期货"}:
        return "futures"
    return "a"


def _build_asset_news_response(
    asset_code: str,
    market: str,
    days: int = 7,
    limit: int = 20,
) -> Dict[str, Any]:
    canonical_asset = _normalize_asset_code(asset_code)
    product_info = _get_product_info(canonical_asset)
    effective_market = market or _guess_market_from_product_info(product_info)

    direct_links = db.news_asset_links_query(
        canonical_asset=canonical_asset,
        relation_type="direct",
        limit=max(limit * 2, 20),
    )
    driver_links = db.news_asset_links_query(
        canonical_asset=canonical_asset,
        relation_type="driver",
        limit=max(limit * 2, 20),
    )

    def _rows_to_news(rows: List[Any], bucket_name: str) -> List[Dict[str, Any]]:
        bucket_news = []
        for row in rows:
            news_row = db.news_get_by_id(row.news_id)
            if not news_row:
                continue
            news_item = _format_db_news_item(news_row, float(row.confidence or 0.0) * 100.0)
            direction_info = infer_asset_impact_direction(
                title=news_row.title or "",
                body=news_row.body or "",
                canonical_asset=canonical_asset,
            )
            news_item["relation_type"] = bucket_name
            news_item["relation_reason"] = row.reason or ""
            news_item["relation_confidence"] = float(row.confidence or 0.0)
            news_item["matched_terms"] = (row.matched_terms or "").split(",") if row.matched_terms else []
            news_item["impact_direction"] = direction_info.get("impact_direction", "neutral")
            news_item["direction_score"] = direction_info.get("direction_score", 0.0)
            news_item["direction_reason"] = direction_info.get("reason", "")
            bucket_news.append(news_item)
        return bucket_news[:limit]

    direct_news = _rows_to_news(direct_links, "direct")
    driver_news = _rows_to_news(driver_links, "driver")
    linked_ids = {
        item.get("metadata", {}).get("news_id")
        for item in direct_news + driver_news
    }

    search_plan = _build_asset_search_plan(
        query=canonical_asset,
        product_code=canonical_asset,
        market=effective_market,
        product_info=product_info,
        stock_info={},
    )
    background_search_terms = _deduplicate_terms(
        search_plan.get("direct_terms", []) + search_plan.get("driver_terms", [])
    )[:16]
    candidate_background = _search_news_from_relational_db(
        query=canonical_asset,
        search_terms=background_search_terms,
        start_date=datetime.now() - timedelta(days=days),
        end_date=datetime.now(),
        n_results=max(limit * 3, 24),
    )
    background_news = [
        news for news in candidate_background
        if news.get("metadata", {}).get("news_id") not in linked_ids
    ][:limit]

    return {
        "asset_code": asset_code,
        "canonical_asset": canonical_asset,
        "market": effective_market,
        "product_info": product_info,
        "buckets": {
            "direct": direct_news,
            "driver": driver_news,
            "background": background_news,
        },
        "counts": {
            "direct": len(direct_news),
            "driver": len(driver_news),
            "background": len(background_news),
        },
    }


def _merge_news_items(*news_groups: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for group in news_groups:
        for item in group or []:
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            news_id = metadata.get("news_id") or item.get("id") or item.get("news_id")
            if news_id and news_id in seen_ids:
                continue
            if news_id:
                seen_ids.add(news_id)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def _build_theme_related_news_response(
    theme_definition: Dict[str, Any],
    asset_code: str,
    market: str,
    lookback_hours: int,
    limit: int,
    product_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    asset_news = _build_asset_news_response(
        asset_code=asset_code,
        market=market,
        days=max(1, int((lookback_hours + 23) / 24)),
        limit=max(limit, 8),
    )
    search_plan = _build_asset_search_plan(
        query=theme_definition.get("label", "") or asset_code,
        product_code=asset_code,
        market=market,
        product_info=product_info or {},
        stock_info={},
    )
    search_terms = _deduplicate_terms(
        (theme_definition.get("keywords", []) or [])
        + [theme_definition.get("label", "")]
        + search_plan.get("direct_terms", [])[:6]
        + search_plan.get("driver_terms", [])[:8]
    )[:20]
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=lookback_hours)
    searched_news = _search_news_from_relational_db(
        query=theme_definition.get("label", "") or asset_code,
        search_terms=search_terms,
        start_date=start_date,
        end_date=end_date,
        n_results=max(limit * 3, 24),
    )
    search_buckets = _bucket_news_evidence(searched_news, asset_code)
    merged_direct = _merge_news_items(
        asset_news.get("buckets", {}).get("direct", []),
        search_buckets.get("direct", []),
        limit=max(limit * 2, 12),
    )
    merged_driver = _merge_news_items(
        asset_news.get("buckets", {}).get("driver", []),
        search_buckets.get("driver", []),
        limit=max(limit * 2, 12),
    )
    merged_background = _merge_news_items(
        asset_news.get("buckets", {}).get("background", []),
        search_buckets.get("background", []),
        limit=max(limit * 2, 12),
    )
    return {
        "theme_search_terms": search_terms,
        "searched_news": searched_news,
        "searched_news_count": len(searched_news),
        "buckets": {
            "direct": merged_direct,
            "driver": merged_driver,
            "background": merged_background,
        },
    }


def _merge_theme_bucket_sequences(
    primary_items: List[Dict[str, Any]],
    secondary_items: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    return _merge_news_items(primary_items, secondary_items, limit=limit)


def _normalize_uploaded_evidence_items(values: Any) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in values[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("file_name") or "").strip()
        summary = str(item.get("summary") or item.get("excerpt") or "").strip()
        content = str(item.get("content") or "").strip()
        if not title or not (summary or content):
            continue
        normalized.append(
            {
                "evidence_id": str(item.get("evidence_id") or uuid.uuid4().hex[:12]).strip(),
                "title": title,
                "summary": summary[:800] or content[:800],
                "content": content[:6000] or summary[:6000],
                "published_at": str(item.get("published_at") or item.get("uploaded_at") or "").strip(),
                "importance_score": float(item.get("importance_score", 0.8) or 0.8),
                "impact_direction": str(item.get("impact_direction") or "neutral").strip() or "neutral",
                "direction_reason": str(item.get("direction_reason") or "来自用户上传材料，作为补充证据参与推演。").strip(),
                "file_name": str(item.get("file_name") or title).strip(),
                "file_type": str(item.get("file_type") or "").strip(),
                "source_label": str(item.get("source_label") or "用户上传材料").strip(),
                "document": content[:6000] or summary[:6000],
            }
        )
    return normalized


def _decode_uploaded_text(file_bytes: bytes) -> str:
    if not file_bytes:
        return ""
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb18030", "big5"]
    for encoding in encodings:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        import chardet

        detected = chardet.detect(file_bytes)
        detected_encoding = str((detected or {}).get("encoding") or "").strip()
        if detected_encoding:
            return file_bytes.decode(detected_encoding, errors="ignore")
    except Exception:
        pass
    return file_bytes.decode("utf-8", errors="ignore")


def _normalize_extracted_text(value: Any, max_chars: int = 6000) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def _extract_pdf_text(file_bytes: bytes) -> str:
    reader_cls = None
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name, fromlist=["PdfReader"])
            reader_cls = getattr(module, "PdfReader", None)
            if reader_cls:
                break
        except Exception:
            continue
    if reader_cls is None:
        raise ValueError("当前环境缺少 PDF 解析依赖，请安装 pypdf 或 PyPDF2")
    reader = reader_cls(io.BytesIO(file_bytes))
    chunks: List[str] = []
    for page in list(getattr(reader, "pages", []))[:20]:
        page_text = ""
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_text = _normalize_extracted_text(page_text, max_chars=1600)
        if page_text:
            chunks.append(page_text)
        if len("\n".join(chunks)) >= 8000:
            break
    return _normalize_extracted_text("\n\n".join(chunks), max_chars=7000)


def _extract_docx_text(file_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    texts = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    return _normalize_extracted_text("\n".join(texts), max_chars=7000)


def _extract_excel_text(file_bytes: bytes, file_name: str) -> str:
    import pandas as pd

    excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
    sheet_chunks: List[str] = []
    for sheet_name in excel_file.sheet_names[:3]:
        df = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=12)
        df = df.fillna("")
        preview_rows = []
        for _, row in df.head(8).iterrows():
            row_values = [str(value).strip() for value in row.tolist() if str(value).strip()]
            if row_values:
                preview_rows.append(" | ".join(row_values))
        sheet_chunks.append(f"工作表 {sheet_name}：\n" + "\n".join(preview_rows[:8]))
    return _normalize_extracted_text("\n\n".join(sheet_chunks) or file_name, max_chars=7000)


def _extract_uploaded_file_text(file_name: str, file_bytes: bytes) -> Dict[str, Any]:
    suffix = os.path.splitext(file_name or "")[1].lower()
    if suffix in (".md", ".markdown", ".txt", ".csv", ".json"):
        text = _decode_uploaded_text(file_bytes)
        source_label = "文本材料"
    elif suffix == ".pdf":
        text = _extract_pdf_text(file_bytes)
        source_label = "PDF材料"
    elif suffix == ".docx":
        text = _extract_docx_text(file_bytes)
        source_label = "Word材料"
    elif suffix in (".xls", ".xlsx"):
        text = _extract_excel_text(file_bytes, file_name)
        source_label = "Excel材料"
    elif suffix == ".doc":
        raise ValueError("当前仅支持 .docx Word 文件，请先转换为 .docx 后上传")
    else:
        raise ValueError(f"暂不支持该文件类型：{suffix or 'unknown'}")
    normalized_text = _normalize_extracted_text(text, max_chars=7000)
    if not normalized_text:
        raise ValueError("文件已上传，但未提取到可用文本内容")
    summary_lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    summary = "；".join(summary_lines[:3])[:500] or normalized_text[:500]
    return {
        "evidence_id": uuid.uuid4().hex[:12],
        "title": os.path.basename(file_name or "用户材料"),
        "file_name": os.path.basename(file_name or "用户材料"),
        "file_type": suffix.lstrip("."),
        "source_label": source_label,
        "summary": summary,
        "excerpt": normalized_text[:800],
        "content": normalized_text,
        "published_at": datetime.now().isoformat(),
        "uploaded_at": datetime.now().isoformat(),
        "importance_score": 0.82,
        "impact_direction": "neutral",
        "direction_reason": "来自用户上传材料，作为额外研究证据补充到主题推演。",
    }


def _run_theme_research_round(
    theme_definition: Dict[str, Any],
    asset_code: str,
    lookback_hours: int,
    round_plan: Dict[str, Any],
    max_news: int,
) -> Dict[str, Any]:
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=lookback_hours)
    search_terms = list(round_plan.get("search_terms") or [])[:16]
    searched_news = _search_news_from_relational_db(
        query=str(round_plan.get("query_text") or theme_definition.get("label") or asset_code),
        search_terms=search_terms,
        start_date=start_date,
        end_date=end_date,
        n_results=max(max_news * 3, 24),
    )
    buckets = _bucket_news_evidence(searched_news, asset_code)
    new_titles = [
        str(item.get("metadata", {}).get("title") or item.get("title") or "").strip()
        for item in searched_news[:4]
        if str(item.get("metadata", {}).get("title") or item.get("title") or "").strip()
    ]
    return {
        "round_id": int(round_plan.get("round_id", 0) or 0),
        "focus": str(round_plan.get("focus") or ""),
        "objective": str(round_plan.get("objective") or ""),
        "query_text": str(round_plan.get("query_text") or ""),
        "search_terms": search_terms,
        "searched_news": searched_news,
        "searched_news_count": len(searched_news),
        "buckets": buckets,
        "new_headlines": new_titles,
    }


def _build_theme_research_agent_payload(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    asset_code: str,
    lookback_hours: int,
    max_news: int,
    cross_asset_watch: Dict[str, Any],
    base_buckets: Dict[str, List[Dict[str, Any]]],
    uploaded_evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    working_buckets = {
        "direct": list(base_buckets.get("direct", []) or []),
        "driver": list(base_buckets.get("driver", []) or []),
        "background": list(base_buckets.get("background", []) or []),
    }
    working_toolkit = build_theme_toolkit_payload(
        theme_definition=theme_definition,
        asset_context=asset_context,
        direct_news=working_buckets["direct"],
        driver_news=working_buckets["driver"],
        background_news=working_buckets["background"],
        cross_asset_watch=cross_asset_watch,
        uploaded_evidence=uploaded_evidence or [],
        max_news=max_news,
    )
    completed_focuses: List[str] = []
    round_results: List[Dict[str, Any]] = []
    total_supplemental_hits = 0
    for _ in range(2):
        round_plans = build_theme_research_rounds(
            theme_definition=theme_definition,
            asset_context=asset_context,
            toolkit_payload=working_toolkit,
            completed_focuses=completed_focuses,
            max_rounds=1,
        )
        if not round_plans:
            break
        round_plan = round_plans[0]
        completed_focuses.append(str(round_plan.get("focus") or ""))
        before_total_news = int((working_toolkit.get("evidence_matrix", {}) or {}).get("total_news", 0) or 0)
        round_payload = _run_theme_research_round(
            theme_definition=theme_definition,
            asset_code=asset_code,
            lookback_hours=lookback_hours,
            round_plan=round_plan,
            max_news=max_news,
        )
        total_supplemental_hits += int(round_payload.get("searched_news_count", 0) or 0)
        working_buckets["direct"] = _merge_theme_bucket_sequences(
            working_buckets["direct"],
            round_payload.get("buckets", {}).get("direct", []),
            limit=max_news * 4,
        )
        working_buckets["driver"] = _merge_theme_bucket_sequences(
            working_buckets["driver"],
            round_payload.get("buckets", {}).get("driver", []),
            limit=max_news * 4,
        )
        working_buckets["background"] = _merge_theme_bucket_sequences(
            working_buckets["background"],
            round_payload.get("buckets", {}).get("background", []),
            limit=max_news * 4,
        )
        working_toolkit = build_theme_toolkit_payload(
            theme_definition=theme_definition,
            asset_context=asset_context,
            direct_news=working_buckets["direct"],
            driver_news=working_buckets["driver"],
            background_news=working_buckets["background"],
            cross_asset_watch=cross_asset_watch,
            uploaded_evidence=uploaded_evidence or [],
            max_news=max_news,
        )
        after_total_news = int((working_toolkit.get("evidence_matrix", {}) or {}).get("total_news", 0) or 0)
        round_results.append(
            {
                "round_id": int(round_plan.get("round_id", len(round_results) + 1) or len(round_results) + 1),
                "focus": str(round_plan.get("focus") or ""),
                "objective": str(round_plan.get("objective") or ""),
                "query_text": str(round_plan.get("query_text") or ""),
                "search_terms": list(round_plan.get("search_terms") or [])[:10],
                "searched_news_count": int(round_payload.get("searched_news_count", 0) or 0),
                "new_headlines": list(round_payload.get("new_headlines") or [])[:4],
                "status": "completed" if round_payload.get("searched_news_count", 0) else "no_new_evidence",
                "evidence_gain": {
                    "before": before_total_news,
                    "after": after_total_news,
                    "delta": max(0, after_total_news - before_total_news),
                },
            }
        )
    working_toolkit["planner_source"] = "evidence_gap_heuristic"
    working_toolkit["agent_rounds"] = round_results
    working_toolkit["rounds_completed"] = len(round_results)
    working_toolkit["supplemental_news_count"] = total_supplemental_hits
    working_toolkit["research_digest"] = (
        f"{working_toolkit.get('research_digest', '')}"
        f" 已完成 {len(round_results)} 轮补证据检索，新增检索命中 {total_supplemental_hits} 条。"
    ).strip()
    return working_toolkit


def _resolve_agent_stance_label(direction: str) -> str:
    normalized = str(direction or "").strip().lower()
    if normalized in {"bullish", "long", "up"}:
        return "偏多"
    if normalized in {"bearish", "short", "down"}:
        return "偏空"
    return "中性"


def _build_theme_agent_output(
    agent_definition: Dict[str, Any],
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    toolkit_payload: Dict[str, Any],
    temporal_evidence: Dict[str, Any],
    market_data_snapshot: Dict[str, Any],
    market_data_digest: Dict[str, Any],
    cross_asset_watch: Dict[str, Any],
) -> Dict[str, Any]:
    agent_type = str(agent_definition.get("agent_type") or "custom")
    product_info = _get_product_info(str(asset_context.get("current_code") or ""), str(asset_context.get("current_market") or ""))
    asset_class = _resolve_market_data_asset_class(str(asset_context.get("current_market") or ""), product_info)
    fx_route = _classify_fx_theme_route(str(asset_context.get("current_code") or ""), theme_definition, product_info) if asset_class == "fx" else {}
    fx_pair_profile = fx_route.get("pair_profile", {}) if isinstance(fx_route, dict) else {}
    fx_metric_map = _get_market_data_metric_map(market_data_snapshot) if asset_class == "fx" else {}
    policy_rate_diff = _safe_float((fx_metric_map.get("policy_rate_differential") or {}).get("metric_value"), 0.0) if fx_metric_map else 0.0
    policy_surprise_diff = _safe_float((fx_metric_map.get("policy_surprise_differential") or {}).get("metric_value"), 0.0) if fx_metric_map else 0.0
    usd_pressure = _safe_float((fx_metric_map.get("usd_counter_currency_pressure") or {}).get("metric_value"), 0.0) if fx_metric_map else 0.0
    cftc_bias = _safe_float((fx_metric_map.get("cftc_positioning_bias") or {}).get("metric_value"), 0.0) if fx_metric_map else 0.0
    evidence_matrix = toolkit_payload.get("evidence_matrix", {}) or {}
    bucket_counts = evidence_matrix.get("bucket_counts", {}) or {}
    dominant_direction = str(evidence_matrix.get("dominant_direction") or asset_context.get("price_direction") or "neutral").lower()
    stance = dominant_direction
    confidence = 0.48
    findings: List[str] = []
    theme_news = toolkit_payload.get("theme_news", []) or []
    direct_news = toolkit_payload.get("direct_theme_news", []) or []
    actor_profiles = toolkit_payload.get("actor_profiles", []) or []
    cross_asset_signals = toolkit_payload.get("cross_asset_signals", []) or []
    summary = ""

    if agent_type == "evidence":
        confidence = min(0.92, 0.48 + min(len(theme_news), 8) * 0.04)
        summary = f"直达 {len(direct_news)} 条、驱动 {int(bucket_counts.get('driver', 0) or 0)} 条、背景 {int(bucket_counts.get('background', 0) or 0)} 条，主题证据主方向为{_resolve_agent_stance_label(dominant_direction)}。"
        findings = [
            f"最新主题新闻 {len(theme_news)} 条，说明主题{'仍在发酵' if len(theme_news) >= 3 else '仍需继续补证据'}。",
            f"核心催化来自 {str((theme_news[0] or {}).get('title') or (theme_definition.get('label') or '当前主题')) if theme_news else str(theme_definition.get('label') or '当前主题')}。",
        ]
    elif agent_type == "temporal":
        alignment_rate = _safe_float(temporal_evidence.get("alignment_rate"), 0.0)
        reaction_count = int(temporal_evidence.get("reaction_count", 0) or 0)
        avg_follow = _safe_float(temporal_evidence.get("avg_follow_30m_pct"), 0.0)
        avg_follow_120m = _safe_float(temporal_evidence.get("avg_follow_120m_pct"), 0.0)
        avg_dominant_move = _safe_float(temporal_evidence.get("avg_dominant_move_pct"), 0.0)
        confidence = min(0.92, 0.35 + reaction_count * 0.06 + alignment_rate * 0.25)
        if reaction_count and alignment_rate >= 0.55:
            stance = dominant_direction if dominant_direction in {"bullish", "bearish"} else asset_context.get("price_direction", "neutral")
        elif reaction_count and alignment_rate < 0.4:
            stance = "neutral"
        summary = f"时间性验证样本 {reaction_count} 条，方向一致率 {alignment_rate * 100:.0f}%，30分钟均值 {avg_follow:+.3f}% ，2小时均值 {avg_follow_120m:+.3f}% 。"
        findings = [
            str(temporal_evidence.get("summary") or "当前时间性验证样本不足，需要结合实时价格继续确认。"),
            f"新闻后主导波动均值 {avg_dominant_move:.3f}%。",
            f"最新证据新鲜度：{str(temporal_evidence.get('freshness_label') or '待确认')}。",
        ]
    elif agent_type == "macro_policy" and asset_class == "fx":
        confidence = min(0.93, 0.5 + min(len(fx_metric_map), 4) * 0.08)
        if policy_rate_diff > 0.05:
            stance = "bullish"
        elif policy_rate_diff < -0.05:
            stance = "bearish"
        summary = (
            f"外汇主轴优先看相对利差，当前 {asset_context.get('asset_name') or asset_context.get('current_code') or '该货币对'} 的政策利差差值 "
            f"{policy_rate_diff:+.2f}，主题路由为 {str(fx_route.get('label') or '均衡观察')}。"
        )
        findings = [
            f"主货币对：{str(fx_pair_profile.get('pair_code') or asset_context.get('current_code') or '')}，重点观察 {str(fx_pair_profile.get('role') or '相对利差')}。",
            f"政策 surprise 差值 {policy_surprise_diff:+.2f}，说明主题更像 {'持续路径重估' if abs(policy_surprise_diff) >= 0.1 else '短期催化'}。",
            "外汇最关键的是比较 base/quote 两边央行路径，而不是单看一条新闻。",
        ]
    elif agent_type == "macro_surprise":
        confidence = min(0.91, 0.48 + min(len(theme_news), 5) * 0.05 + (0.06 if fx_metric_map else 0.0))
        if policy_surprise_diff > 0.05:
            stance = "bullish"
        elif policy_surprise_diff < -0.05:
            stance = "bearish"
        summary = f"宏观预期差 Agent 将当前主题归类为 {str(fx_route.get('label') or '数据预期差')}，重点判断数据是否真正改变了 {asset_context.get('asset_name') or asset_context.get('current_code') or '货币对'} 的相对定价。"
        findings = [
            f"政策 surprise 差值 {policy_surprise_diff:+.2f}，优先判断是否从“事件”升级成“路径重估”。",
            str((theme_news[0] or {}).get("reaction_summary") or "需要结合新闻后的 30m / 2h / 6h 价格反应确认数据是否被持续定价。") if theme_news else "需要结合新闻后的 30m / 2h / 6h 价格反应确认数据是否被持续定价。",
            f"该类主题最容易影响 {str(fx_pair_profile.get('role') or '相对利差')}。",
        ]
    elif agent_type == "usd_regime":
        confidence = min(0.9, 0.46 + min(len(cross_asset_signals), 4) * 0.08 + (0.06 if fx_metric_map else 0.0))
        if "USD" == str(asset_context.get("base_currency") or "").upper():
            if usd_pressure > 0.05:
                stance = "bullish"
            elif usd_pressure < -0.05:
                stance = "bearish"
        elif "USD" == str(asset_context.get("quote_currency") or "").upper():
            if usd_pressure > 0.05:
                stance = "bearish"
            elif usd_pressure < -0.05:
                stance = "bullish"
        summary = f"美元主线 Agent 判断该主题需要放到美元系统框架下解释，美元压力值 {usd_pressure:+.2f}。"
        findings = [
            f"跨资产摘要：{str(cross_asset_watch.get('summary') or '当前跨资产尚未形成足够强的美元共振。')}",
            f"若美元是{'基准货币' if str(asset_context.get('base_currency') or '').upper() == 'USD' else '计价货币'}，同样的美元走强会对货币对方向产生不同影响。",
            "美元主线不清晰时，很多外汇主题只会形成短波动而非趋势。",
        ]
    elif agent_type == "positioning" and asset_class == "fx":
        confidence = min(0.88, 0.42 + (0.1 if abs(cftc_bias) >= 0.25 else 0.04) + min(len(theme_news), 3) * 0.05)
        summary = f"持仓拥挤度当前参考值 {cftc_bias:+.2f}，用于判断 {asset_context.get('asset_name') or asset_context.get('current_code') or '货币对'} 是否已经过度 price in。"
        findings = [
            f"CFTC / 持仓偏向 {cftc_bias:+.2f}，说明{'交易可能较拥挤' if abs(cftc_bias) >= 0.25 else '仓位尚未极端'}。",
            "外汇主题若证据正确但仓位过度拥挤，更适合等回撤或二次确认。",
            str((theme_news[0] or {}).get("reaction_summary") or "需结合价格延续判断这轮主题是否还存在挤仓空间。") if theme_news else "需结合价格延续判断这轮主题是否还存在挤仓空间。",
        ]
    elif agent_type == "risk_sentiment":
        confidence = min(0.88, 0.42 + min(len(cross_asset_signals), 4) * 0.1)
        summary = f"风险偏好 Agent 认为当前主题更像 {str(fx_route.get('label') or '风险偏好')} 交易，重点看避险流是否改变了 {asset_context.get('asset_name') or asset_context.get('current_code') or '货币对'} 的相对强弱。"
        findings = [
            str((cross_asset_signals[0] or {}).get("alignment_label") or "暂未观察到足够强的避险或风险偏好共振。") if cross_asset_signals else "暂未观察到足够强的避险或风险偏好共振。",
            f"{str(fx_pair_profile.get('pair_code') or asset_context.get('current_code') or '')} 需要结合 {str(fx_pair_profile.get('role') or '专属机制')} 一起解释。",
            "风险偏好类主题若只有 headline，没有跨资产共振，通常难形成持续趋势。",
        ]
    elif agent_type == "pair_specialist":
        confidence = min(0.92, 0.5 + min(len(theme_news), 4) * 0.05 + (0.08 if fx_metric_map else 0.0))
        summary = f"{str(fx_pair_profile.get('label') or '货币对专属 Agent')} 认为当前主题应回到 {str(fx_pair_profile.get('pair_code') or asset_context.get('current_code') or '该货币对')} 的专属结构下理解。"
        findings = [
            f"核心框架：{str(fx_pair_profile.get('role') or '货币对结构与特殊机制')}。",
            "关注点：" + "、".join([str(item) for item in list(fx_pair_profile.get("focus_points") or [])[:4]]) if fx_pair_profile.get("focus_points") else "需要结合货币对专属机制继续补证据。",
            f"当前主题归类为 {str(fx_route.get('label') or '均衡观察')}，不能只按统一美元叙事解释。",
        ]
    elif agent_type in {"market_data", "supply_chain", "basis_structure", "liquidity_curve", "policy_supply", "macro_policy", "positioning", "flow", "earnings", "policy_industry"}:
        catalog_overview = market_data_digest.get("catalog_overview", []) or []
        analysis_focus = market_data_digest.get("analysis_focus", []) or []
        confidence = min(0.9, 0.42 + min(len(catalog_overview), 4) * 0.08 + min(len(analysis_focus), 3) * 0.06)
        summary = market_data_digest.get("summary") or "市场数据底座已接入，但当前对应类型数据仍有限。"
        findings = list(catalog_overview[:2]) + list(analysis_focus[:1])
    elif agent_type == "actor":
        confidence = min(0.88, 0.4 + min(len(actor_profiles), 4) * 0.1)
        actor_name = str((actor_profiles[0] or {}).get("name") or "关键主体") if actor_profiles else "关键主体"
        actor_stance = str((actor_profiles[0] or {}).get("stance") or "立场待确认") if actor_profiles else "立场待确认"
        summary = f"{actor_name} 是当前主题的主要驱动主体，立场为 {actor_stance}。"
        findings = [
            f"主体层共识数量 {len(actor_profiles)}，说明{'驱动方较清晰' if actor_profiles else '主体仍需进一步确认'}。",
            str((actor_profiles[0] or {}).get("summary") or "当前还缺少更强的主体层公开表态。"),
        ]
    elif agent_type == "cross_asset":
        confidence = min(0.86, 0.38 + min(len(cross_asset_signals), 4) * 0.1)
        aligned = [item for item in cross_asset_signals if "共振" in str(item.get("alignment_label") or "")]
        summary = f"跨资产联动监控到 {len(cross_asset_signals)} 个信号，其中 {len(aligned)} 个表现为共振。"
        findings = [
            f"主资产价格状态：{str(asset_context.get('status_label') or '待确认')}。",
            str((cross_asset_signals[0] or {}).get("alignment_label") or "跨资产当前尚未形成强共振。") if cross_asset_signals else "跨资产当前尚未形成强共振。",
        ]
    elif agent_type in {"geopolitics", "catalyst"}:
        confidence = min(0.86, 0.46 + min(len(theme_news), 5) * 0.06)
        summary = f"{str(theme_definition.get('label') or '当前主题')} 对 {str(asset_context.get('asset_name') or asset_context.get('current_code') or '资产')} 的影响仍处于事件催化驱动阶段。"
        findings = [
            str((theme_news[0] or {}).get("summary") or "当前催化仍需继续补证据确认强度。") if theme_news else "当前催化仍需继续补证据确认强度。",
            f"价格方向暂时表现为 {str(asset_context.get('status_label') or '待确认')}。",
        ]
    elif agent_type == "arbiter":
        summary = "等待汇总其他 Agent 后形成最终裁决。"
        findings = ["该 Agent 负责识别多 Agent 共识和冲突，不直接产出单独方向。"]
        confidence = 0.66
        stance = "neutral"
    else:
        confidence = 0.55
        summary = str(agent_definition.get("instructions") or agent_definition.get("description") or f"{agent_definition.get('label') or '自定义Agent'} 已接入当前主题推演。")
        findings = [
            "该 Agent 使用自定义角色与说明参与推演。",
            "如需更强判断，可在设置中补充更具体的主题关键词和关注点。",
        ]

    findings = [str(item or "").strip() for item in findings if str(item or "").strip()][:4]
    return {
        "agent_id": str(agent_definition.get("id") or ""),
        "label": str(agent_definition.get("label") or ""),
        "agent_type": agent_type,
        "role": str(agent_definition.get("role") or ""),
        "description": str(agent_definition.get("description") or ""),
        "priority": int(agent_definition.get("priority", 50) or 50),
        "preset_source": str(agent_definition.get("preset_source") or ""),
        "stance": _resolve_agent_stance_label(stance),
        "stance_key": str(stance or "neutral"),
        "confidence": round(max(0.0, min(confidence, 0.99)), 3),
        "summary": summary,
        "findings": findings,
        "focus_points": list(agent_definition.get("focus_points") or [])[:4],
        "instructions": str(agent_definition.get("instructions") or ""),
    }


def _build_theme_multi_agent_panel(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    toolkit_payload: Dict[str, Any],
    temporal_evidence: Dict[str, Any],
    market_data_snapshot: Dict[str, Any],
    cross_asset_watch: Dict[str, Any],
    agent_definitions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    market_data_digest = _summarize_market_data_snapshot(market_data_snapshot)
    current_market = str(asset_context.get("current_market") or "")
    current_code = str(asset_context.get("current_code") or "")
    product_info = _get_product_info(current_code, current_market) if current_market or current_code else {}
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    fx_route = _classify_fx_theme_route(current_code, theme_definition, product_info) if asset_class == "fx" else {}
    agent_outputs: List[Dict[str, Any]] = []
    for agent_definition in agent_definitions:
        if str(agent_definition.get("agent_type") or "") == "arbiter":
            continue
        agent_outputs.append(
            _build_theme_agent_output(
                agent_definition=agent_definition,
                theme_definition=theme_definition,
                asset_context=asset_context,
                toolkit_payload=toolkit_payload,
                temporal_evidence=temporal_evidence,
                market_data_snapshot=market_data_snapshot,
                market_data_digest=market_data_digest,
                cross_asset_watch=cross_asset_watch,
            )
        )
    stance_counts = {"偏多": 0, "偏空": 0, "中性": 0}
    weighted_score = 0.0
    total_weight = 0.0
    for item in agent_outputs:
        stance = str(item.get("stance") or "中性")
        confidence = _safe_float(item.get("confidence"), 0.5)
        stance_counts[stance] = stance_counts.get(stance, 0) + 1
        if stance == "偏多":
            weighted_score += confidence
            total_weight += confidence
        elif stance == "偏空":
            weighted_score -= confidence
            total_weight += confidence
    if weighted_score > 0.18:
        consensus_stance = "偏多"
    elif weighted_score < -0.18:
        consensus_stance = "偏空"
    else:
        consensus_stance = "中性"
    aligned_agents = [item.get("label") for item in agent_outputs if str(item.get("stance") or "") == consensus_stance][:4]
    conflicting_agents = [item.get("label") for item in agent_outputs if str(item.get("stance") or "") not in {consensus_stance, "中性"}][:4]
    arbitration_summary = (
        f"当前共启用 {len(agent_outputs)} 个专题 Agent，整体裁决为 {consensus_stance}；"
        f"偏多 {stance_counts.get('偏多', 0)} 个、偏空 {stance_counts.get('偏空', 0)} 个、中性 {stance_counts.get('中性', 0)} 个。"
    )
    arbiter_definition = next((item for item in agent_definitions if str(item.get("agent_type") or "") == "arbiter"), None)
    arbiter_output = _build_theme_agent_output(
        agent_definition=arbiter_definition or {
            "id": "risk_arbiter",
            "label": "裁决 Agent",
            "agent_type": "arbiter",
            "role": "多 Agent 裁决与风险边界",
            "description": "负责汇总多 Agent 观点。",
            "priority": 110,
            "focus_points": ["共识方向", "冲突来源", "执行边界"],
            "instructions": "总结共识与冲突。",
            "preset_source": "system",
        },
        theme_definition=theme_definition,
        asset_context=asset_context,
        toolkit_payload=toolkit_payload,
        temporal_evidence=temporal_evidence,
        market_data_snapshot=market_data_snapshot,
        market_data_digest=market_data_digest,
        cross_asset_watch=cross_asset_watch,
    )
    arbiter_output["stance"] = consensus_stance
    arbiter_output["stance_key"] = {"偏多": "bullish", "偏空": "bearish"}.get(consensus_stance, "neutral")
    arbiter_output["confidence"] = round(max(0.45, min(abs(weighted_score) / max(total_weight, 1e-6), 0.92)) if total_weight else 0.45, 3)
    arbiter_output["summary"] = arbitration_summary
    arbiter_output["findings"] = [
        ("形成共识的 Agent：" + "、".join([str(item) for item in aligned_agents])) if aligned_agents else "当前尚未形成强一致结论。",
        ("主要冲突 Agent：" + "、".join([str(item) for item in conflicting_agents])) if conflicting_agents else "当前冲突主要来自中性或等待确认型 Agent。",
    ]
    return {
        "mode": "asset_theme_multi_agent",
        "asset_class": asset_class,
        "route_context": {
            "theme_type": str(fx_route.get("theme_type") or ""),
            "route_label": str(fx_route.get("label") or ""),
            "pair_code": str((fx_route.get("pair_profile") or {}).get("pair_code") or current_code or ""),
            "pair_label": str((fx_route.get("pair_profile") or {}).get("label") or ""),
            "pair_role": str((fx_route.get("pair_profile") or {}).get("role") or ""),
        } if asset_class == "fx" else {},
        "active_agents": [
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "agent_type": str(item.get("agent_type") or ""),
                "role": str(item.get("role") or ""),
                "focus_points": list(item.get("focus_points") or [])[:4],
                "priority": int(item.get("priority", 50) or 50),
                "preset_source": str(item.get("preset_source") or ""),
                "selection_score": int(item.get("selection_score", 0) or 0),
                "selection_reason": _describe_theme_agent_selection(item, asset_context, theme_definition),
            }
            for item in agent_definitions[:8]
        ],
        "agent_outputs": agent_outputs[:8],
        "arbiter": arbiter_output,
        "consensus": {
            "stance": consensus_stance,
            "weighted_score": round(weighted_score, 3),
            "aligned_agents": aligned_agents,
            "conflicting_agents": conflicting_agents,
        },
    }


def _backfill_news_asset_links(limit: int = 500, days: int = 60) -> Dict[str, Any]:
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    news_rows = db.news_query(
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )

    processed = 0
    linked_news = 0
    total_links = 0

    for news in news_rows:
        asset_rows = build_asset_link_rows(
            news_id=news.news_id or str(news.id),
            title=news.title or "",
            body=news.body or "",
        )
        db.news_asset_links_replace(news.news_id or str(news.id), asset_rows)
        processed += 1
        if asset_rows:
            linked_news += 1
            total_links += len(asset_rows)

    return {
        "processed": processed,
        "linked_news": linked_news,
        "total_links": total_links,
        "days": days,
    }


def _generate_market_summary_payload(
    data: Dict[str, Any],
    progress_callback=None,
) -> Dict[str, Any]:
    if not data:
        raise ValueError("请求体不能为空")

    query = data.get("query", "")
    current_market = data.get("current_market", "")
    current_code = data.get("current_code", "")
    product_code = data.get("product_code", "")
    frequency = data.get("frequency", "d")
    selected_nodes = data.get("selected_nodes", [])
    n_results = max(10, min(int(data.get("n_results", 20)), 30))
    days = max(1, min(int(data.get("days", 7)), 30))

    if not query:
        if product_code:
            query = product_code
        elif current_code:
            query = current_code
        else:
            raise ValueError("缺少必要参数：query、product_code、或current_code至少需要提供一个")

    if not current_market:
        raise ValueError("缺少必要参数：current_market")

    cache_payload = {
        "query": query,
        "current_market": current_market,
        "current_code": current_code,
        "product_code": product_code,
        "frequency": frequency,
        "selected_nodes": sorted(selected_nodes or []),
        "n_results": n_results,
        "days": days,
    }
    cached_result = _load_summary_result_cache("market_summary", cache_payload)
    if cached_result:
        logger.info("市场总结命中结果缓存")
        return cached_result

    def _progress(stage: str, message: str, progress: int) -> None:
        if progress_callback is not None:
            progress_callback(stage=stage, message=message, progress=progress)

    logger.info(
        f"开始生成市场总结 query={query} market={current_market} "
        f"code={current_code} n_results={n_results} days={days}"
    )

    lookup_code = product_code or current_code or query
    _progress("prepare", "正在优化新闻检索条件", 5)
    optimized_query, product_info = _create_optimized_search_query(query, lookup_code)

    _progress("search_news", "正在检索相关新闻", 20)
    ex = get_exchange(Market(current_market))
    stock_info = ex.stock_info(current_code) if current_code else {}
    name = (
        stock_info.get("name")
        or product_info.get("name_cn")
        or product_info.get("cn_name")
        or product_info.get("name_en")
        or current_code
        or query
    )

    news_list = get_vector_news(
        current_code or product_code or query,
        current_market,
        days,
        n_results=n_results,
        query=optimized_query,
        product_info=product_info,
    )
    if not news_list:
        raise ValueError("未找到相关新闻，请尝试调整搜索条件")

    canonical_asset = _normalize_asset_code(lookup_code)
    evidence_buckets = _bucket_news_evidence(news_list[:n_results], canonical_asset)

    formatted_news_list = []
    direction_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for bucket_name in ["direct", "driver", "background"]:
        for news in evidence_buckets[bucket_name]:
            metadata = news.get("metadata", {})
            bucket_label = {
                "direct": "[直接相关]",
                "driver": "[驱动相关]",
                "background": "[背景参考]",
            }[bucket_name]
            direction_label = {
                "bullish": "利多",
                "bearish": "利空",
                "neutral": "中性",
            }.get(news.get("impact_direction", "neutral"), "中性")
            direction_counts[news.get("impact_direction", "neutral")] = (
                direction_counts.get(news.get("impact_direction", "neutral"), 0) + 1
            )
            formatted_news_list.append(
                {
                    "title": f"[{direction_label}]{bucket_label} {metadata.get('title', '')}".strip(),
                    "body": news.get("document", ""),
                    "content": news.get("document", ""),
                    "published_at": metadata.get("published_at", ""),
                    "source": metadata.get("source", ""),
                    "category": metadata.get("category", ""),
                    "sentiment_score": metadata.get("sentiment_score", 0),
                    "importance_score": metadata.get("importance_score", 0),
                    "news_id": metadata.get("news_id", ""),
                    "evidence_type": bucket_name,
                    "impact_direction": news.get("impact_direction", "neutral"),
                    "direction_reason": news.get("direction_reason", ""),
                    "direct_assets": metadata.get("direct_assets", []),
                    "driver_assets": metadata.get("driver_assets", []),
                }
            )

    _progress("economic_data", "正在整理经济数据", 45)
    economic_data_list = _get_economic_data_by_product(
        product_info=product_info,
        product_code=lookup_code,
        limit=500,
    )

    direct_focus_news = [_format_realtime_focus_news_item(item, "direct") for item in evidence_buckets["direct"][:3]]
    driver_focus_news = [_format_realtime_focus_news_item(item, "driver") for item in evidence_buckets["driver"][:3]]
    price_state = (
        _summarize_realtime_price_state(current_market, current_code)
        if current_code
        else {
            "available": False,
            "direction": "neutral",
            "change_5m_pct": 0.0,
            "change_30m_pct": 0.0,
            "range_60m_pct": 0.0,
            "status_label": "缺少资产代码",
            "alert_level": "low",
            "recent_event": None,
        }
    )
    cross_asset_watch = (
        _build_cross_asset_watch(
            current_market=current_market,
            current_code=current_code,
            current_price_state=price_state,
            product_info=product_info,
        )
        if current_code
        else {"items": [], "summary": ""}
    )
    scenario_route = _build_research_scenario_route(
        current_market=current_market,
        current_code=current_code,
        price_state=price_state,
        direct_news=direct_focus_news,
        driver_news=driver_focus_news,
        cross_asset_watch=cross_asset_watch,
    )
    reflection_memory = _build_reflection_memory(
        current_market=current_market,
        current_code=current_code,
        scenario_route=scenario_route,
    )
    quick_research = _build_quick_research_snapshot(
        asset_name=name,
        current_code=current_code,
        scenario_route=scenario_route,
        price_state=price_state,
        direct_news=direct_focus_news,
        driver_news=driver_focus_news,
    )
    routed_selected_nodes = selected_nodes or scenario_route.get("deep_nodes", [])
    deep_research = _build_deep_research_plan(
        scenario_route=scenario_route,
        selected_nodes=routed_selected_nodes,
    )
    timesfm_forecast = _build_timesfm_forecast(
        current_market=current_market,
        current_code=current_code,
        frequency="5m",
        price_state=price_state,
        direct_news=direct_focus_news,
        driver_news=driver_focus_news,
        cross_asset_watch=cross_asset_watch,
        scenario_route=scenario_route,
    )
    risk_brief = _build_rule_based_risk_brief(
        scenario_route=scenario_route,
        price_state=price_state,
        cross_asset_watch=cross_asset_watch,
        forecast_bundle=timesfm_forecast,
    )

    logger.info(
        f"市场总结使用 {len(formatted_news_list)} 条新闻、"
        f"direct={len(evidence_buckets['direct'])} "
        f"driver={len(evidence_buckets['driver'])} "
        f"background={len(evidence_buckets['background'])}、"
        f"{len(economic_data_list)} 条经济数据"
    )

    _progress("summary", "AI 正在生成市场总结", 70)
    summary_result = _generate_ai_market_summary(
        economic_data_list,
        formatted_news_list,
        current_market,
        current_code,
        name,
        frequency,
        routed_selected_nodes,
        scenario_route=scenario_route,
        reflection_memory=reflection_memory,
        quick_research=quick_research,
        deep_research=deep_research,
    )
    if isinstance(summary_result, dict):
        scenario_route = summary_result.get("scenario_route", scenario_route) or scenario_route
        reflection_memory = summary_result.get("reflection_memory", reflection_memory) or reflection_memory
        quick_research = summary_result.get("quick_research", quick_research) or quick_research
        deep_research = summary_result.get("deep_research", deep_research) or deep_research
    summary = summary_result.get("summary", "") if isinstance(summary_result, dict) else str(summary_result)
    risk_assessment = summary_result.get("risk_assessment", "") if isinstance(summary_result, dict) else ""
    research_verdict = summary_result.get("research_verdict", "") if isinstance(summary_result, dict) else ""

    _progress("save", "正在保存总结结果", 92)
    summary_id = None
    try:
        summary_data = {
            "title": f"{current_market}-{current_code} 研究报告"
            if current_market and current_code
            else "研究报告",
            "content": summary,
            "market": current_market,
            "code": current_code,
            "summary_type": "market_analysis",
        }
        summary_id = db.market_summary_insert(summary_data)
        logger.info(f"研究报告已保存到数据库，ID: {summary_id}")
    except Exception as db_error:
        logger.error(f"保存研究报告到数据库失败: {str(db_error)}")

    _progress("completed", "市场总结生成完成", 100)
    result = {
        "summary": summary,
        "summary_id": summary_id,
        "query": query,
        "optimized_query": optimized_query,
        "current_market": current_market,
        "current_code": current_code,
        "product_code": product_code,
        "frequency": frequency,
        "days": days,
        "n_results": n_results,
        "selected_nodes": routed_selected_nodes,
        "news_count": len(formatted_news_list),
        "economic_data_count": len(economic_data_list),
        "product_info": product_info,
        "scenario_route": scenario_route,
        "reflection_memory": reflection_memory,
        "quick_research": quick_research,
        "deep_research": deep_research,
        "risk_brief": risk_brief,
        "risk_assessment": risk_assessment,
        "research_verdict": research_verdict,
        "timesfm_forecast": timesfm_forecast,
        "price_state": price_state,
        "cross_asset_summary": cross_asset_watch.get("summary", ""),
        "evidence_counts": {
            "direct": len(evidence_buckets["direct"]),
            "driver": len(evidence_buckets["driver"]),
            "background": len(evidence_buckets["background"]),
        },
        "direction_counts": direction_counts,
        "cache_hit": False,
    }
    _save_summary_result_cache("market_summary", cache_payload, result)
    return result


def _run_market_summary_task(task_id: str, payload: Dict[str, Any]) -> None:
    try:
        _set_market_summary_task(
            task_id,
            task_type="market_summary",
            state="running",
            stage="prepare",
            message="任务已启动",
            progress=1,
            started_at=datetime.now().isoformat(),
        )

        result = _generate_market_summary_payload(
            payload,
            progress_callback=lambda stage, message, progress: _set_market_summary_task(
                task_id,
                stage=stage,
                message=message,
                progress=progress,
            ),
        )
        _set_market_summary_task(
            task_id,
            state="completed",
            task_type="market_summary",
            stage="completed",
            message="市场总结生成完成",
            progress=100,
            result=result,
            summary_id=result.get("summary_id"),
            summary_preview=(result.get("summary") or "")[:300],
            finished_at=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"异步生成市场总结失败: {str(e)}", exc_info=True)
        _set_market_summary_task(
            task_id,
            state="failed",
            task_type="market_summary",
            stage="failed",
            message=str(e),
            progress=100,
            error=str(e),
            finished_at=datetime.now().isoformat(),
        )


def _get_news_window_for_summary(days: int, limit: int = 5000) -> tuple[List[Dict[str, Any]], str]:
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    vector_db = get_vector_db()
    if getattr(vector_db, "is_ready", lambda: False)():
        news_items = vector_db.get_news_by_date_range(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            limit=limit,
        )
        if news_items:
            return news_items, "vector"

    db_rows = db.news_query(
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )
    return [_format_db_news_item(news, 0.0) for news in db_rows], "db"


def _generate_daily_summary_payload(
    data: Dict[str, Any],
    progress_callback=None,
) -> Dict[str, Any]:
    data = data or {}
    days = data.get("days", 1)

    if not isinstance(days, int) or days < 1 or days > 30:
        raise ValueError("天数参数无效，请选择1-30天")

    cache_payload = {"days": days}
    cached_result = _load_summary_result_cache("daily_news_summary", cache_payload)
    if cached_result:
        logger.info("每日新闻总结命中结果缓存")
        return cached_result

    def _progress(stage: str, message: str, progress: int) -> None:
        if progress_callback is not None:
            progress_callback(stage=stage, message=message, progress=progress)

    logger.info(f"开始生成{days}天的每日新闻总结")
    _progress("search_news", f"正在获取近{days}天新闻", 15)

    all_news, source_type = _get_news_window_for_summary(days, limit=5000)
    if not all_news:
        raise ValueError(f"未找到{days}天内的新闻数据")

    logger.info(f"获取到{len(all_news)}条新闻，来源={source_type}")

    _progress("analyze_targets", "正在分析重要标的", 40)
    analyzed_targets = _analyze_important_targets(all_news)

    formatted_news_list = []
    for news in all_news:
        metadata = news.get("metadata", {})
        formatted_news_list.append(
            {
                "title": metadata.get("title", ""),
                "body": news.get("document", ""),
                "content": news.get("document", ""),
                "published_at": metadata.get("published_at", ""),
                "source": metadata.get("source", ""),
                "category": metadata.get("category", ""),
                "sentiment_score": metadata.get("sentiment_score", 0),
                "importance_score": metadata.get("importance_score", 0),
                "news_id": metadata.get("news_id", ""),
            }
        )

    _progress("summary", "AI 正在生成每日新闻总结", 70)
    summary = _generate_daily_news_summary(
        news_list=formatted_news_list,
        analyzed_targets=analyzed_targets,
        days=days,
    )
    trader_brief = _build_daily_summary_trader_brief(
        news_list=formatted_news_list,
        analyzed_targets=analyzed_targets,
        days=days,
    )

    _progress("save", "正在保存每日新闻总结", 92)
    summary_id = None
    try:
        summary_data = {
            "title": f"{days}天每日新闻总结",
            "content": summary,
            "market": "all",
            "code": "daily_summary",
            "summary_type": "daily_news_summary",
        }
        summary_id = db.market_summary_insert(summary_data)
        logger.info(f"每日新闻总结已保存到数据库，ID: {summary_id}")
    except Exception as db_error:
        logger.error(f"保存每日新闻总结到数据库失败: {str(db_error)}")

    _progress("completed", "每日新闻总结生成完成", 100)
    result = {
        "summary": summary,
        "summary_id": summary_id,
        "analyzed_targets": analyzed_targets,
        "news_count": len(formatted_news_list),
        "days": days,
        "source_type": source_type,
        "trader_brief": trader_brief,
        "cache_hit": False,
    }
    _save_summary_result_cache("daily_news_summary", cache_payload, result)
    return result


def _run_daily_summary_task(task_id: str, payload: Dict[str, Any]) -> None:
    try:
        _set_market_summary_task(
            task_id,
            task_type="daily_news_summary",
            state="running",
            stage="prepare",
            message="任务已启动",
            progress=1,
            started_at=datetime.now().isoformat(),
        )
        result = _generate_daily_summary_payload(
            payload,
            progress_callback=lambda stage, message, progress: _set_market_summary_task(
                task_id,
                stage=stage,
                message=message,
                progress=progress,
            ),
        )
        _set_market_summary_task(
            task_id,
            task_type="daily_news_summary",
            state="completed",
            stage="completed",
            message="每日新闻总结生成完成",
            progress=100,
            result=result,
            summary_id=result.get("summary_id"),
            summary_preview=(result.get("summary") or "")[:300],
            finished_at=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"异步生成每日新闻总结失败: {str(e)}", exc_info=True)
        _set_market_summary_task(
            task_id,
            task_type="daily_news_summary",
            state="failed",
            stage="failed",
            message=str(e),
            progress=100,
            error=str(e),
            finished_at=datetime.now().isoformat(),
        )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime_like(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _normalize_history_analysis_params(data: Dict[str, Any]) -> Dict[str, Any]:
    data = data or {}
    lookback_hours = int(data.get("lookback_hours", 24) or 24)
    event_window_minutes = int(data.get("event_window_minutes", 5) or 5)
    merge_gap_minutes = int(data.get("merge_gap_minutes", 10) or 10)
    max_events = int(data.get("max_events", 8) or 8)
    frequency = str(data.get("event_frequency", "5m") or "5m")
    min_return_pct = float(data.get("min_return_pct", 0.35) or 0.35)
    min_range_pct = float(data.get("min_range_pct", 0.55) or 0.55)
    atr_multiple = float(data.get("atr_multiple", 1.2) or 1.2)

    if lookback_hours < 4 or lookback_hours > 72:
        raise ValueError("回看时长需在 4-72 小时之间")
    if event_window_minutes < 1 or event_window_minutes > 30:
        raise ValueError("事件新闻窗口需在 1-30 分钟之间")
    if merge_gap_minutes < 0 or merge_gap_minutes > 60:
        raise ValueError("事件合并间隔需在 0-60 分钟之间")
    if max_events < 1 or max_events > 20:
        raise ValueError("最多事件数需在 1-20 之间")
    if min_return_pct <= 0 or min_range_pct <= 0 or atr_multiple <= 0:
        raise ValueError("波动阈值参数必须大于 0")

    return {
        "lookback_hours": lookback_hours,
        "event_window_minutes": event_window_minutes,
        "merge_gap_minutes": merge_gap_minutes,
        "max_events": max_events,
        "event_frequency": frequency,
        "min_return_pct": min_return_pct,
        "min_range_pct": min_range_pct,
        "atr_multiple": atr_multiple,
    }


def _format_lookback_label(lookback_hours: int) -> str:
    lookback_hours = max(int(lookback_hours or 0), 1)
    if lookback_hours % 24 == 0:
        days = int(lookback_hours / 24)
        return f"{days}天"
    return f"{lookback_hours}小时"


def _frequency_to_minutes(frequency: str) -> int:
    freq = str(frequency or "").strip().lower()
    mapping = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "10m": 10,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "120m": 120,
        "240m": 240,
        "d": 1440,
        "1d": 1440,
    }
    if freq in mapping:
        return mapping[freq]
    match = re.match(r"^(\d+)\s*([mhd])$", freq)
    if not match:
        return 0
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return value
    if unit == "h":
        return value * 60
    if unit == "d":
        return value * 1440
    return 0


def _estimate_historical_bar_limit(frequency: str, lookback_hours: int) -> int:
    frequency_minutes = _frequency_to_minutes(frequency)
    if frequency_minutes <= 0:
        return max(lookback_hours * 24, 120)
    expected_bars = int((lookback_hours * 60) / max(frequency_minutes, 1))
    return max(expected_bars + 24, 120)


def _rows_to_price_bars(rows: List[Any]) -> List[Dict[str, Any]]:
    price_bars: List[Dict[str, Any]] = []
    for row in rows:
        dt_value = getattr(row, "dt", None)
        if not dt_value:
            continue
        price_bars.append(
            {
                "dt": dt_value,
                "open": _safe_float(getattr(row, "o", None)),
                "close": _safe_float(getattr(row, "c", None)),
                "high": _safe_float(getattr(row, "h", None)),
                "low": _safe_float(getattr(row, "l", None)),
                "volume": _safe_float(getattr(row, "v", None)),
            }
        )
    return price_bars


def _dataframe_to_price_bars(dataframe: Any) -> List[Dict[str, Any]]:
    if dataframe is None or getattr(dataframe, "empty", True):
        return []
    records = dataframe.to_dict("records")
    price_bars: List[Dict[str, Any]] = []
    for row in records:
        dt_value = row.get("date") or row.get("dt") or row.get("datetime")
        if not dt_value:
            continue
        if isinstance(dt_value, str):
            try:
                dt_value = datetime.fromisoformat(dt_value.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                try:
                    dt_value = datetime.strptime(dt_value, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
        price_bars.append(
            {
                "dt": dt_value,
                "open": _safe_float(row.get("open") if "open" in row else row.get("o")),
                "close": _safe_float(row.get("close") if "close" in row else row.get("c")),
                "high": _safe_float(row.get("high") if "high" in row else row.get("h")),
                "low": _safe_float(row.get("low") if "low" in row else row.get("l")),
                "volume": _safe_float(row.get("volume") if "volume" in row else row.get("v")),
            }
        )
    return price_bars


def _normalize_price_dataframe_for_storage(dataframe: Any) -> Any:
    if dataframe is None or getattr(dataframe, "empty", True):
        return None
    try:
        normalized = dataframe.copy()
    except Exception:
        return None
    rename_map = {}
    if "dt" in normalized.columns and "date" not in normalized.columns:
        rename_map["dt"] = "date"
    if "datetime" in normalized.columns and "date" not in normalized.columns:
        rename_map["datetime"] = "date"
    if "o" in normalized.columns and "open" not in normalized.columns:
        rename_map["o"] = "open"
    if "c" in normalized.columns and "close" not in normalized.columns:
        rename_map["c"] = "close"
    if "h" in normalized.columns and "high" not in normalized.columns:
        rename_map["h"] = "high"
    if "l" in normalized.columns and "low" not in normalized.columns:
        rename_map["l"] = "low"
    if "v" in normalized.columns and "volume" not in normalized.columns:
        rename_map["v"] = "volume"
    if rename_map:
        normalized = normalized.rename(columns=rename_map)
    required_columns = ["date", "open", "close", "high", "low", "volume"]
    if any(column not in normalized.columns for column in required_columns):
        return None
    return normalized[required_columns + ([ "position"] if "position" in normalized.columns else [])]


def _persist_exchange_price_bars(
    market: str,
    code: str,
    frequency: str,
    dataframe: Any,
) -> None:
    normalized = _normalize_price_dataframe_for_storage(dataframe)
    if normalized is None or getattr(normalized, "empty", True):
        return
    try:
        db.klines_insert(market=market, code=code, frequency=frequency, klines=normalized)
    except Exception as e:
        logger.warning(f"保存交易所K线到数据库失败: {market} {code} {frequency} {str(e)}")


def _get_latest_price_bar_dt(price_bars: List[Dict[str, Any]]) -> Optional[datetime]:
    if not price_bars:
        return None
    latest_dt = price_bars[-1].get("dt")
    if isinstance(latest_dt, datetime):
        return latest_dt.replace(tzinfo=None)
    return None


def _price_data_refresh_threshold_minutes(frequency: str) -> int:
    base_minutes = max(_frequency_to_minutes(frequency), 1)
    return max(base_minutes * 3, 15)


def _is_price_bar_series_stale(
    price_bars: List[Dict[str, Any]],
    frequency: str,
    now_dt: Optional[datetime] = None,
) -> bool:
    latest_dt = _get_latest_price_bar_dt(price_bars)
    if latest_dt is None:
        return True
    now_dt = (now_dt or datetime.now()).replace(tzinfo=None)
    return (now_dt - latest_dt).total_seconds() / 60.0 > _price_data_refresh_threshold_minutes(frequency)


def _build_price_code_candidates(market: str, code: str) -> List[str]:
    raw_code = str(code or "").strip().upper()
    candidates: List[str] = []
    if raw_code:
        candidates.append(raw_code)

    if market == "fx":
        compact = re.sub(r"[^A-Z]", "", raw_code)
        if "." in raw_code:
            suffix = raw_code.split(".")[-1]
            compact = re.sub(r"[^A-Z]", "", suffix)
        if len(compact) == 6:
            base = compact[:3]
            quote = compact[3:]
            candidates.extend(
                [
                    f"FX.{compact}",
                    f"FX.{quote}{base}",
                    f"FE.{compact}",
                    f"FE.{quote}{base}",
                ]
            )

    seen = set()
    ordered_candidates: List[str] = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered_candidates.append(candidate)
    return ordered_candidates


def _query_price_bars_from_db(
    market: str,
    code: str,
    frequency: str,
    query_limit: int,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    order: str = "asc",
) -> List[Dict[str, Any]]:
    try:
        rows = db.klines_query(
            market=market,
            code=code,
            frequency=frequency,
            start_date=start_dt,
            end_date=end_dt,
            limit=query_limit,
            order=order,
        )
    except Exception:
        return []
    return _rows_to_price_bars(rows if order == "asc" else list(reversed(rows)))


def _query_price_bars_from_exchange(
    market: str,
    code: str,
    frequency: str,
    query_limit: int,
) -> List[Dict[str, Any]]:
    try:
        ex = get_exchange(Market(market))
        pages = max(1, min(12, int(query_limit / 700) + 1))
        dataframe = ex.klines(code, frequency, args={"pages": pages})
        _persist_exchange_price_bars(market=market, code=code, frequency=frequency, dataframe=dataframe)
        return _dataframe_to_price_bars(dataframe)
    except Exception:
        return []


def _load_historical_price_bars(
    market: str,
    code: str,
    frequency: str,
    lookback_hours: int,
    purpose: str = "价格分析",
) -> List[Dict[str, Any]]:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=lookback_hours)
    query_limit = max(_estimate_historical_bar_limit(frequency, lookback_hours), 500)
    candidates = _build_price_code_candidates(market, code)
    best_bars: List[Dict[str, Any]] = []
    best_code = code

    for candidate in candidates:
        strict_bars = _query_price_bars_from_db(
            market=market,
            code=candidate,
            frequency=frequency,
            query_limit=query_limit,
            start_dt=start_dt,
            end_dt=end_dt,
            order="asc",
        )
        if len(strict_bars) > len(best_bars):
            best_bars = strict_bars
            best_code = candidate
        if len(strict_bars) >= 10 and not _is_price_bar_series_stale(strict_bars, frequency):
            return strict_bars

    for candidate in candidates:
        fallback_bars = _query_price_bars_from_db(
            market=market,
            code=candidate,
            frequency=frequency,
            query_limit=query_limit,
            order="desc",
        )
        if len(fallback_bars) > len(best_bars):
            best_bars = fallback_bars
            best_code = candidate
        if len(fallback_bars) >= 10 and not _is_price_bar_series_stale(fallback_bars, frequency):
            _log_price_bar_fallback(
                purpose=purpose,
                fallback_type="最近可用K线",
                market=market,
                code=code,
                resolved_code=candidate,
                frequency=frequency,
                count=len(fallback_bars),
            )
            return fallback_bars

    for candidate in candidates:
        exchange_bars = _query_price_bars_from_exchange(
            market=market,
            code=candidate,
            frequency=frequency,
            query_limit=query_limit,
        )
        if len(exchange_bars) > len(best_bars):
            best_bars = exchange_bars
            best_code = candidate
        if len(exchange_bars) >= 10:
            _log_price_bar_fallback(
                purpose=purpose,
                fallback_type="交易所实时K线",
                market=market,
                code=code,
                resolved_code=candidate,
                frequency=frequency,
                count=len(exchange_bars),
            )
            return exchange_bars

    if best_bars:
        _log_price_bar_fallback(
            purpose=purpose,
            fallback_type="最佳候选K线",
            market=market,
            code=code,
            resolved_code=best_code,
            frequency=frequency,
            count=len(best_bars),
        )
    return best_bars


def _alert_level_rank(level: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(level, 0)


def _format_focus_time_label(value: Any) -> str:
    if not value:
        return "--"
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:%M")
    text = str(value).replace("T", " ").replace("Z", "")
    if len(text) >= 16:
        return text[5:16]
    return text


def _format_realtime_focus_news_item(news: Dict[str, Any], evidence_type: str) -> Dict[str, Any]:
    metadata = news.get("metadata", {}) if isinstance(news.get("metadata", {}), dict) else {}
    body = news.get("document") or metadata.get("title") or ""
    body = re.sub(r"\s+", " ", body).strip()
    summary = body[:90] + "..." if len(body) > 90 else body
    impact_direction = news.get("impact_direction", "neutral")
    importance_score = _safe_float(metadata.get("importance_score", 0.0))
    alert_level = "high" if importance_score >= 0.75 else "medium" if importance_score >= 0.45 else "low"
    return {
        "news_id": metadata.get("news_id") or news.get("id"),
        "title": metadata.get("title") or summary or "未命名新闻",
        "source": metadata.get("source", ""),
        "published_at": metadata.get("published_at", ""),
        "published_at_label": _format_focus_time_label(metadata.get("published_at", "")),
        "evidence_type": evidence_type,
        "evidence_label": {
            "direct": "直接新闻",
            "driver": "驱动线索",
            "background": "背景线索",
        }.get(evidence_type, "新闻"),
        "impact_direction": impact_direction,
        "impact_label": {
            "bullish": "偏利多",
            "bearish": "偏利空",
            "neutral": "中性",
        }.get(impact_direction, "中性"),
        "direction_reason": news.get("direction_reason", ""),
        "importance_score": importance_score,
        "alert_level": alert_level,
        "summary": summary,
    }


_SCENARIO_ROUTE_PRESETS = {
    "price_news_resonance": {
        "label": "价格与新闻共振",
        "quick_nodes": ["technical_analyst", "chanlun_expert", "macro_analyst"],
        "deep_nodes": ["macro_analyst", "economic_data_analyst", "technical_analyst", "chanlun_expert", "geopolitical_analyst"],
    },
    "news_catalyst": {
        "label": "新闻催化跟踪",
        "quick_nodes": ["macro_analyst", "economic_data_analyst"],
        "deep_nodes": ["macro_analyst", "economic_data_analyst", "technical_analyst", "chanlun_expert", "geopolitical_analyst"],
    },
    "cross_asset_propagation": {
        "label": "跨资产传导确认",
        "quick_nodes": ["technical_analyst", "macro_analyst"],
        "deep_nodes": ["macro_analyst", "technical_analyst", "chanlun_expert", "geopolitical_analyst"],
    },
    "historical_followthrough": {
        "label": "历史主线延续",
        "quick_nodes": ["technical_analyst", "chanlun_expert"],
        "deep_nodes": ["macro_analyst", "economic_data_analyst", "technical_analyst", "chanlun_expert", "geopolitical_analyst"],
    },
    "price_dislocation": {
        "label": "价格先行异动",
        "quick_nodes": ["technical_analyst", "chanlun_expert"],
        "deep_nodes": ["technical_analyst", "chanlun_expert", "macro_analyst", "economic_data_analyst"],
    },
    "balanced_monitoring": {
        "label": "均衡观察",
        "quick_nodes": ["technical_analyst", "macro_analyst"],
        "deep_nodes": ["macro_analyst", "economic_data_analyst", "technical_analyst", "chanlun_expert", "financial_analyst", "geopolitical_analyst"],
    },
}

_ANALYST_NODE_LABELS = {
    "macro_analyst": "宏观分析师",
    "economic_data_analyst": "经济数据分析师",
    "technical_analyst": "技术指标分析师",
    "chanlun_expert": "缠论结构专家",
    "financial_analyst": "财务分析师",
    "geopolitical_analyst": "地缘政治分析师",
}


def _build_research_scenario_route(
    current_market: str,
    current_code: str,
    price_state: Optional[Dict[str, Any]] = None,
    direct_news: Optional[List[Dict[str, Any]]] = None,
    driver_news: Optional[List[Dict[str, Any]]] = None,
    cross_asset_watch: Optional[Any] = None,
    storylines: Optional[List[Dict[str, Any]]] = None,
    pricing_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    price_state = price_state or {}
    direct_news = direct_news or []
    driver_news = driver_news or []
    storylines = storylines or []
    pricing_summary = pricing_summary or {}
    if isinstance(cross_asset_watch, dict):
        cross_items = cross_asset_watch.get("items", [])
    elif isinstance(cross_asset_watch, list):
        cross_items = cross_asset_watch
    else:
        cross_items = []

    high_price = _alert_level_rank(price_state.get("alert_level", "low")) >= 3
    high_direct_news = any(_alert_level_rank(item.get("alert_level", "low")) >= 2 for item in direct_news[:2])
    aligned_cross = any(
        item.get("alignment") == "aligned" and _alert_level_rank(item.get("alert_level", "low")) >= 2
        for item in cross_items[:3]
    )
    strongest_storyline = storylines[0] if storylines else {}
    future_bias = str(pricing_summary.get("future_bias", "") or "")
    if strongest_storyline and future_bias and "延续" in future_bias:
        route_key = "historical_followthrough"
        trigger = strongest_storyline.get("storyline", "历史主线")
        reason = f"最强主线“{trigger}”仍指向{future_bias}，适合先看延续性与风险定价。"
    elif high_price and high_direct_news:
        route_key = "price_news_resonance"
        trigger = direct_news[0].get("title", "直接新闻")
        reason = "价格异动与直接新闻同时确认，适合先快评后深挖。"
    elif high_direct_news:
        route_key = "news_catalyst"
        trigger = direct_news[0].get("title", "新闻催化")
        reason = "直接新闻强于价格确认，需要先评估是否会继续传导到价格。"
    elif aligned_cross:
        route_key = "cross_asset_propagation"
        trigger = cross_items[0].get("name") or cross_items[0].get("code") or "跨资产线索"
        reason = "关键参考资产已经出现一致性变化，更像是跨资产主线在传导。"
    elif high_price:
        route_key = "price_dislocation"
        trigger = price_state.get("status_label", "价格异动")
        reason = "价格先行放大，但尚缺乏足够新闻证据，需优先查确认信号。"
    else:
        route_key = "balanced_monitoring"
        trigger = current_code or "当前资产"
        reason = "当前没有单一主导触发源，需要均衡跟踪新闻、价格与联动。"

    preset = _SCENARIO_ROUTE_PRESETS[route_key]
    return {
        "route": route_key,
        "label": preset["label"],
        "trigger": trigger,
        "reason": reason,
        "quick_nodes": list(preset["quick_nodes"]),
        "deep_nodes": list(preset["deep_nodes"]),
        "market": current_market,
        "code": current_code,
    }


def _build_reflection_memory(
    current_market: str,
    current_code: str,
    scenario_route: Optional[Dict[str, Any]] = None,
    lookback_limit: int = 12,
    memory_limit: int = 3,
) -> Dict[str, Any]:
    scenario_route = scenario_route or {}
    rows: List[Any] = []
    try:
        rows = db.market_summary_query(limit=lookback_limit, market=current_market, code=current_code)
    except Exception as e:
        logger.warning(f"读取反思记忆失败: {str(e)}")
        rows = []

    route_keywords = {
        str(scenario_route.get("label", "") or ""),
        str(scenario_route.get("trigger", "") or ""),
        str(scenario_route.get("route", "") or ""),
    }
    route_keywords = {item for item in route_keywords if item}

    memory_items: List[Dict[str, Any]] = []
    for row in rows:
        content = str(getattr(row, "content", "") or "")
        title = str(getattr(row, "title", "") or "")
        if not content and not title:
            continue
        preview = re.sub(r"\s+", " ", content or title).strip()
        if len(preview) > 180:
            preview = preview[:180] + "..."
        score = 0
        haystack = f"{title} {content}"
        for keyword in route_keywords:
            if keyword and keyword in haystack:
                score += 1
        if getattr(row, "summary_type", "") == "historical_analysis":
            score += 1
        lesson = preview
        if "失效" in haystack:
            lesson = "过去类似场景里，失效条件往往比主线结论更早出现。"
        elif "风险" in haystack:
            lesson = "过去记录显示，风险提示常先于趋势反转，应优先跟踪风险信号。"
        elif "未充分定价" in haystack or "剩余空间" in haystack:
            lesson = "过去类似场景里，是否已定价与剩余空间判断最有参考价值。"
        memory_items.append(
            {
                "summary_id": getattr(row, "id", None),
                "summary_type": getattr(row, "summary_type", ""),
                "title": title or "历史记录",
                "created_at": getattr(row, "created_at", None).isoformat() if getattr(row, "created_at", None) else "",
                "preview": preview,
                "lesson": lesson,
                "score": score,
            }
        )

    memory_items.sort(key=lambda item: (item.get("score", 0), item.get("created_at", "")), reverse=True)
    memory_items = memory_items[:memory_limit]
    summary = "；".join(item.get("lesson", "") for item in memory_items if item.get("lesson")) or "暂无相似反思记忆"
    memory_text = "\n".join(f"- {item.get('title', '历史记录')}: {item.get('lesson', '')}" for item in memory_items) or "- 暂无相似反思记忆"
    return {
        "items": memory_items,
        "summary": summary,
        "memory_text": memory_text,
    }


def _build_rule_based_risk_brief(
    scenario_route: Optional[Dict[str, Any]] = None,
    price_state: Optional[Dict[str, Any]] = None,
    cross_asset_watch: Optional[Any] = None,
    pricing_summary: Optional[Dict[str, Any]] = None,
    pricing_room: Optional[Dict[str, Any]] = None,
    forecast_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    scenario_route = scenario_route or {}
    price_state = price_state or {}
    pricing_summary = pricing_summary or {}
    pricing_room = pricing_room or {}
    if isinstance(cross_asset_watch, dict):
        cross_items = cross_asset_watch.get("items", [])
    elif isinstance(cross_asset_watch, list):
        cross_items = cross_asset_watch
    else:
        cross_items = []

    level = "medium" if _alert_level_rank(price_state.get("alert_level", "low")) >= 2 else "low"
    invalidations = []
    if scenario_route.get("route") in {"price_news_resonance", "news_catalyst"}:
        invalidations.append("后续30分钟价格未延续，或更强反向新闻出现")
    if scenario_route.get("route") in {"cross_asset_propagation", "price_dislocation"}:
        invalidations.append("关键参考资产不再同步，联动确认失效")
    if pricing_summary.get("future_bias"):
        invalidations.append(f"若“{pricing_summary.get('future_bias')}”对应主线被快速回吐，则延续判断降级")
    if pricing_room.get("estimated_room_pct", 0) and _safe_float(pricing_room.get("estimated_room_pct", 0)) < 0.2:
        invalidations.append("剩余定价空间偏小，不宜把短线波动直接外推成趋势")
    if not invalidations:
        invalidations.append("若价格回到事件触发前区间且新闻未继续发酵，则本轮判断失效")

    focus_points = []
    if cross_items:
        focus_points.append("继续看跨资产联动是否保持一致")
    if price_state.get("recent_event"):
        focus_points.append("重点跟踪最近一次5分钟事件后的30-120分钟延续")
    if pricing_summary.get("future_bias"):
        focus_points.append(f"留意主线是否仍指向{pricing_summary.get('future_bias')}")
    if not focus_points:
        focus_points.append("等待新的价格确认或直接新闻催化")

    forecast_overlay = build_forecast_risk_overlay(forecast_bundle)
    invalidations.extend(forecast_overlay.get("invalidations", []))
    focus_points.extend(forecast_overlay.get("focus_points", []))

    if _alert_level_rank(price_state.get("alert_level", "low")) >= 3:
        level = "high"
    if forecast_overlay.get("level") == "high":
        level = "high"
    elif forecast_overlay.get("level") == "medium" and level != "high":
        level = "medium"
    summary = f"{scenario_route.get('label', '当前情景')}下，最需要防范的是“{'；'.join(invalidations[:2])}”。"
    if forecast_overlay.get("summary"):
        summary += f" {forecast_overlay.get('summary')}"
    return {
        "level": level,
        "summary": summary,
        "invalidations": invalidations[:3],
        "focus_points": focus_points[:3],
    }


def _build_quick_research_snapshot(
    asset_name: str,
    current_code: str,
    scenario_route: Optional[Dict[str, Any]] = None,
    price_state: Optional[Dict[str, Any]] = None,
    direct_news: Optional[List[Dict[str, Any]]] = None,
    driver_news: Optional[List[Dict[str, Any]]] = None,
    pricing_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    scenario_route = scenario_route or {}
    price_state = price_state or {}
    direct_news = direct_news or []
    driver_news = driver_news or []
    pricing_summary = pricing_summary or {}
    quick_nodes = scenario_route.get("quick_nodes", [])
    quick_node_labels = [_ANALYST_NODE_LABELS.get(node, node) for node in quick_nodes]

    summary_parts = [
        f"{asset_name or current_code or '当前资产'}当前优先走“{scenario_route.get('label', '均衡观察')}”快评路径"
    ]
    if price_state.get("status_label"):
        summary_parts.append(f"价格状态为“{price_state.get('status_label')}”")
    if direct_news:
        summary_parts.append(f"优先核验直接新闻“{direct_news[0].get('title', '未命名新闻')}”")
    elif driver_news:
        summary_parts.append(f"先看驱动线索“{driver_news[0].get('title', '未命名驱动')}”是否继续传导")
    if pricing_summary.get("future_bias"):
        summary_parts.append(f"历史主线目前指向{pricing_summary.get('future_bias')}")

    return {
        "mode": "quick",
        "summary": "；".join(summary_parts) + "。",
        "selected_nodes": quick_nodes,
        "selected_node_labels": quick_node_labels,
        "route_label": scenario_route.get("label", "均衡观察"),
        "trigger": scenario_route.get("trigger", current_code),
    }


def _build_deep_research_plan(
    scenario_route: Optional[Dict[str, Any]] = None,
    selected_nodes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    scenario_route = scenario_route or {}
    selected_nodes = [node for node in (selected_nodes or []) if node]
    deep_nodes = selected_nodes or scenario_route.get("deep_nodes", [])
    deep_node_labels = [_ANALYST_NODE_LABELS.get(node, node) for node in deep_nodes]
    return {
        "mode": "deep",
        "selected_nodes": deep_nodes,
        "selected_node_labels": deep_node_labels,
        "summary": (
            f"深度研究阶段将重点调用：{'、'.join(deep_node_labels) if deep_node_labels else '综合研究节点'}，"
            f"围绕“{scenario_route.get('label', '均衡观察')}”场景完成完整研究。"
        ),
    }


def _build_timesfm_trade_plan(forecast_bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    forecast_bundle = forecast_bundle or {}
    forecast_primary = forecast_bundle.get("forecast_primary", {}) or forecast_bundle.get("forecast_30m", {}) or {}
    forecast_secondary = forecast_bundle.get("forecast_secondary", {}) or forecast_bundle.get("forecast_120m", {}) or {}
    overlay = build_forecast_risk_overlay(forecast_bundle)
    primary_label = forecast_primary.get("horizon_label", "下一周期")
    secondary_label = forecast_secondary.get("horizon_label", "4周期")
    primary_direction = str(forecast_primary.get("direction", "neutral") or "neutral")
    secondary_direction = str(forecast_secondary.get("direction", "neutral") or "neutral")
    primary_probability = _safe_float(forecast_primary.get("continuation_probability"), 0.0)
    secondary_probability = _safe_float(forecast_secondary.get("continuation_probability"), 0.0)
    uncertainty = str(
        forecast_primary.get("uncertainty_level")
        or forecast_secondary.get("uncertainty_level")
        or "high"
    )
    expected_secondary = _safe_float(forecast_secondary.get("expected_return_pct"))
    direction_map = {
        "bullish": ("long", "偏多", "考虑顺势试多"),
        "bearish": ("short", "偏空", "考虑顺势试空"),
        "neutral": ("no_trade", "中性", "先不交易"),
    }

    if not forecast_bundle.get("available"):
        failure_message = str(
            forecast_bundle.get("error_message")
            or ((forecast_bundle.get("backend_details") or {}).get("native_message"))
            or forecast_bundle.get("summary")
            or "TimesFM 当前不可用"
        )
        return {
            "action": "no_trade",
            "action_label": "不交易",
            "bias": "neutral",
            "bias_label": "中性",
            "summary": failure_message,
            "reason": failure_message,
            "execution": "等待模型恢复或使用历史分析与实时关注做人工判断。",
            "holding_window": secondary_label,
            "confidence": "low",
            "no_trade_reason": failure_message,
            "invalidations": [],
            "focus_points": [],
        }

    aligned = primary_direction == secondary_direction and primary_direction in {"bullish", "bearish"}
    action, bias_label, action_label = direction_map.get(primary_direction, direction_map["neutral"])
    reason = (
        f"{primary_label}{'与' + secondary_label if secondary_label else ''}方向一致，"
        f"延续概率分别为{round(primary_probability * 100)}% / {round(secondary_probability * 100)}%。"
    )
    no_trade_reason = ""
    if uncertainty == "high" or max(primary_probability, secondary_probability) < 0.55:
        action = "no_trade"
        action_label = "不交易"
        bias_label = "中性"
        no_trade_reason = "预测不确定性偏高，或延续概率不足，暂不具备稳定交易优势。"
    elif not aligned and primary_direction in {"bullish", "bearish"}:
        action = "watch_long" if primary_direction == "bullish" else "watch_short"
        action_label = "等待确认"
        no_trade_reason = "短周期与长周期方向暂未完全一致，先等价格二次确认。"
    elif aligned and min(primary_probability, secondary_probability) >= 0.62 and uncertainty != "high":
        action = "long" if primary_direction == "bullish" else "short"
        action_label = "可执行"
    else:
        action = "watch_long" if primary_direction == "bullish" else "watch_short" if primary_direction == "bearish" else "no_trade"
        action_label = "轻仓观察" if action != "no_trade" else "不交易"
        if action == "no_trade":
            no_trade_reason = "模型没有给出明确方向。"
        else:
            no_trade_reason = "方向存在但优势不够强，优先观察确认信号。"

    execution = (
        f"仅当价格继续按{primary_label}{'上行' if primary_direction == 'bullish' else '下行' if primary_direction == 'bearish' else '震荡'}延续，"
        f"且{secondary_label}方向不逆转时再考虑执行。"
    )
    if action == "no_trade":
        execution = "先观望，等价格突破或新的直接新闻出现后再评估。"

    return {
        "action": action,
        "action_label": action_label,
        "bias": primary_direction,
        "bias_label": bias_label,
        "summary": (
            f"{action_label}：{primary_label}{'偏上行' if primary_direction == 'bullish' else '偏下行' if primary_direction == 'bearish' else '方向不明'}，"
            f"{secondary_label}预期{expected_secondary:+.3f}% 。"
        ),
        "reason": reason,
        "execution": execution,
        "holding_window": secondary_label,
        "confidence": "high" if min(primary_probability, secondary_probability) >= 0.68 and uncertainty == "low" else "medium" if max(primary_probability, secondary_probability) >= 0.55 else "low",
        "no_trade_reason": no_trade_reason,
        "invalidations": overlay.get("invalidations", [])[:3],
        "focus_points": overlay.get("focus_points", [])[:3],
    }


def _build_daily_summary_trader_brief(
    news_list: List[Dict[str, Any]],
    analyzed_targets: List[str],
    days: int,
) -> Dict[str, Any]:
    sorted_news = sorted(
        news_list or [],
        key=lambda item: (
            _safe_float(item.get("importance_score"), 0.0),
            str(item.get("published_at", "") or ""),
        ),
        reverse=True,
    )
    must_watch_news = [
        {
            "title": item.get("title", "无标题"),
            "published_at": item.get("published_at", ""),
            "source": item.get("source", ""),
            "importance_score": round(_safe_float(item.get("importance_score"), 0.0), 4),
        }
        for item in sorted_news[:3]
    ]
    focus_targets = [str(item) for item in (analyzed_targets or [])[:6] if str(item)]
    action = "wait"
    action_label = "先筛选，后交易"
    summary = (
        f"过去{days}天新闻更适合提炼主线和筛选标的，不建议直接把新闻汇总当成交易信号。"
    )
    execution_rules = [
        "只把这份总结当作主线筛选清单，真正下单前必须切到单资产历史分析或实时关注。",
        "优先处理新闻直接涉及、且价格已有确认的资产；没有价格确认先不做。",
        "每天最多保留 3 个重点资产进入下一轮分析，避免信息过载。",
    ]
    return {
        "action": action,
        "action_label": action_label,
        "summary": summary,
        "focus_targets": focus_targets,
        "must_watch_news": must_watch_news,
        "execution_rules": execution_rules,
    }


def _build_historical_event_trade_templates(
    events: List[Dict[str, Any]],
    pricing_room: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    pricing_room = pricing_room or {}
    templates: List[Dict[str, Any]] = []
    holding_window = "120分钟"
    if pricing_room.get("estimated_room_pct", 0):
        holding_window = "120分钟内观察是否延续"
    for event in (events or [])[:3]:
        direction = str(event.get("direction", "neutral") or "neutral")
        cause_title = ""
        news_details = list(event.get("event_news_details", []) or [])
        if news_details:
            cause_title = news_details[0].get("title", "")
        templates.append(
            {
                "trigger_dt": event.get("trigger_dt").isoformat() if hasattr(event.get("trigger_dt"), "isoformat") else str(event.get("trigger_dt", "")),
                "storyline": event.get("storyline", "综合驱动"),
                "cause_title": cause_title or (event.get("top_news_titles", ["暂无"])[0] if event.get("top_news_titles") else "暂无"),
                "suggested_side": "试多" if direction == "bullish" else "试空" if direction == "bearish" else "观望",
                "holding_window": holding_window,
                "edge_text": (
                    f"事件后30分钟实际{_safe_float(event.get('follow_30m_pct')):+.3f}% ，"
                    f"120分钟实际{_safe_float(event.get('follow_120m_pct')):+.3f}% 。"
                ),
                "invalidation": event.get("absorption_reason", "") or event.get("absorption_status", "absorbed"),
            }
        )
    return templates


def _build_historical_trader_decision(
    events: List[Dict[str, Any]],
    storylines: List[Dict[str, Any]],
    pricing_summary: Optional[Dict[str, Any]] = None,
    pricing_room: Optional[Dict[str, Any]] = None,
    timesfm_forecast: Optional[Dict[str, Any]] = None,
    risk_brief: Optional[Dict[str, Any]] = None,
    lookback_label: str = "24小时",
) -> Dict[str, Any]:
    pricing_summary = pricing_summary or {}
    pricing_room = pricing_room or {}
    risk_brief = risk_brief or {}
    strongest_storyline = storylines[0] if storylines else {}
    top_event = events[0] if events else {}
    timesfm_plan = _build_timesfm_trade_plan(timesfm_forecast or {})
    room = _safe_float(pricing_room.get("estimated_room_pct"), 0.0)
    aligned_samples = int(pricing_room.get("aligned_sample_count", 0) or 0)
    storyline_direction = str(strongest_storyline.get("direction", "中性") or "中性")
    future_bias = str(pricing_summary.get("future_bias", "") or "")

    action = "no_trade"
    action_label = "先不交易"
    action_reason = "当前历史主线优势不够清晰，先观察。"
    if storyline_direction in {"偏利多", "偏利空"} and room >= 0.2 and aligned_samples >= 1:
        desired_bias = "bullish" if storyline_direction == "偏利多" else "bearish"
        if timesfm_plan.get("bias") == desired_bias and timesfm_plan.get("action") in {"long", "short"}:
            action = "long" if desired_bias == "bullish" else "short"
            action_label = "可执行"
            action_reason = "历史主线、剩余定价空间与 TimesFM 方向一致。"
        elif timesfm_plan.get("bias") == desired_bias:
            action = "watch_long" if desired_bias == "bullish" else "watch_short"
            action_label = "等待确认"
            action_reason = "主线方向仍占优，但模型优势不够强，先等价格确认。"
    elif room >= 0.12 and storyline_direction in {"偏利多", "偏利空"}:
        action = "watch_long" if storyline_direction == "偏利多" else "watch_short"
        action_label = "轻仓观察"
        action_reason = "方向有倾向，但历史剩余空间一般，不适合重仓追。"

    driver_summary = str(
        top_event.get("cause_summary")
        or strongest_storyline.get("storyline")
        or "暂无单一主驱动"
    )
    statistical_edge = (
        f"过去{lookback_label}内最强主线为“{strongest_storyline.get('storyline', '暂无')}”，"
        f"方向{storyline_direction}；相似样本{aligned_samples}个，"
        f"历史120分钟均值{_safe_float(pricing_room.get('historical_avg_follow_120m_pct')):+.3f}% ，"
        f"当前剩余空间估算{room:+.3f}% 。"
    )
    execution_rules = [
        f"只围绕“{strongest_storyline.get('storyline', '当前主线')}”做交易，不做无关噪音新闻。",
        f"优先等价格继续确认{future_bias or storyline_direction}，再考虑顺势执行。",
        "若没有新的直接新闻或价格共振，默认观望。",
    ]
    if action == "no_trade":
        execution_rules[1] = "当前不满足历史优势与模型共振条件，默认不交易。"

    supporting_news = [
        {
            "title": item.get("title", "未命名新闻"),
            "impact_label": item.get("impact_label", "中性"),
            "published_at_label": item.get("published_at_label", "--"),
        }
        for item in list(top_event.get("event_news_details", []) or [])[:3]
    ]
    return {
        "action": action,
        "action_label": action_label,
        "summary": f"{action_label}：{action_reason}",
        "driver": driver_summary,
        "statistical_edge": statistical_edge,
        "execution_rules": execution_rules[:3],
        "invalidations": list(risk_brief.get("invalidations", []) or [])[:3],
        "focus_points": list(risk_brief.get("focus_points", []) or [])[:3],
        "supporting_news": supporting_news,
        "timesfm_alignment": timesfm_plan.get("summary", ""),
        "no_trade_reason": timesfm_plan.get("no_trade_reason", "") if action == "no_trade" else "",
    }


def _estimate_timesfm_lookback_hours(frequency: str) -> int:
    return {
        "1m": 6,
        "3m": 8,
        "5m": 12,
        "15m": 36,
        "30m": 72,
        "60m": 120,
        "1h": 120,
        "4h": 720,
        "d": 24 * 240,
    }.get((frequency or "").strip().lower(), 12)


def _normalize_timesfm_frequency(frequency: str) -> str:
    text = str(frequency or "").strip().lower()
    return {
        "1h": "60m",
        "1d": "d",
    }.get(text, text or "5m")


def _timesfm_frequency_label(frequency: str) -> str:
    return {
        "1m": "1分钟",
        "3m": "3分钟",
        "5m": "5分钟",
        "15m": "15分钟",
        "30m": "30分钟",
        "60m": "1小时",
        "1h": "1小时",
        "4h": "4小时",
        "d": "1日",
        "1d": "1日",
    }.get((frequency or "").strip().lower(), str(frequency or "").strip() or "5分钟")


def _format_timesfm_axis_label(value: Any) -> str:
    dt_value = _parse_datetime_like(value)
    if dt_value is None:
        return str(value or "")
    return dt_value.strftime("%m-%d %H:%M")


def _build_timesfm_input_snapshot(
    bars: List[Dict[str, Any]],
    frequency: str,
    covariates: Dict[str, Any],
    context_length: int,
) -> Dict[str, Any]:
    resolved_context_length = max(10, min(int(context_length or 120), len(bars or [])))
    context_bars = list((bars or [])[-resolved_context_length:])
    use_price_covariates = bool((covariates or {}).get("use_price_covariates"))
    latest_close = _safe_float(context_bars[-1].get("close")) if context_bars else 0.0
    first_close = _safe_float(context_bars[0].get("close")) if context_bars else 0.0
    window_change_pct = 0.0
    if abs(first_close) > 1e-9:
        window_change_pct = round((latest_close - first_close) / abs(first_close) * 100, 4)
    data_sources = [f"最近{len(context_bars)}根{_timesfm_frequency_label(frequency)}K线 Close 主序列"]
    if use_price_covariates:
        data_sources.append("同窗口 Open/High/Low/Volume 动态协变量")
    if covariates:
        data_sources.extend(
            [
                "新闻强弱与数量特征",
                "跨资产联动偏置",
                "场景路由偏置",
                "短线价格偏置",
            ]
        )
    return {
        "data_sources": data_sources,
        "model_design": {
            "target_series_field": "close",
            "dynamic_price_covariates_enabled": use_price_covariates,
            "dynamic_price_covariate_fields": ["open", "high", "low", "volume"] if use_price_covariates else [],
        },
        "price_window": {
            "frequency": frequency,
            "frequency_label": _timesfm_frequency_label(frequency),
            "context_length": len(context_bars),
            "window_start": _format_timesfm_axis_label(context_bars[0].get("dt")) if context_bars else "",
            "context_end": _format_timesfm_axis_label(context_bars[-1].get("dt")) if context_bars else "",
            "latest_price": round(latest_close, 6),
            "window_change_pct": window_change_pct,
            "recent_closes": [round(_safe_float(bar.get("close")), 6) for bar in context_bars[-8:]],
            "recent_ohlcv": [
                {
                    "label": _format_timesfm_axis_label(bar.get("dt")),
                    "open": round(_safe_float(bar.get("open")), 6),
                    "high": round(_safe_float(bar.get("high")), 6),
                    "low": round(_safe_float(bar.get("low")), 6),
                    "close": round(_safe_float(bar.get("close")), 6),
                    "volume": round(_safe_float(bar.get("volume")), 2),
                }
                for bar in context_bars[-5:]
            ],
        },
        "covariates": {
            "route": str(covariates.get("route", "") or ""),
            "use_event_covariates": bool(covariates.get("use_event_covariates")),
            "use_price_covariates": use_price_covariates,
            "news_bias_score": round(_safe_float(covariates.get("news_bias_score")), 4),
            "cross_asset_bias": round(_safe_float(covariates.get("cross_asset_bias")), 4),
            "scenario_bias": round(_safe_float(covariates.get("scenario_bias")), 4),
            "price_bias": round(_safe_float(covariates.get("price_bias")), 4),
            "direct_news_count": int(covariates.get("direct_news_count", 0) or 0),
            "driver_news_count": int(covariates.get("driver_news_count", 0) or 0),
        },
    }


def _build_timesfm_visual_chart(
    bars: List[Dict[str, Any]],
    frequency: str,
    forecast_primary: Dict[str, Any],
    forecast_secondary: Dict[str, Any],
) -> Dict[str, Any]:
    context_bars = list(bars[-min(max(len(bars), 20), 36):])
    observed = [
        {
            "label": _format_timesfm_axis_label(bar.get("dt")),
            "price": round(_safe_float(bar.get("close")), 6),
        }
        for bar in context_bars
    ]
    latest_price = _safe_float(context_bars[-1].get("close")) if context_bars else 0.0
    step_minutes = max(_frequency_to_minutes(frequency), 1)

    def _forecast_points(path: List[Any], treat_as_prices: bool = False) -> List[Dict[str, Any]]:
        points: List[Dict[str, Any]] = [{"label": "当前", "price": round(latest_price, 6)}]
        for idx, pct_value in enumerate(path or [], start=1):
            minutes = idx * step_minutes
            if minutes % 1440 == 0:
                label = f"T+{int(minutes / 1440)}d"
            elif minutes % 60 == 0:
                label = f"T+{int(minutes / 60)}h"
            else:
                label = f"T+{minutes}m"
            forecast_price = _safe_float(pct_value) if treat_as_prices else latest_price * (1 + _safe_float(pct_value) / 100.0)
            points.append({"label": label, "price": round(forecast_price, 6)})
        return points

    def _quantile_band_points(forecast: Dict[str, Any], quantile_key: str) -> List[Dict[str, Any]]:
        price_paths = forecast.get("quantile_forecast_price_path", {}) or {}
        pct_paths = forecast.get("quantile_forecast_pct_path", {}) or {}
        if quantile_key in price_paths:
            return _forecast_points(price_paths.get(quantile_key, []), treat_as_prices=True)
        return _forecast_points(pct_paths.get(quantile_key, []), treat_as_prices=False)

    return {
        "frequency": frequency,
        "frequency_label": _timesfm_frequency_label(frequency),
        "observed": observed,
        "forecast_primary": _forecast_points(
            forecast_primary.get("point_forecast_price_path", []) or forecast_primary.get("point_forecast_pct_path", []),
            treat_as_prices=bool(forecast_primary.get("point_forecast_price_path")),
        ),
        "forecast_secondary": _forecast_points(
            forecast_secondary.get("point_forecast_price_path", []) or forecast_secondary.get("point_forecast_pct_path", []),
            treat_as_prices=bool(forecast_secondary.get("point_forecast_price_path")),
        ),
        "forecast_primary_band": {
            "p10": _quantile_band_points(forecast_primary, "p10"),
            "p90": _quantile_band_points(forecast_primary, "p90"),
        },
        "forecast_secondary_band": {
            "p10": _quantile_band_points(forecast_secondary, "p10"),
            "p90": _quantile_band_points(forecast_secondary, "p90"),
        },
        "forecast_30m": _forecast_points(forecast_primary.get("point_forecast_pct_path", [])),
        "forecast_120m": _forecast_points(forecast_secondary.get("point_forecast_pct_path", [])),
    }


def _build_timesfm_forecast(
    current_market: str,
    current_code: str,
    frequency: str = "30m",
    context_length: Optional[int] = None,
    price_bars: Optional[List[Dict[str, Any]]] = None,
    price_state: Optional[Dict[str, Any]] = None,
    direct_news: Optional[List[Dict[str, Any]]] = None,
    driver_news: Optional[List[Dict[str, Any]]] = None,
    cross_asset_watch: Optional[Any] = None,
    scenario_route: Optional[Dict[str, Any]] = None,
    pricing_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    current_market = (current_market or "").strip()
    current_code = (current_code or "").strip().upper()
    normalized_frequency = _normalize_timesfm_frequency(frequency)
    if not current_market or not current_code:
        return {
            "available": False,
            "degraded": False,
            "backend": "timesfm_native_unavailable",
            "degrade_message": "",
            "error_message": "缺少资产信息，暂无法生成预测",
            "summary": "缺少资产信息，暂无法生成预测。",
            "backend_details": {
                "native_enabled": False,
                "native_message": "缺少资产信息，暂无法生成预测",
                "xreg_used": False,
            },
        }

    bars = price_bars
    if bars is None:
        bars = _load_historical_price_bars(
            market=current_market,
            code=current_code,
            frequency=normalized_frequency,
            lookback_hours=_estimate_timesfm_lookback_hours(normalized_frequency),
            purpose="TimesFM预测",
        )
    if len(bars or []) < 10:
        return {
            "available": False,
            "degraded": False,
            "backend": "timesfm_native_unavailable",
            "degrade_message": "",
            "error_message": "价格上下文不足，暂无法生成预测",
            "summary": "价格上下文不足，暂无法生成预测。",
            "backend_details": {
                "native_enabled": False,
                "native_message": "价格上下文不足，暂无法生成预测",
                "xreg_used": False,
            },
        }

    resolved_context_length = max(10, min(int(context_length or 120), len(bars)))
    mode_results: List[Dict[str, Any]] = []
    for mode_definition in _timesfm_forecast_mode_definitions(
        price_state=price_state,
        direct_news=direct_news,
        driver_news=driver_news,
        cross_asset_watch=cross_asset_watch,
        scenario_route=scenario_route,
        pricing_summary=pricing_summary,
    ):
        mode_covariates = mode_definition.get("covariates", {}) or {}
        bundle = generate_timesfm_forecast_bundle(
            price_bars=bars,
            market=current_market,
            code=current_code,
            frequency=normalized_frequency,
            horizons=[1, 4],
            context_length=resolved_context_length,
            covariates=mode_covariates,
        )
        bundle["forecast_mode"] = mode_definition.get("key", "")
        bundle["forecast_mode_label"] = mode_definition.get("label", "")
        bundle["forecast_mode_description"] = mode_definition.get("description", "")
        bundle["covariates"] = mode_covariates
        bundle["context_length_requested"] = int(context_length or 0)
        bundle["context_length_used"] = resolved_context_length
        bundle["input_snapshot"] = _build_timesfm_input_snapshot(
            bars,
            normalized_frequency,
            mode_covariates,
            resolved_context_length,
        )
        bundle["visual_chart"] = _build_timesfm_visual_chart(
            bars,
            normalized_frequency,
            bundle.get("forecast_primary", {}) or bundle.get("forecast_30m", {}) or {},
            bundle.get("forecast_secondary", {}) or bundle.get("forecast_120m", {}) or {},
        )
        bundle["asset"] = {
            "market": current_market,
            "code": current_code,
        }
        bundle["mode_score"] = _forecast_mode_confidence_score(bundle) if bundle.get("available") else None
        mode_results.append(bundle)
    available_modes = [item for item in mode_results if item.get("available")]
    selected_mode = sorted(
        available_modes or mode_results,
        key=lambda item: (
            -_safe_float(item.get("mode_score")),
            -_safe_float(((item.get("forecast_secondary") or {}).get("continuation_probability"))),
            -_safe_float(((item.get("forecast_primary") or {}).get("continuation_probability"))),
        ),
    )[0]
    mode_comparison = []
    for item in mode_results:
        primary = item.get("forecast_primary", {}) or item.get("forecast_30m", {}) or {}
        secondary = item.get("forecast_secondary", {}) or item.get("forecast_120m", {}) or {}
        mode_comparison.append(
            {
                "mode_key": item.get("forecast_mode", ""),
                "mode_label": item.get("forecast_mode_label", ""),
                "mode_description": item.get("forecast_mode_description", ""),
                "available": bool(item.get("available")),
                "backend": item.get("backend", ""),
                "mode_score": item.get("mode_score"),
                "xreg_used": bool(((item.get("backend_details") or {}).get("xreg_used"))),
                "context_length_used": int(item.get("context_length_used", 0) or 0),
                "primary_direction": primary.get("direction"),
                "primary_continuation_probability": primary.get("continuation_probability"),
                "primary_confidence": primary.get("forecast_confidence"),
                "primary_uncertainty": primary.get("uncertainty_level"),
                "secondary_direction": secondary.get("direction"),
                "secondary_continuation_probability": secondary.get("continuation_probability"),
                "secondary_confidence": secondary.get("forecast_confidence"),
                "secondary_uncertainty": secondary.get("uncertainty_level"),
                "error_message": item.get("error_message", ""),
            }
        )
    summary_prefix = (
        f"当前主模式为{selected_mode.get('forecast_mode_label', '纯价格')}，"
        if selected_mode.get("forecast_mode_label")
        else ""
    )
    result = {
        **selected_mode,
        "summary": summary_prefix + str(selected_mode.get("summary", "") or ""),
        "selected_forecast_mode": selected_mode.get("forecast_mode", ""),
        "selected_forecast_mode_label": selected_mode.get("forecast_mode_label", ""),
        "selected_forecast_mode_description": selected_mode.get("forecast_mode_description", ""),
        "forecast_mode_results": mode_results,
        "mode_comparison": mode_comparison,
    }
    result["trade_plan"] = _build_timesfm_trade_plan(result)
    return result


def _timesfm_forecast_mode_definitions(
    price_state: Optional[Dict[str, Any]] = None,
    direct_news: Optional[List[Dict[str, Any]]] = None,
    driver_news: Optional[List[Dict[str, Any]]] = None,
    cross_asset_watch: Optional[Any] = None,
    scenario_route: Optional[Dict[str, Any]] = None,
    pricing_summary: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    enhanced_covariates = build_timesfm_covariates(
        price_state=price_state,
        direct_news=direct_news,
        driver_news=driver_news,
        cross_asset_watch=cross_asset_watch,
        scenario_route=scenario_route,
        pricing_summary=pricing_summary,
    )
    return [
        {
            "key": "pure_price",
            "label": "纯价格",
            "description": "只使用历史 Close 序列做原生预测，不注入 OHLCV、新闻、场景和价格状态协变量。",
            "covariates": {},
        },
        {
            "key": "price_event_covariates",
            "label": "价格+协变量",
            "description": "以 Close 为目标序列，并把 OHLCV、价格状态、新闻和场景特征作为动态协变量输入 TimesFM 2.5。",
            "covariates": enhanced_covariates,
        },
    ]


def _forecast_mode_confidence_score(bundle: Dict[str, Any]) -> float:
    primary = bundle.get("forecast_primary", {}) or bundle.get("forecast_30m", {}) or {}
    secondary = bundle.get("forecast_secondary", {}) or bundle.get("forecast_120m", {}) or {}
    confidence_weight = {
        "high": 1.0,
        "medium": 0.72,
        "low": 0.45,
    }
    uncertainty_penalty = {
        "low": 0.08,
        "medium": 0.18,
        "high": 0.3,
    }
    primary_conf = confidence_weight.get(str(primary.get("forecast_confidence", "") or "medium"), 0.72)
    secondary_conf = confidence_weight.get(str(secondary.get("forecast_confidence", "") or "medium"), 0.72)
    primary_cont = _safe_float(primary.get("continuation_probability"), 0.5)
    secondary_cont = _safe_float(secondary.get("continuation_probability"), 0.5)
    primary_penalty = uncertainty_penalty.get(str(primary.get("uncertainty_level", "") or "medium"), 0.18)
    secondary_penalty = uncertainty_penalty.get(str(secondary.get("uncertainty_level", "") or "medium"), 0.18)
    score = (
        primary_conf * 0.28
        + secondary_conf * 0.26
        + primary_cont * 0.24
        + secondary_cont * 0.22
        - primary_penalty * 0.4
        - secondary_penalty * 0.6
    )
    if (bundle.get("backend_details") or {}).get("xreg_used"):
        score += 0.03
    return round(score, 4)


def _normalize_timesfm_request(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = data or {}
    current_market = str(data.get("current_market", "") or "").strip()
    current_code = str(data.get("current_code", "") or "").strip().upper()
    frequency = _normalize_timesfm_frequency(str(data.get("frequency", "30m") or "30m").strip().lower())
    context_length = int(data.get("context_length", 120) or 120)
    return {
        "current_market": current_market,
        "current_code": current_code,
        "frequency": frequency,
        "context_length": max(10, min(context_length, 240)),
    }


def _generate_timesfm_forecast_payload(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    params = _normalize_timesfm_request(data)
    if not params["current_market"] or not params["current_code"]:
        raise ValueError("缺少市场或标的代码")
    cache_payload = dict(params)
    cached_result = _load_summary_result_cache("timesfm_forecast", cache_payload)
    if cached_result:
        return cached_result

    price_bars = _load_historical_price_bars(
        market=params["current_market"],
        code=params["current_code"],
        frequency=params["frequency"],
        lookback_hours=_estimate_timesfm_lookback_hours(params["frequency"]),
        purpose="TimesFM预测接口",
    )
    forecast = _build_timesfm_forecast(
        current_market=params["current_market"],
        current_code=params["current_code"],
        frequency=params["frequency"],
        context_length=params["context_length"],
        price_bars=price_bars,
    )
    result = {
        **forecast,
        "current_market": params["current_market"],
        "current_code": params["current_code"],
        "frequency": params["frequency"],
        "cache_hit": False,
    }
    _save_summary_result_cache("timesfm_forecast", cache_payload, result)
    return result


def _generate_timesfm_event_forecast_payload(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = data or {}
    params = _normalize_timesfm_request(data)
    if not params["current_market"] or not params["current_code"]:
        raise ValueError("缺少市场或标的代码")
    event_time = data.get("event_time")
    if not event_time:
        raise ValueError("缺少事件时间")
    actual_follow_30m_pct = _safe_float(data.get("actual_follow_30m_pct", 0.0))
    actual_follow_120m_pct = _safe_float(data.get("actual_follow_120m_pct", 0.0))
    cache_payload = {
        **params,
        "event_time": str(event_time),
        "actual_follow_30m_pct": actual_follow_30m_pct,
        "actual_follow_120m_pct": actual_follow_120m_pct,
    }
    cached_result = _load_summary_result_cache("timesfm_event_forecast", cache_payload)
    if cached_result:
        return cached_result

    price_bars = _load_historical_price_bars(
        market=params["current_market"],
        code=params["current_code"],
        frequency=params["frequency"],
        lookback_hours=_estimate_timesfm_lookback_hours(params["frequency"]),
        purpose="TimesFM事件预测接口",
    )
    event_forecast = build_event_forecast(
        price_bars=price_bars,
        market=params["current_market"],
        code=params["current_code"],
        frequency=params["frequency"],
        event_time=event_time,
        actual_follow_30m_pct=actual_follow_30m_pct,
        actual_follow_120m_pct=actual_follow_120m_pct,
        context_length=params["context_length"],
    )
    result = {
        **event_forecast,
        "current_market": params["current_market"],
        "current_code": params["current_code"],
        "frequency": params["frequency"],
        "cache_hit": False,
    }
    _save_summary_result_cache("timesfm_event_forecast", cache_payload, result)
    return result


def _sign_label(
    value: Any,
    threshold: Optional[float] = None,
    frequency: str = "5m",
    horizon_bars: int = 1,
) -> str:
    _ = threshold, frequency, horizon_bars
    numeric = _safe_float(value)
    if numeric > 0:
        return "bullish"
    if numeric < 0:
        return "bearish"
    return "neutral"


def _direction_hit(forecast_direction: str, actual_direction: str) -> int:
    return 1 if forecast_direction == actual_direction else 0


def _neutral_match(forecast_direction: str, actual_direction: str) -> int:
    return 1 if forecast_direction == "neutral" and actual_direction == "neutral" else 0


def _build_review_horizon_meta(frequency: str) -> Dict[str, Any]:
    normalized_frequency = _normalize_timesfm_frequency(frequency)
    minute_value = max(_frequency_to_minutes(normalized_frequency), 1)

    def _label_for_bars(horizon_bars: int) -> str:
        total_minutes = minute_value * horizon_bars
        if total_minutes % 1440 == 0:
            return f"{int(total_minutes / 1440)}日"
        if total_minutes % 60 == 0:
            return f"{int(total_minutes / 60)}小时"
        return f"{total_minutes}分钟"

    return {
        "normalized_frequency": normalized_frequency,
        "primary_horizon_bars": 1,
        "secondary_horizon_bars": 4,
        "primary_label": _label_for_bars(1),
        "secondary_label": _label_for_bars(4),
    }


def _compute_forward_return_pct(price_bars: List[Dict[str, Any]], start_index: int, horizon_bars: int) -> float:
    if not price_bars:
        return 0.0
    safe_index = max(0, min(start_index, len(price_bars) - 1))
    end_index = min(len(price_bars) - 1, safe_index + max(int(horizon_bars or 1), 1))
    start_price = _safe_float(price_bars[safe_index].get("close"))
    end_price = _safe_float(price_bars[end_index].get("close"))
    if abs(start_price) <= 1e-9:
        return 0.0
    return round(((end_price - start_price) / abs(start_price)) * 100, 4)


def _empty_review_stats(primary_label: str, secondary_label: str) -> Dict[str, Any]:
    return {
        "primary_label": primary_label,
        "secondary_label": secondary_label,
        "sample_size": 0,
        "sample_quality": "low",
        "sample_quality_label": "样本不足",
        "reliability_score": None,
        "reliability_label": "待观察",
        "stability_score": None,
        "direction_hit_rate_primary": None,
        "direction_hit_rate_secondary": None,
        "neutral_match_rate_primary": None,
        "neutral_match_rate_secondary": None,
        "mae_primary_pct": None,
        "mae_secondary_pct": None,
        "direction_hit_rate_30m": None,
        "direction_hit_rate_120m": None,
        "mae_30m_pct": None,
        "mae_120m_pct": None,
        "avg_surprise_score": None,
        "group_breakdown": {},
        "surprise_breakdown": {},
        "notes": [],
    }


def _build_review_group_metrics(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not events:
        return {
            "count": 0,
            "hit_rate_primary": None,
            "hit_rate_secondary": None,
            "mae_primary_pct": None,
            "mae_secondary_pct": None,
        }
    primary_hits = [
        _direction_hit(
            str(item.get("forecast_direction_primary", "") or ""),
            str(item.get("actual_direction_primary", "") or ""),
        )
        for item in events
    ]
    secondary_hits = [
        _direction_hit(
            str(item.get("forecast_direction_secondary", "") or ""),
            str(item.get("actual_direction_secondary", "") or ""),
        )
        for item in events
    ]
    mae_primary = sum(abs(_safe_float(item.get("forecast_error_primary_pct"))) for item in events) / len(events)
    mae_secondary = sum(abs(_safe_float(item.get("forecast_error_secondary_pct"))) for item in events) / len(events)
    return {
        "count": len(events),
        "hit_rate_primary": round(sum(primary_hits) / len(primary_hits), 4),
        "hit_rate_secondary": round(sum(secondary_hits) / len(secondary_hits), 4),
        "mae_primary_pct": round(mae_primary, 4),
        "mae_secondary_pct": round(mae_secondary, 4),
    }


def _build_review_research_stats(
    review_events: List[Dict[str, Any]],
    primary_label: str,
    secondary_label: str,
) -> Dict[str, Any]:
    if not review_events:
        return _empty_review_stats(primary_label, secondary_label)

    hit_primary = [
        _direction_hit(item["forecast_direction_primary"], item["actual_direction_primary"])
        for item in review_events
    ]
    hit_secondary = [
        _direction_hit(item["forecast_direction_secondary"], item["actual_direction_secondary"])
        for item in review_events
    ]
    neutral_match_primary = [
        _neutral_match(item["forecast_direction_primary"], item["actual_direction_primary"])
        for item in review_events
    ]
    neutral_match_secondary = [
        _neutral_match(item["forecast_direction_secondary"], item["actual_direction_secondary"])
        for item in review_events
    ]
    mae_primary = sum(abs(item["forecast_error_primary_pct"]) for item in review_events) / len(review_events)
    mae_secondary = sum(abs(item["forecast_error_secondary_pct"]) for item in review_events) / len(review_events)
    avg_surprise = sum(item["surprise_score"] for item in review_events) / len(review_events)
    hit_rate_primary = round(sum(hit_primary) / len(hit_primary), 4)
    hit_rate_secondary = round(sum(hit_secondary) / len(hit_secondary), 4)
    neutral_match_rate_primary = round(sum(neutral_match_primary) / len(neutral_match_primary), 4)
    neutral_match_rate_secondary = round(sum(neutral_match_secondary) / len(neutral_match_secondary), 4)
    sample_size = len(review_events)

    if sample_size >= 12:
        sample_quality = "high"
        sample_quality_label = "样本较充分"
    elif sample_size >= 6:
        sample_quality = "medium"
        sample_quality_label = "样本一般"
    else:
        sample_quality = "low"
        sample_quality_label = "样本偏少"

    stability_score = round(max(0.0, 1.0 - abs(hit_rate_primary - hit_rate_secondary)), 4)
    reliability_raw = (
        hit_rate_primary * 0.42
        + hit_rate_secondary * 0.28
        + stability_score * 0.15
        + max(0.0, 1.0 - min(mae_primary / 1.5, 1.0)) * 0.1
        + max(0.0, 1.0 - min(avg_surprise / 1.2, 1.0)) * 0.05
    )
    sample_weight = min(sample_size / 10.0, 1.0)
    reliability_score = round(min(1.0, reliability_raw) * sample_weight, 4)
    if reliability_score >= 0.72:
        reliability_label = "较可靠"
    elif reliability_score >= 0.5:
        reliability_label = "可参考"
    else:
        reliability_label = "谨慎参考"

    bullish_events = [item for item in review_events if _safe_float(item.get("initial_move_pct")) >= 0]
    bearish_events = [item for item in review_events if _safe_float(item.get("initial_move_pct")) < 0]
    surprise_breakdown = {
        "low": len([item for item in review_events if _safe_float(item.get("surprise_score")) < 0.2]),
        "medium": len([item for item in review_events if 0.2 <= _safe_float(item.get("surprise_score")) < 0.45]),
        "high": len([item for item in review_events if _safe_float(item.get("surprise_score")) >= 0.45]),
    }

    notes: List[str] = []
    if sample_quality == "low":
        notes.append("样本偏少，统计结果易受单次事件影响")
    if neutral_match_rate_primary >= 0.4:
        notes.append(f"{primary_label}较多样本接近持平，已按涨跌方向是否一致统计命中率")
    if hit_rate_primary < 0.55:
        notes.append(f"{primary_label}方向命中率偏低，短周期可交易性不足")
    if hit_rate_secondary < 0.55:
        notes.append(f"{secondary_label}方向延续不稳定，不能直接外推中周期趋势")
    if avg_surprise >= 0.45:
        notes.append("事件后真实路径波动较大，模型对冲击后的再定价适应一般")
    if stability_score < 0.7:
        notes.append("短中周期表现分化明显，说明方法稳定性仍不足")
    if not notes:
        notes.append("当前样本下方法具备一定稳定性，可作为研究辅助信号")

    return {
        "primary_label": primary_label,
        "secondary_label": secondary_label,
        "sample_size": sample_size,
        "sample_quality": sample_quality,
        "sample_quality_label": sample_quality_label,
        "reliability_score": reliability_score,
        "reliability_label": reliability_label,
        "stability_score": stability_score,
        "direction_hit_rate_primary": hit_rate_primary,
        "direction_hit_rate_secondary": hit_rate_secondary,
        "neutral_match_rate_primary": neutral_match_rate_primary,
        "neutral_match_rate_secondary": neutral_match_rate_secondary,
        "mae_primary_pct": round(mae_primary, 4),
        "mae_secondary_pct": round(mae_secondary, 4),
        "direction_hit_rate_30m": hit_rate_primary,
        "direction_hit_rate_120m": hit_rate_secondary,
        "mae_30m_pct": round(mae_primary, 4),
        "mae_120m_pct": round(mae_secondary, 4),
        "avg_surprise_score": round(avg_surprise, 4),
        "group_breakdown": {
            "bullish": _build_review_group_metrics(bullish_events),
            "bearish": _build_review_group_metrics(bearish_events),
        },
        "surprise_breakdown": surprise_breakdown,
        "notes": notes[:4],
    }


def _safe_json_loads(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _build_timesfm_review_metadata(result: Dict[str, Any], params: Dict[str, Any]) -> str:
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [_json_safe(item) for item in value]
        if hasattr(value, "isoformat") and callable(getattr(value, "isoformat")):
            try:
                return value.isoformat()
            except Exception:
                return str(value)
        return value

    payload = {
        "schema": "timesfm_review_v1",
        "event_frequency": params.get("event_frequency"),
        "lookback_hours": params.get("lookback_hours"),
        "generated_at": datetime.now().isoformat(),
        "timesfm_forecast": result.get("timesfm_forecast", {}),
        "events": result.get("events", []),
        "pricing_summary": result.get("pricing_summary", {}),
        "pricing_room": result.get("pricing_room", {}),
    }
    return json.dumps(_json_safe(payload), ensure_ascii=False)


def _build_review_event_covariates(event: Dict[str, Any]) -> Dict[str, Any]:
    return build_timesfm_covariates(
        price_state={
            "change_30m_pct": _safe_float(event.get("return_pct")),
        },
        scenario_route={
            "route": "historical_followthrough",
        },
    )


def _build_review_event_price_table(
    price_bars: List[Dict[str, Any]],
    event_index: int,
    review_horizon: Dict[str, Any],
    event_forecast: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not price_bars:
        return []
    safe_index = max(0, min(int(event_index or 0), len(price_bars) - 1))
    context_slice = price_bars[max(0, safe_index - 7): safe_index + 1]
    primary_path = list(((event_forecast.get("forecast_primary") or {}).get("point_forecast_price_path", [])) or [])
    secondary_path = list(((event_forecast.get("forecast_secondary") or {}).get("point_forecast_price_path", [])) or [])
    rows: List[Dict[str, Any]] = []
    for bar in context_slice:
        dt_value = bar.get("dt") or bar.get("datetime") or bar.get("time")
        close_value = round(_safe_float(bar.get("close")), 6)
        rows.append(
            {
                "stage": "history",
                "label": "历史",
                "time": _format_timesfm_axis_label(dt_value),
                "historical_price": close_value,
                "predicted_price": None,
                "actual_price": close_value,
            }
        )
    for step in range(1, int(review_horizon.get("secondary_horizon_bars", 4) or 4) + 1):
        future_index = min(len(price_bars) - 1, safe_index + step)
        future_bar = price_bars[future_index]
        dt_value = future_bar.get("dt") or future_bar.get("datetime") or future_bar.get("time")
        if step == 1 and primary_path:
            predicted_price = round(_safe_float(primary_path[0]), 6)
        elif len(secondary_path) >= step:
            predicted_price = round(_safe_float(secondary_path[step - 1]), 6)
        else:
            predicted_price = None
        rows.append(
            {
                "stage": "future",
                "label": review_horizon.get("primary_label") if step == 1 else f"+{step}步",
                "time": _format_timesfm_axis_label(dt_value),
                "historical_price": None,
                "predicted_price": predicted_price,
                "actual_price": round(_safe_float(future_bar.get("close")), 6),
            }
        )
    return rows


def _timesfm_review_mode_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "key": "pure_price",
            "label": "纯价格",
            "description": "只使用事件触发前的历史价格上下文，不注入事件派生协变量。",
            "covariates_builder": lambda event: {},
        },
        {
            "key": "price_event_covariates",
            "label": "价格+事件协变量",
            "description": "使用历史价格上下文，并注入事件触发时点可观测的价格状态协变量。",
            "covariates_builder": _build_review_event_covariates,
        },
    ]


def _build_timesfm_context_candidates(frequency: str, available_bars: int, requested_context_length: int = 0) -> List[int]:
    if requested_context_length > 0:
        return [max(10, min(int(requested_context_length), max(int(available_bars or 0), 10), 240))]
    normalized_frequency = _normalize_timesfm_frequency(frequency)
    candidate_map = {
        "1m": [64, 128, 192, 240],
        "3m": [64, 96, 144, 192],
        "5m": [48, 96, 144, 192],
        "15m": [32, 64, 96, 128],
        "30m": [32, 48, 64, 96],
        "60m": [24, 48, 72, 96],
        "4h": [16, 24, 32, 48],
        "d": [16, 24, 32, 48],
    }
    filtered = [
        max(10, min(int(item), max(int(available_bars or 0), 10), 240))
        for item in candidate_map.get(normalized_frequency, [48, 96, 144, 192])
    ]
    deduped: List[int] = []
    for item in filtered:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _score_timesfm_context_result(stats: Dict[str, Any]) -> float:
    hit_primary = _safe_float(stats.get("direction_hit_rate_primary"))
    hit_secondary = _safe_float(stats.get("direction_hit_rate_secondary"))
    mae_primary = _safe_float(stats.get("mae_primary_pct"))
    mae_secondary = _safe_float(stats.get("mae_secondary_pct"))
    reliability = _safe_float(stats.get("reliability_score"))
    return round(
        hit_secondary * 0.35
        + hit_primary * 0.25
        + max(0.0, 1.0 - min(mae_secondary / 0.6, 1.0)) * 0.2
        + max(0.0, 1.0 - min(mae_primary / 0.35, 1.0)) * 0.1
        + reliability * 0.1,
        4,
    )


def _evaluate_timesfm_context_lengths(
    price_bars: List[Dict[str, Any]],
    current_market: str,
    current_code: str,
    frequency: str,
    sampled_events: List[Dict[str, Any]],
    bar_index_map: Dict[str, int],
    review_horizon: Dict[str, Any],
    requested_context_length: int = 0,
    covariates_builder: Optional[Any] = None,
) -> Dict[str, Any]:
    candidate_lengths = _build_timesfm_context_candidates(
        frequency=frequency,
        available_bars=len(price_bars),
        requested_context_length=requested_context_length,
    )
    primary_label = review_horizon["primary_label"]
    secondary_label = review_horizon["secondary_label"]
    benchmark_events = list(sampled_events[: min(len(sampled_events), 6)])
    evaluations: List[Dict[str, Any]] = []
    recommended_context_length = candidate_lengths[0] if candidate_lengths else max(10, min(len(price_bars), 120))

    for context_length in candidate_lengths:
        review_events: List[Dict[str, Any]] = []
        for event in benchmark_events:
            trigger_dt = event.get("trigger_dt")
            trigger_key = trigger_dt.isoformat() if hasattr(trigger_dt, "isoformat") else str(trigger_dt or "")
            event_index = bar_index_map.get(trigger_key)
            if event_index is None:
                continue
            actual_primary = _compute_forward_return_pct(
                price_bars,
                event_index,
                review_horizon["primary_horizon_bars"],
            )
            actual_secondary = _compute_forward_return_pct(
                price_bars,
                event_index,
                review_horizon["secondary_horizon_bars"],
            )
            event_forecast = build_event_forecast(
                price_bars=price_bars,
                market=current_market,
                code=current_code,
                frequency=frequency,
                event_time=trigger_dt,
                actual_follow_primary_pct=actual_primary,
                actual_follow_secondary_pct=actual_secondary,
                primary_horizon_bars=review_horizon["primary_horizon_bars"],
                secondary_horizon_bars=review_horizon["secondary_horizon_bars"],
                covariates=(covariates_builder(event) if callable(covariates_builder) else {}),
                context_length=context_length,
            )
            if not event_forecast.get("available"):
                continue
            forecast_primary = event_forecast.get("forecast_primary", {}) or event_forecast.get("forecast_30m", {}) or {}
            forecast_secondary = event_forecast.get("forecast_secondary", {}) or event_forecast.get("forecast_120m", {}) or {}
            expected_primary = _safe_float(forecast_primary.get("expected_return_pct"))
            expected_secondary = _safe_float(forecast_secondary.get("expected_return_pct"))
            review_events.append(
                {
                    "direction": event.get("direction", "neutral"),
                    "initial_move_pct": round(_safe_float(event.get("return_pct")), 4),
                    "forecast_direction_primary": _sign_label(
                        expected_primary,
                        frequency=frequency,
                        horizon_bars=review_horizon["primary_horizon_bars"],
                    ),
                    "actual_direction_primary": _sign_label(
                        actual_primary,
                        frequency=frequency,
                        horizon_bars=review_horizon["primary_horizon_bars"],
                    ),
                    "forecast_direction_secondary": _sign_label(
                        expected_secondary,
                        frequency=frequency,
                        horizon_bars=review_horizon["secondary_horizon_bars"],
                    ),
                    "actual_direction_secondary": _sign_label(
                        actual_secondary,
                        frequency=frequency,
                        horizon_bars=review_horizon["secondary_horizon_bars"],
                    ),
                    "expected_primary_pct": round(expected_primary, 4),
                    "actual_primary_pct": round(actual_primary, 4),
                    "expected_secondary_pct": round(expected_secondary, 4),
                    "actual_secondary_pct": round(actual_secondary, 4),
                    "forecast_error_primary_pct": round(actual_primary - expected_primary, 4),
                    "forecast_error_secondary_pct": round(actual_secondary - expected_secondary, 4),
                    "surprise_score": round(_safe_float(event_forecast.get("surprise_score")), 4),
                }
            )
        stats = _build_review_research_stats(review_events, primary_label, secondary_label)
        score = _score_timesfm_context_result(stats)
        evaluations.append(
            {
                "context_length": context_length,
                "sample_size": len(review_events),
                "direction_hit_rate_primary": stats.get("direction_hit_rate_primary"),
                "direction_hit_rate_secondary": stats.get("direction_hit_rate_secondary"),
                "mae_primary_pct": stats.get("mae_primary_pct"),
                "mae_secondary_pct": stats.get("mae_secondary_pct"),
                "reliability_score": stats.get("reliability_score"),
                "reliability_label": stats.get("reliability_label"),
                "score": score,
            }
        )

    if evaluations:
        best = sorted(
            evaluations,
            key=lambda item: (
                -_safe_float(item.get("score")),
                -_safe_float(item.get("direction_hit_rate_secondary")),
                _safe_float(item.get("mae_secondary_pct"), 999.0),
                -_safe_float(item.get("sample_size")),
            ),
        )[0]
        recommended_context_length = int(best.get("context_length") or recommended_context_length)
    else:
        best = {
            "context_length": recommended_context_length,
            "sample_size": 0,
            "score": 0.0,
            "reliability_label": "待观察",
        }

    return {
        "requested_context_length": int(requested_context_length or 0),
        "recommended_context_length": recommended_context_length,
        "recommended_score": _safe_float(best.get("score")),
        "recommended_reliability_label": str(best.get("reliability_label", "待观察") or "待观察"),
        "evaluations": evaluations,
    }


def _run_timesfm_review_mode(
    mode_definition: Dict[str, Any],
    price_bars: List[Dict[str, Any]],
    current_market: str,
    current_code: str,
    normalized_frequency: str,
    frequency_label: str,
    review_days: int,
    sampled_events: List[Dict[str, Any]],
    bar_index_map: Dict[str, int],
    review_horizon: Dict[str, Any],
    requested_context_length: int,
    max_items: int,
) -> Dict[str, Any]:
    mode_key = str(mode_definition.get("key", "") or "")
    mode_label = str(mode_definition.get("label", "") or mode_key)
    covariates_builder = mode_definition.get("covariates_builder")
    primary_label = review_horizon["primary_label"]
    secondary_label = review_horizon["secondary_label"]

    context_evaluation = _evaluate_timesfm_context_lengths(
        price_bars=price_bars,
        current_market=current_market,
        current_code=current_code,
        frequency=normalized_frequency,
        sampled_events=sampled_events,
        bar_index_map=bar_index_map,
        review_horizon=review_horizon,
        requested_context_length=requested_context_length,
        covariates_builder=covariates_builder,
    )
    resolved_context_length = max(
        10,
        min(
            int(context_evaluation.get("recommended_context_length") or requested_context_length or 120),
            len(price_bars),
            240,
        ),
    )

    review_events: List[Dict[str, Any]] = []
    review_failure_reasons: List[str] = []
    for event in sampled_events:
        trigger_dt = event.get("trigger_dt")
        trigger_key = trigger_dt.isoformat() if hasattr(trigger_dt, "isoformat") else str(trigger_dt or "")
        event_index = bar_index_map.get(trigger_key)
        if event_index is None:
            continue
        actual_primary = _compute_forward_return_pct(
            price_bars,
            event_index,
            review_horizon["primary_horizon_bars"],
        )
        actual_secondary = _compute_forward_return_pct(
            price_bars,
            event_index,
            review_horizon["secondary_horizon_bars"],
        )
        event_forecast = build_event_forecast(
            price_bars=price_bars,
            market=current_market,
            code=current_code,
            frequency=normalized_frequency,
            event_time=trigger_dt,
            actual_follow_primary_pct=actual_primary,
            actual_follow_secondary_pct=actual_secondary,
            primary_horizon_bars=review_horizon["primary_horizon_bars"],
            secondary_horizon_bars=review_horizon["secondary_horizon_bars"],
            covariates=(covariates_builder(event) if callable(covariates_builder) else {}),
            context_length=resolved_context_length,
        )
        if not event_forecast.get("available"):
            failure_message = str(
                event_forecast.get("error_message")
                or ((event_forecast.get("backend_details") or {}).get("native_message"))
                or event_forecast.get("summary")
                or ""
            ).strip()
            if failure_message:
                review_failure_reasons.append(failure_message)
            continue
        forecast_primary = event_forecast.get("forecast_primary", {}) or event_forecast.get("forecast_30m", {}) or {}
        forecast_secondary = event_forecast.get("forecast_secondary", {}) or event_forecast.get("forecast_120m", {}) or {}
        expected_primary = _safe_float(forecast_primary.get("expected_return_pct"))
        expected_secondary = _safe_float(forecast_secondary.get("expected_return_pct"))
        initial_move = _safe_float(event.get("return_pct"))
        primary_direction = _sign_label(
            expected_primary,
            frequency=normalized_frequency,
            horizon_bars=review_horizon["primary_horizon_bars"],
        )
        actual_primary_direction = _sign_label(
            actual_primary,
            frequency=normalized_frequency,
            horizon_bars=review_horizon["primary_horizon_bars"],
        )
        secondary_direction = _sign_label(
            expected_secondary,
            frequency=normalized_frequency,
            horizon_bars=review_horizon["secondary_horizon_bars"],
        )
        actual_secondary_direction = _sign_label(
            actual_secondary,
            frequency=normalized_frequency,
            horizon_bars=review_horizon["secondary_horizon_bars"],
        )
        review_events.append(
            {
                "trigger_dt": trigger_dt.isoformat() if hasattr(trigger_dt, "isoformat") else str(trigger_dt or ""),
                "storyline": "历史上冲预测" if initial_move >= 0 else "历史下探预测",
                "direction": event.get("direction", "neutral"),
                "initial_move_pct": round(initial_move, 4),
                "review_mode": mode_key,
                "review_mode_label": mode_label,
                "primary_label": event_forecast.get("primary_label", primary_label),
                "secondary_label": event_forecast.get("secondary_label", secondary_label),
                "forecast_direction_primary": primary_direction,
                "actual_direction_primary": actual_primary_direction,
                "forecast_direction_secondary": secondary_direction,
                "actual_direction_secondary": actual_secondary_direction,
                "expected_primary_pct": round(expected_primary, 4),
                "actual_primary_pct": round(actual_primary, 4),
                "expected_secondary_pct": round(expected_secondary, 4),
                "actual_secondary_pct": round(actual_secondary, 4),
                "forecast_error_primary_pct": round(actual_primary - expected_primary, 4),
                "forecast_error_secondary_pct": round(actual_secondary - expected_secondary, 4),
                "forecast_direction_30m": primary_direction,
                "actual_direction_30m": actual_primary_direction,
                "forecast_direction_120m": secondary_direction,
                "actual_direction_120m": actual_secondary_direction,
                "expected_30m_pct": round(expected_primary, 4),
                "actual_30m_pct": round(actual_primary, 4),
                "expected_120m_pct": round(expected_secondary, 4),
                "actual_120m_pct": round(actual_secondary, 4),
                "forecast_error_30m_pct": round(actual_primary - expected_primary, 4),
                "forecast_error_120m_pct": round(actual_secondary - expected_secondary, 4),
                "surprise_score": round(_safe_float(event_forecast.get("surprise_score")), 4),
                "forecast_summary": event_forecast.get("summary", ""),
                "event_price_table": _build_review_event_price_table(
                    price_bars=price_bars,
                    event_index=event_index,
                    review_horizon=review_horizon,
                    event_forecast=event_forecast,
                ),
            }
        )

    if not review_events:
        failure_message = review_failure_reasons[0] if review_failure_reasons else f"{mode_label}模式下原生 TimesFM 不可用，无法生成历史价格预测回顾。"
        return {
            "mode_key": mode_key,
            "mode_label": mode_label,
            "mode_description": str(mode_definition.get("description", "") or ""),
            "available": False,
            "backend": "timesfm_native_unavailable",
            "error_message": failure_message,
            "summary": failure_message,
            "primary_label": primary_label,
            "secondary_label": secondary_label,
            "context_length_requested": requested_context_length,
            "context_length_used": resolved_context_length,
            "context_evaluation": context_evaluation,
            "stats": _empty_review_stats(primary_label, secondary_label),
            "events": [],
            "event_count": 0,
            "review_days": review_days,
            "frequency": normalized_frequency,
            "frequency_label": frequency_label,
        }

    sorted_events = sorted(
        review_events,
        key=lambda item: item.get("trigger_dt") or item.get("created_at") or "",
        reverse=True,
    )
    stats = _build_review_research_stats(review_events, primary_label, secondary_label)
    summary = (
        f"{mode_label}模式下，最近{review_days}天基于{frequency_label}价格共回顾{len(review_events)}个历史价格事件，"
        f"{primary_label}方向命中率{round(stats['direction_hit_rate_primary'] * 100)}%，"
        f"{secondary_label}方向命中率{round(stats['direction_hit_rate_secondary'] * 100)}%，"
        f"推荐上下文长度为{resolved_context_length}根K线。"
    )
    return {
        "mode_key": mode_key,
        "mode_label": mode_label,
        "mode_description": str(mode_definition.get("description", "") or ""),
        "available": True,
        "backend": "timesfm_native",
        "summary": summary,
        "primary_label": primary_label,
        "secondary_label": secondary_label,
        "context_length_requested": requested_context_length,
        "context_length_used": resolved_context_length,
        "context_evaluation": context_evaluation,
        "stats": stats,
        "events": sorted_events[:max_items],
        "event_count": len(review_events),
        "review_days": review_days,
        "frequency": normalized_frequency,
        "frequency_label": frequency_label,
    }


def _generate_timesfm_review_payload(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = data or {}
    current_market = str(data.get("current_market", "") or "").strip()
    current_code = str(data.get("current_code", "") or "").strip().upper()
    review_days = max(1, min(int(data.get("review_days", 14) or 14), 180))
    max_items = max(5, min(int(data.get("max_items", 8) or 8), 30))
    requested_context_length = max(0, min(int(data.get("context_length", 0) or 0), 240))
    frequency = str(data.get("frequency", "30m") or "30m").strip().lower()
    frequency_alias = {
        "5m": ("5m", "5分钟"),
        "15m": ("15m", "15分钟"),
        "30m": ("30m", "30分钟"),
        "1h": ("60m", "1小时"),
        "60m": ("60m", "1小时"),
        "4h": ("4h", "4小时"),
        "1d": ("d", "1日"),
        "d": ("d", "1日"),
    }
    normalized_frequency, frequency_label = frequency_alias.get(frequency, ("5m", "5分钟"))
    display_frequency = {
        "60m": "1h",
        "d": "1d",
    }.get(normalized_frequency, normalized_frequency)
    review_horizon = _build_review_horizon_meta(normalized_frequency)
    primary_label = review_horizon["primary_label"]
    secondary_label = review_horizon["secondary_label"]
    if not current_market or not current_code:
        raise ValueError("缺少市场或标的代码")

    price_bars = _load_historical_price_bars(
        market=current_market,
        code=current_code,
        frequency=normalized_frequency,
        lookback_hours=review_days * 24,
        purpose="TimesFM历史预测回顾",
    )
    if len(price_bars) < 40:
        return {
            "current_market": current_market,
            "current_code": current_code,
            "review_days": review_days,
            "frequency": display_frequency,
            "frequency_label": frequency_label,
            "available": False,
            "backend": "timesfm_native_unavailable",
            "error_message": f"最近{review_days}天的{frequency_label}价格数据不足，暂无法生成历史价格预测回顾。",
            "analysis_count": 0,
            "event_count": 0,
            "summary": f"最近{review_days}天的{frequency_label}价格数据不足，暂无法生成历史价格预测回顾。",
            "stats": _empty_review_stats(primary_label, secondary_label),
            "events": [],
        }

    detected_events = _detect_price_events(
        price_bars=price_bars,
        min_return_pct=0.35,
        min_range_pct=0.45,
        atr_multiple=1.2,
        event_window_minutes=max(_frequency_to_minutes(normalized_frequency), 5),
        merge_gap_minutes=max(_frequency_to_minutes(normalized_frequency) * 2, 20),
    )
    detected_events = sorted(detected_events, key=lambda item: item.get("trigger_dt") or datetime.min, reverse=True)
    sampled_events = detected_events[: max(max_items * 3, 12)]
    bar_index_map = {}
    for idx, bar in enumerate(price_bars):
        bar_dt = bar.get("dt") or bar.get("datetime") or bar.get("time")
        bar_key = bar_dt.isoformat() if hasattr(bar_dt, "isoformat") else str(bar_dt or "")
        bar_index_map[bar_key] = idx

    mode_results = [
        _run_timesfm_review_mode(
            mode_definition=mode_definition,
            price_bars=price_bars,
            current_market=current_market,
            current_code=current_code,
            normalized_frequency=normalized_frequency,
            frequency_label=frequency_label,
            review_days=review_days,
            sampled_events=sampled_events,
            bar_index_map=bar_index_map,
            review_horizon=review_horizon,
            requested_context_length=requested_context_length,
            max_items=max_items,
        )
        for mode_definition in _timesfm_review_mode_definitions()
    ]
    available_modes = [item for item in mode_results if item.get("available")]
    selected_mode = sorted(
        available_modes or mode_results,
        key=lambda item: (
            -_safe_float((item.get("stats") or {}).get("reliability_score")),
            -_safe_float((item.get("stats") or {}).get("direction_hit_rate_secondary")),
            _safe_float((item.get("stats") or {}).get("mae_secondary_pct"), 999.0),
            -_safe_float((item.get("event_count")), 0.0),
        ),
    )[0]
    mode_comparison = []
    for item in mode_results:
        item_stats = item.get("stats") or {}
        mode_comparison.append(
            {
                "mode_key": item.get("mode_key", ""),
                "mode_label": item.get("mode_label", ""),
                "mode_description": item.get("mode_description", ""),
                "available": bool(item.get("available")),
                "event_count": int(item.get("event_count", 0) or 0),
                "context_length_used": int(item.get("context_length_used", 0) or 0),
                "direction_hit_rate_primary": item_stats.get("direction_hit_rate_primary"),
                "direction_hit_rate_secondary": item_stats.get("direction_hit_rate_secondary"),
                "neutral_match_rate_primary": item_stats.get("neutral_match_rate_primary"),
                "neutral_match_rate_secondary": item_stats.get("neutral_match_rate_secondary"),
                "mae_primary_pct": item_stats.get("mae_primary_pct"),
                "mae_secondary_pct": item_stats.get("mae_secondary_pct"),
                "reliability_score": item_stats.get("reliability_score"),
                "reliability_label": item_stats.get("reliability_label"),
                "error_message": item.get("error_message", ""),
            }
        )

    if not available_modes:
        failure_message = str(selected_mode.get("error_message") or "原生 TimesFM 不可用，无法生成历史价格预测回顾。")
        return {
            "current_market": current_market,
            "current_code": current_code,
            "review_days": review_days,
            "frequency": display_frequency,
            "frequency_label": frequency_label,
            "analysis_count": 0,
            "event_count": 0,
            "backend": "timesfm_native_unavailable",
            "available": False,
            "error_message": failure_message,
            "summary": failure_message,
            "stats": _empty_review_stats(primary_label, secondary_label),
            "events": [],
            "context_length_requested": requested_context_length,
            "context_length_used": int(selected_mode.get("context_length_used", 0) or 0),
            "context_evaluation": selected_mode.get("context_evaluation", {}),
            "selected_review_mode": selected_mode.get("mode_key", ""),
            "selected_review_mode_label": selected_mode.get("mode_label", ""),
            "review_mode_results": mode_results,
            "mode_comparison": mode_comparison,
        }

    selected_stats = selected_mode.get("stats") or {}
    selected_primary_label = selected_mode.get("primary_label", primary_label)
    selected_secondary_label = selected_mode.get("secondary_label", secondary_label)
    summary = (
        f"最近{review_days}天基于{frequency_label}价格共回顾{selected_mode.get('event_count', 0)}个历史价格事件，"
        f"当前主模式为{selected_mode.get('mode_label', '纯价格')}，"
        f"{selected_primary_label}方向命中率{round(_safe_float(selected_stats.get('direction_hit_rate_primary')) * 100)}%，"
        f"{selected_secondary_label}方向命中率{round(_safe_float(selected_stats.get('direction_hit_rate_secondary')) * 100)}%，"
        f"当前可靠性评估为{selected_stats.get('reliability_label', '待观察')}。"
    )
    return {
        "current_market": current_market,
        "current_code": current_code,
        "review_days": review_days,
        "frequency": display_frequency,
        "frequency_label": frequency_label,
        "available": True,
        "backend": "timesfm_native",
        "primary_label": selected_primary_label,
        "secondary_label": selected_secondary_label,
        "context_length_requested": requested_context_length,
        "context_length_used": int(selected_mode.get("context_length_used", 0) or 0),
        "context_evaluation": selected_mode.get("context_evaluation", {}),
        "validation_method": (
            f"对最近{review_days}天的{frequency_label}价格序列先识别历史异动事件，"
            f"然后分别使用“纯价格”和“价格+事件协变量”两种模式，"
            f"站在每个事件触发当时，仅使用此前可观测信息生成预测；"
            f"每种模式内部再比较多档上下文长度，选出当前样本中表现更稳的长度后，"
            f"再拿事件后{selected_primary_label}与{selected_secondary_label}的真实走势对比方向命中率与误差；"
            f"只要预测方向与实际方向一致就计为命中，预测与实际都为持平时单独计入持平匹配率。"
        ),
        "analysis_count": len(available_modes),
        "event_count": int(selected_mode.get("event_count", 0) or 0),
        "summary": summary,
        "stats": selected_stats,
        "events": selected_mode.get("events", []),
        "selected_review_mode": selected_mode.get("mode_key", ""),
        "selected_review_mode_label": selected_mode.get("mode_label", ""),
        "selected_review_mode_description": selected_mode.get("mode_description", ""),
        "review_mode_results": mode_results,
        "mode_comparison": mode_comparison,
    }


def _summarize_realtime_price_state(
    market: str,
    code: str,
) -> Dict[str, Any]:
    price_bars = _load_historical_price_bars(market, code, "5m", lookback_hours=6, purpose="实时关注")
    if len(price_bars) < 3:
        return {
            "available": False,
            "direction": "neutral",
            "change_5m_pct": 0.0,
            "change_30m_pct": 0.0,
            "range_60m_pct": 0.0,
            "status_label": "价格数据不足",
            "alert_level": "low",
            "recent_event": None,
        }

    latest_bar = price_bars[-1]
    prev_bar = price_bars[-2]
    bar_30m = price_bars[max(0, len(price_bars) - 7)]
    last_12_bars = price_bars[-12:]
    latest_close = _safe_float(latest_bar.get("close"))
    prev_close = max(abs(_safe_float(prev_bar.get("close"))), 1e-9)
    bar_30m_close = max(abs(_safe_float(bar_30m.get("close"))), 1e-9)
    high_60m = max(_safe_float(item.get("high")) for item in last_12_bars)
    low_60m = min(_safe_float(item.get("low")) for item in last_12_bars)
    range_60m_pct = ((high_60m - low_60m) / max(abs(latest_close), 1e-9)) * 100 if latest_close else 0.0
    change_5m_pct = ((_safe_float(latest_bar.get("close")) - _safe_float(prev_bar.get("close"))) / prev_close) * 100
    change_30m_pct = ((_safe_float(latest_bar.get("close")) - _safe_float(bar_30m.get("close"))) / bar_30m_close) * 100
    price_events = _detect_price_events(
        price_bars=price_bars,
        min_return_pct=0.18,
        min_range_pct=0.28,
        atr_multiple=1.0,
        event_window_minutes=5,
        merge_gap_minutes=10,
    )
    recent_event = price_events[-1] if price_events else None
    direction = "bullish" if change_30m_pct > 0.03 else "bearish" if change_30m_pct < -0.03 else "neutral"

    if recent_event and abs(_safe_float(recent_event.get("return_pct"))) >= 0.45:
        status_label = "价格快速异动"
        alert_level = "high"
    elif abs(change_30m_pct) >= 0.65 or range_60m_pct >= 1.1:
        status_label = "波动显著放大"
        alert_level = "medium"
    elif abs(change_5m_pct) >= 0.18:
        status_label = "短线开始发力"
        alert_level = "medium"
    else:
        status_label = "价格相对平稳"
        alert_level = "low"

    recent_event_payload = None
    if recent_event:
        recent_event_payload = {
            "event_time": recent_event.get("event_time"),
            "event_time_label": _format_focus_time_label(recent_event.get("event_time")),
            "return_pct": _safe_float(recent_event.get("return_pct")),
            "range_pct": _safe_float(recent_event.get("range_pct")),
            "direction": recent_event.get("direction", "neutral"),
        }

    return {
        "available": True,
        "direction": direction,
        "change_5m_pct": round(change_5m_pct, 4),
        "change_30m_pct": round(change_30m_pct, 4),
        "range_60m_pct": round(range_60m_pct, 4),
        "status_label": status_label,
        "alert_level": alert_level,
        "latest_price": round(latest_close, 6),
        "recent_event": recent_event_payload,
    }


def _get_realtime_reference_presets(canonical_code: str, asset_type: str) -> List[Dict[str, str]]:
    presets = {
        "EURUSD": [
            {"market": "fx", "code": "USDJPY", "relation": "inverse", "reason": "美元走强时，EURUSD 与 USDJPY 往往呈反向联动"},
            {"market": "fx", "code": "USDCNH", "relation": "inverse", "reason": "离岸人民币走弱通常意味着美元偏强，容易压制 EURUSD"},
            {"market": "futures", "code": "XAU", "relation": "same", "reason": "黄金与 EURUSD 常共同反映美元方向与风险偏好"},
        ],
        "USDJPY": [
            {"market": "fx", "code": "EURUSD", "relation": "inverse", "reason": "EURUSD 回落往往对应美元偏强，与 USDJPY 形成共振"},
            {"market": "futures", "code": "XAU", "relation": "inverse", "reason": "避险升温时，黄金偏强而 USDJPY 更容易承压"},
            {"market": "fx", "code": "USDCNH", "relation": "same", "reason": "美元全局偏强时，USDJPY 与 USDCNH 常同向走强"},
        ],
        "USDCNY": [
            {"market": "fx", "code": "EURUSD", "relation": "inverse", "reason": "EURUSD 回落多半对应美元偏强，容易推升 USDCNY"},
            {"market": "fx", "code": "USDJPY", "relation": "same", "reason": "美元广泛走强时，USDJPY 与 USDCNY 常同向波动"},
            {"market": "futures", "code": "XAU", "relation": "inverse", "reason": "黄金走弱常伴随美元走强，对人民币汇率形成压力"},
        ],
        "XAU": [
            {"market": "fx", "code": "EURUSD", "relation": "same", "reason": "EURUSD 与黄金常共同反映美元方向变化"},
            {"market": "fx", "code": "USDJPY", "relation": "inverse", "reason": "避险交易中，黄金偏强往往伴随 USDJPY 走弱"},
            {"market": "fx", "code": "USDCNH", "relation": "inverse", "reason": "美元若全面走强，黄金往往承压而 USDCNH 上行"},
        ],
        "CL": [
            {"market": "futures", "code": "XAU", "relation": "inverse", "reason": "风险厌恶升温时，黄金与原油常出现分化"},
            {"market": "fx", "code": "EURUSD", "relation": "same", "reason": "美元走弱时，原油和 EURUSD 往往更易获得支撑"},
            {"market": "fx", "code": "USDCNH", "relation": "inverse", "reason": "美元走强及中国需求担忧，常对应原油压力加大"},
        ],
    }
    if canonical_code in presets:
        return presets[canonical_code]
    if asset_type == "forex":
        return [
            {"market": "fx", "code": "EURUSD", "relation": "same", "reason": "可用于观察美元方向是否在主要货币对中同步体现"},
            {"market": "fx", "code": "USDJPY", "relation": "inverse", "reason": "可用于观察避险与美元方向是否同步扩散"},
            {"market": "futures", "code": "XAU", "relation": "same", "reason": "黄金常用于辅助确认美元与风险偏好变化"},
        ]
    if asset_type in {"commodity", "precious_metal", "metal"}:
        return [
            {"market": "fx", "code": "EURUSD", "relation": "same", "reason": "用于确认美元方向是否同步作用于大宗商品"},
            {"market": "fx", "code": "USDJPY", "relation": "inverse", "reason": "用于观察避险情绪是否主导盘面"},
            {"market": "fx", "code": "USDCNH", "relation": "inverse", "reason": "用于观察美元与中国需求预期是否形成传导"},
        ]
    return []


def _evaluate_cross_asset_alignment(current_direction: str, ref_direction: str, relation: str) -> Dict[str, str]:
    if current_direction == "neutral" or ref_direction == "neutral":
        return {
            "alignment": "mixed",
            "alignment_label": "信号未完全确认",
        }
    if relation == "inverse":
        aligned = (
            (current_direction == "bullish" and ref_direction == "bearish")
            or (current_direction == "bearish" and ref_direction == "bullish")
        )
    else:
        aligned = current_direction == ref_direction
    return {
        "alignment": "aligned" if aligned else "divergent",
        "alignment_label": "联动一致" if aligned else "联动分化",
    }


def _build_cross_asset_watch(
    current_market: str,
    current_code: str,
    current_price_state: Dict[str, Any],
    product_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    canonical_code = _normalize_asset_code(current_code)
    asset_profile = get_asset_context_terms(canonical_code)
    reference_presets = _get_realtime_reference_presets(
        canonical_code,
        asset_profile.get("asset_type", (product_info or {}).get("type", "unknown")),
    )
    reference_items: List[Dict[str, Any]] = []

    for preset in reference_presets:
        reference_code = preset.get("code", "")
        if not reference_code or _normalize_asset_code(reference_code) == canonical_code:
            continue
        ref_price_state = _summarize_realtime_price_state(preset.get("market", current_market), reference_code)
        if not ref_price_state.get("available"):
            continue
        ref_product = _get_product_info(reference_code, preset.get("market", current_market))
        ref_profile = get_asset_context_terms(reference_code)
        alignment = _evaluate_cross_asset_alignment(
            current_price_state.get("direction", "neutral"),
            ref_price_state.get("direction", "neutral"),
            preset.get("relation", "same"),
        )
        reference_items.append(
            {
                "market": preset.get("market", current_market),
                "code": reference_code,
                "name": ref_product.get("name_cn") or ref_product.get("name_en") or (ref_profile.get("aliases", [])[:2] or [reference_code])[-1],
                "relation": preset.get("relation", "same"),
                "reason": preset.get("reason", ""),
                "direction": ref_price_state.get("direction", "neutral"),
                "change_5m_pct": ref_price_state.get("change_5m_pct", 0.0),
                "change_30m_pct": ref_price_state.get("change_30m_pct", 0.0),
                "status_label": ref_price_state.get("status_label", "等待信号"),
                "alert_level": ref_price_state.get("alert_level", "low"),
                "alignment": alignment.get("alignment", "mixed"),
                "alignment_label": alignment.get("alignment_label", "信号未完全确认"),
            }
        )

    reference_items.sort(
        key=lambda item: (
            _alert_level_rank(item.get("alert_level", "low")),
            abs(_safe_float(item.get("change_30m_pct", 0.0))),
        ),
        reverse=True,
    )
    aligned_count = sum(1 for item in reference_items if item.get("alignment") == "aligned")
    divergent_count = sum(1 for item in reference_items if item.get("alignment") == "divergent")
    if not reference_items:
        summary = "暂无可用的跨资产参考行情。"
    elif aligned_count >= 2:
        summary = "关键参考资产与当前标的多数同向确认，盘面更像是跨资产共振驱动。"
    elif divergent_count >= 2:
        summary = "关键参考资产与当前标的出现明显分化，需警惕单一资产噪音或假突破。"
    else:
        summary = "关键参考资产暂未形成一致方向，建议继续观察新闻与价格是否进一步共振。"

    return {
        "items": reference_items[:3],
        "summary": summary,
    }


def _classify_theme_reasoning_route(
    current_market: str,
    current_code: str,
    theme_definition: Dict[str, Any],
    product_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    product_info = product_info or _get_product_info(current_code, current_market)
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    theme_text = " ".join(
        [
            str(theme_definition.get("label") or ""),
            str(theme_definition.get("description") or ""),
            " ".join([str(item) for item in (theme_definition.get("keywords") or []) if str(item).strip()]),
        ]
    ).lower()
    route = {
        "route_id": "balanced_monitoring",
        "route_label": "均衡观察",
        "asset_class": asset_class,
        "focus": "先确认主题是否真的进入价格，再判断是否扩散到相关资产。",
        "reference_bias": ["价格时间验证", "跨资产共振", "市场数据底座"],
    }
    if asset_class == "fx":
        fx_route = _classify_fx_theme_route(current_code, theme_definition, product_info)
        return {
            "route_id": str(fx_route.get("theme_type") or "balanced_monitoring"),
            "route_label": str(fx_route.get("label") or "均衡观察"),
            "asset_class": asset_class,
            "focus": "先看相对强弱，再看美元主线、利差、风险偏好与货币对专属机制。",
            "reference_bias": ["时间验证", "跨资产共振", "美元/利率/商品链"],
            "pair_profile": fx_route.get("pair_profile", {}) if isinstance(fx_route.get("pair_profile"), dict) else {},
            "preferred_agent_ids": list(fx_route.get("preferred_agent_ids") or [])[:6],
            "preferred_agent_types": list(fx_route.get("preferred_agent_types") or [])[:6],
        }
    if asset_class == "commodity_futures":
        if any(keyword in theme_text for keyword in ["战争", "冲突", "制裁", "opec", "库存", "供给"]):
            route.update({
                "route_id": "commodity_supply",
                "route_label": "供给扰动",
                "focus": "先看库存/供给冲击，再看美元与风险偏好是否放大价格波动。",
                "reference_bias": ["相关商品", "美元", "风险资产"],
            })
        elif any(keyword in theme_text for keyword in ["需求", "中国", "基建", "地产", "刺激"]):
            route.update({
                "route_id": "commodity_demand",
                "route_label": "需求重估",
                "focus": "先看需求代理，再看期货与现货、相关品种是否共振。",
                "reference_bias": ["需求代理", "相关商品", "人民币/股指"],
            })
    elif asset_class == "equity":
        if any(keyword in theme_text for keyword in ["业绩", "财报", "盈利", "指引"]):
            route.update({
                "route_id": "earnings_revision",
                "route_label": "盈利重估",
                "focus": "先看盈利与估值，再看行业联动和资金是否确认。",
                "reference_bias": ["行业指数", "资金流", "期指/利率"],
            })
        elif any(keyword in theme_text for keyword in ["政策", "监管", "产业", "补贴"]):
            route.update({
                "route_id": "policy_repricing",
                "route_label": "政策重估",
                "focus": "先看政策方向，再看板块、龙头与资金扩散。",
                "reference_bias": ["板块联动", "资金流", "期指"],
            })
    elif asset_class == "rates_futures":
        route.update({
            "route_id": "curve_repricing",
            "route_label": "利率曲线重定价",
            "focus": "先看政策与数据，再看曲线、股债和美元是否同步重估。",
            "reference_bias": ["收益率曲线", "股债跷跷板", "美元/黄金"],
        })
    return route


def _build_cross_asset_evidence_engine(
    current_market: str,
    current_code: str,
    current_price_state: Dict[str, Any],
    cross_asset_watch: Dict[str, Any],
    theme_route: Dict[str, Any],
    product_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    product_info = product_info or _get_product_info(current_code, current_market)
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    cross_items = [item for item in list((cross_asset_watch or {}).get("items", []) or []) if isinstance(item, dict)]
    aligned_items = [item for item in cross_items if str(item.get("alignment") or "") == "aligned"]
    divergent_items = [item for item in cross_items if str(item.get("alignment") or "") == "divergent"]
    mixed_items = [item for item in cross_items if str(item.get("alignment") or "") not in {"aligned", "divergent"}]
    expected_reference_count = 3 if asset_class in {"fx", "commodity_futures", "rates_futures"} else 2
    raw_score = (
        len(aligned_items) * 1.0
        + len(mixed_items) * 0.35
        - len(divergent_items) * 0.7
    ) / max(expected_reference_count, 1)
    confirmation_score = round(max(0.0, min(1.0, (raw_score + 0.6) / 1.6)), 3)
    if len(aligned_items) >= 2:
        regime_label = "跨资产共振"
    elif len(divergent_items) >= 2:
        regime_label = "跨资产背离"
    elif cross_items:
        regime_label = "部分确认"
    else:
        regime_label = "证据缺失"
    sorted_items = sorted(
        cross_items,
        key=lambda item: abs(_safe_float(item.get("change_30m_pct"), 0.0)),
        reverse=True,
    )
    lead_asset = None
    if sorted_items:
        top_item = sorted_items[0]
        lead_asset = {
            "market": str(top_item.get("market") or ""),
            "code": str(top_item.get("code") or ""),
            "name": str(top_item.get("name") or top_item.get("code") or ""),
            "change_30m_pct": round(_safe_float(top_item.get("change_30m_pct"), 0.0), 4),
            "alignment_label": str(top_item.get("alignment_label") or "联动观察"),
        }
    missing_evidence: List[str] = []
    if len(cross_items) < expected_reference_count:
        missing_evidence.append(f"参考资产覆盖不足，仅获得 {len(cross_items)}/{expected_reference_count} 个有效价格锚。")
    if not aligned_items and cross_items:
        missing_evidence.append("相关资产尚未形成足够强的方向确认。")
    if not cross_items:
        missing_evidence.append("暂无可用的跨资产价格样本。")
    corroboration_summary = str((cross_asset_watch or {}).get("summary") or "")
    if not corroboration_summary:
        if regime_label == "跨资产共振":
            corroboration_summary = "主题已获得多个相关资产方向确认，说明价格更可能在交易同一主线。"
        elif regime_label == "跨资产背离":
            corroboration_summary = "相关资产之间出现背离，说明当前更可能是单一资产噪音或过度交易。"
        elif regime_label == "证据缺失":
            corroboration_summary = "当前缺少足够的跨资产价格证据，暂时不能用相关性强化结论。"
        else:
            corroboration_summary = "已有部分参考资产开始响应，但仍不足以构成强共振。"
    return {
        "mode": "event_window_corroboration",
        "asset_class": asset_class,
        "route_label": str(theme_route.get("route_label") or theme_route.get("label") or ""),
        "regime_label": regime_label,
        "confirmation_score": confirmation_score,
        "current_direction": str(current_price_state.get("direction") or "neutral"),
        "lead_asset": lead_asset or {},
        "best_confirmations": aligned_items[:3],
        "strongest_divergences": divergent_items[:3],
        "observed_references": cross_items[:4],
        "missing_evidence": missing_evidence[:4],
        "corroboration_summary": corroboration_summary,
    }


def _build_arbiter_execution_layer(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    temporal_evidence: Dict[str, Any],
    market_data_snapshot: Dict[str, Any],
    theme_multi_agent_panel: Dict[str, Any],
    theme_route: Dict[str, Any],
    cross_asset_evidence: Dict[str, Any],
) -> Dict[str, Any]:
    summary_block = market_data_snapshot.get("summary", {}) if isinstance(market_data_snapshot.get("summary"), dict) else {}
    arbiter = theme_multi_agent_panel.get("arbiter", {}) if isinstance(theme_multi_agent_panel.get("arbiter"), dict) else {}
    consensus = theme_multi_agent_panel.get("consensus", {}) if isinstance(theme_multi_agent_panel.get("consensus"), dict) else {}
    consensus_stance = str(consensus.get("stance") or arbiter.get("stance") or "中性")
    arbiter_confidence = _safe_float(arbiter.get("confidence"), 0.45)
    alignment_rate = _safe_float(temporal_evidence.get("alignment_rate"), 0.0)
    cross_confirmation = _safe_float(cross_asset_evidence.get("confirmation_score"), 0.0)
    reaction_count = int(summary_block.get("reaction_count", 0) or 0)
    market_metric_count = int(summary_block.get("metric_count", 0) or 0)
    conviction_score = round(
        max(
            0.0,
            min(
                1.0,
                arbiter_confidence * 0.4
                + alignment_rate * 0.25
                + cross_confirmation * 0.2
                + min(reaction_count / 3.0, 1.0) * 0.1
                + min(market_metric_count / 4.0, 1.0) * 0.05,
            ),
        ),
        3,
    )
    if alignment_rate >= 0.65 and cross_confirmation >= 0.65 and reaction_count >= 1:
        pricing_stage = "多市场确认"
    elif alignment_rate >= 0.4 or cross_confirmation >= 0.45 or reaction_count >= 1:
        pricing_stage = "部分定价"
    else:
        pricing_stage = "待确认"
    if consensus_stance == "偏多":
        execution_bias = "顺势跟踪多头" if pricing_stage != "待确认" else "等待多头确认"
    elif consensus_stance == "偏空":
        execution_bias = "顺势跟踪空头" if pricing_stage != "待确认" else "等待空头确认"
    else:
        execution_bias = "观望等待确认"
    conflicting_agents = [str(item) for item in (consensus.get("conflicting_agents") or []) if str(item).strip()]
    invalidation_triggers = list(cross_asset_evidence.get("missing_evidence") or [])[:2]
    if alignment_rate < 0.35:
        invalidation_triggers.append("新闻后的时间验证不足，需警惕消息与价格并未真正对齐。")
    if cross_confirmation < 0.35:
        invalidation_triggers.append("跨资产缺少共振确认，当前结论更容易被单市场噪音推翻。")
    if not invalidation_triggers:
        invalidation_triggers.append("若后续同主题催化不能继续扩散，当前主线判断需要快速降权。")
    route_label = str(theme_route.get("route_label") or theme_route.get("label") or "均衡观察")
    theme_label = str(theme_definition.get("label") or "当前主题")
    main_driver = f"{route_label} 是 `{theme_label}` 当前的第一解释框架。"
    if str(arbiter.get("summary") or "").strip():
        main_driver = f"{route_label}：{str(arbiter.get('summary') or '').strip()}"
    missing_evidence = list(cross_asset_evidence.get("missing_evidence") or [])
    if reaction_count <= 0:
        missing_evidence.append("尚未积累足够的事件后价格验证样本。")
    return {
        "consensus_stance": consensus_stance,
        "conviction_score": conviction_score,
        "pricing_stage": pricing_stage,
        "execution_bias": execution_bias,
        "main_driver": main_driver,
        "conflict_summary": (
            "冲突主要来自：" + "、".join(conflicting_agents[:3])
            if conflicting_agents
            else "当前主要 Agent 方向基本一致，冲突集中在证据强度而非方向。"
        ),
        "invalidation_triggers": invalidation_triggers[:4],
        "missing_evidence": missing_evidence[:4],
    }


def _build_comprehensive_reasoning_payload(
    theme_definition: Dict[str, Any],
    asset_context: Dict[str, Any],
    current_price_state: Dict[str, Any],
    temporal_evidence: Dict[str, Any],
    market_data_snapshot: Dict[str, Any],
    cross_asset_watch: Dict[str, Any],
    theme_multi_agent_panel: Dict[str, Any],
    product_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    current_market = str(asset_context.get("current_market") or "")
    current_code = str(asset_context.get("current_code") or "")
    theme_route = _classify_theme_reasoning_route(current_market, current_code, theme_definition, product_info)
    cross_asset_evidence = _build_cross_asset_evidence_engine(
        current_market=current_market,
        current_code=current_code,
        current_price_state=current_price_state,
        cross_asset_watch=cross_asset_watch,
        theme_route=theme_route,
        product_info=product_info,
    )
    arbiter_execution = _build_arbiter_execution_layer(
        theme_definition=theme_definition,
        asset_context=asset_context,
        temporal_evidence=temporal_evidence,
        market_data_snapshot=market_data_snapshot,
        theme_multi_agent_panel=theme_multi_agent_panel,
        theme_route=theme_route,
        cross_asset_evidence=cross_asset_evidence,
    )
    summary = (
        f"当前全面推演优先采用「{str(theme_route.get('route_label') or '均衡观察')}」框架；"
        f"跨资产处于「{str(cross_asset_evidence.get('regime_label') or '待确认')}」阶段，"
        f"确认分数 {float(cross_asset_evidence.get('confirmation_score', 0.0)):.2f}；"
        f"裁决层给出的执行偏向为「{str(arbiter_execution.get('execution_bias') or '观望等待确认')}」，"
        f"当前定价阶段为「{str(arbiter_execution.get('pricing_stage') or '待确认')}」。"
    )
    return {
        "mode": "rule_plus_llm",
        "summary": summary,
        "router": theme_route,
        "cross_asset_evidence": cross_asset_evidence,
        "arbiter_execution": arbiter_execution,
    }


def _build_realtime_spike_alert(
    current_code: str,
    price_state: Dict[str, Any],
    direct_news: List[Dict[str, Any]],
    driver_news: List[Dict[str, Any]],
    cross_asset_watch: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    recent_event = price_state.get("recent_event") or {}
    if price_state.get("alert_level") != "high" or not recent_event:
        return None

    cause_type = "price_only"
    cause_title = "暂无明确外部催化"
    cause_summary = "当前更像是价格与流动性先行异动，需要继续等待新闻或跨资产确认。"

    if direct_news:
        top_news = direct_news[0]
        cause_type = "direct_news"
        cause_title = top_news.get("title", "直接新闻")
        cause_summary = top_news.get("direction_reason") or top_news.get("summary") or "直接关联当前资产的新闻驱动了本次快速波动。"
    elif driver_news:
        top_news = driver_news[0]
        cause_type = "driver_news"
        cause_title = top_news.get("title", "驱动线索")
        cause_summary = top_news.get("direction_reason") or top_news.get("summary") or "驱动型新闻正在通过宏观或风险偏好传导至当前资产。"
    else:
        aligned_watch = next(
            (item for item in cross_asset_watch.get("items", []) if item.get("alignment") == "aligned"),
            None,
        )
        if aligned_watch:
            cause_type = "cross_asset"
            cause_title = aligned_watch.get("name") or aligned_watch.get("code") or "跨资产联动"
            cause_summary = aligned_watch.get("reason") or "关键参考资产同步异动，当前波动更像是跨资产共振。"

    event_time_label = recent_event.get("event_time_label", "--")
    direction_label = {
        "bullish": "快速拉升",
        "bearish": "快速下挫",
        "neutral": "异常波动",
    }.get(recent_event.get("direction", "neutral"), "异常波动")
    signature = "|".join(
        [
            str(current_code or ""),
            str(recent_event.get("event_time", "")),
            str(round(_safe_float(recent_event.get("return_pct", 0.0)), 4)),
            cause_type,
            cause_title,
        ]
    )
    return {
        "enabled": True,
        "signature": signature,
        "level": "high",
        "title": f"{current_code} 在 {event_time_label} 出现{direction_label}",
        "event_time_label": event_time_label,
        "return_pct": round(_safe_float(recent_event.get("return_pct", 0.0)), 4),
        "range_pct": round(_safe_float(recent_event.get("range_pct", 0.0)), 4),
        "cause_type": cause_type,
        "cause_title": cause_title,
        "cause_summary": cause_summary,
    }


def _build_realtime_focus_payload(
    current_market: str,
    current_code: str,
    timesfm_frequency: str = "30m",
    timesfm_context_length: int = 0,
) -> Dict[str, Any]:
    current_market = (current_market or "").strip()
    current_code = (current_code or "").strip()
    timesfm_frequency = _normalize_timesfm_frequency(timesfm_frequency)
    timesfm_context_length = max(0, min(int(timesfm_context_length or 0), 240))
    if not current_market or not current_code:
        raise ValueError("缺少当前资产信息")

    product_info = _get_product_info(current_code, current_market)
    stock_info = {}
    try:
        ex = get_exchange(Market(current_market))
        stock_info = ex.stock_info(current_code) or {}
    except Exception:
        stock_info = {}

    news_results: List[Dict[str, Any]] = []
    try:
        news_results = get_vector_news(
            current_code,
            current_market,
            days=1,
            n_results=18,
            query=stock_info.get("name") or current_code,
            product_info=product_info,
        )
    except Exception:
        start_dt = datetime.now() - timedelta(days=1)
        end_dt = datetime.now()
        search_terms = _build_news_search_terms(
            query=stock_info.get("name", "") or current_code,
            product_code=current_code,
            product_info=product_info,
            stock_info=stock_info,
        )
        news_results = _search_news_from_relational_db(
            query=stock_info.get("name", "") or current_code,
            search_terms=search_terms,
            start_date=start_dt,
            end_date=end_dt,
            n_results=18,
        )

    canonical_asset = _normalize_asset_code(current_code)
    buckets = _bucket_news_evidence(news_results, canonical_asset)
    direct_news = [_format_realtime_focus_news_item(item, "direct") for item in buckets["direct"][:4]]
    driver_news = [_format_realtime_focus_news_item(item, "driver") for item in buckets["driver"][:4]]
    price_state = _summarize_realtime_price_state(current_market, current_code)
    cross_asset_watch = _build_cross_asset_watch(
        current_market=current_market,
        current_code=current_code,
        current_price_state=price_state,
        product_info=product_info,
    )
    scenario_route = _build_research_scenario_route(
        current_market=current_market,
        current_code=current_code,
        price_state=price_state,
        direct_news=direct_news,
        driver_news=driver_news,
        cross_asset_watch=cross_asset_watch,
    )
    reflection_memory = _build_reflection_memory(
        current_market=current_market,
        current_code=current_code,
        scenario_route=scenario_route,
    )
    quick_research = _build_quick_research_snapshot(
        asset_name=stock_info.get("name") or product_info.get("name_cn") or product_info.get("name_en") or current_code,
        current_code=current_code,
        scenario_route=scenario_route,
        price_state=price_state,
        direct_news=direct_news,
        driver_news=driver_news,
    )
    deep_research = _build_deep_research_plan(scenario_route=scenario_route)
    timesfm_forecast = _build_timesfm_forecast(
        current_market=current_market,
        current_code=current_code,
        frequency=timesfm_frequency,
        context_length=timesfm_context_length or None,
        price_state=price_state,
        direct_news=direct_news,
        driver_news=driver_news,
        cross_asset_watch=cross_asset_watch,
        scenario_route=scenario_route,
    )
    risk_brief = _build_rule_based_risk_brief(
        scenario_route=scenario_route,
        price_state=price_state,
        cross_asset_watch=cross_asset_watch,
        forecast_bundle=timesfm_forecast,
    )

    alerts: List[Dict[str, Any]] = []
    if price_state.get("recent_event"):
        event = price_state["recent_event"]
        alerts.append(
            {
                "title": f"{current_code} 价格在 {event.get('event_time_label', '--')} 出现显著波动",
                "summary": (
                    f"5分钟变动 {event.get('return_pct', 0.0):.3f}% ，"
                    f"区间振幅 {event.get('range_pct', 0.0):.3f}% ，需要结合最新新闻确认驱动。"
                ),
                "occurred_at": event.get("event_time", ""),
                "occurred_at_label": event.get("event_time_label", "--"),
                "alert_level": price_state.get("alert_level", "low"),
                "category": "price",
                "category_label": "价格异动",
            }
        )

    for item in direct_news[:2]:
        alerts.append(
            {
                "title": item.get("title", "未命名新闻"),
                "summary": item.get("summary") or item.get("direction_reason") or "直接关联当前资产，建议结合价格确认是否放大波动。",
                "occurred_at": item.get("published_at", ""),
                "occurred_at_label": item.get("published_at_label", "--"),
                "alert_level": "high" if item.get("alert_level") == "high" else "medium",
                "category": "direct_news",
                "category_label": "重要新闻",
            }
        )

    for item in driver_news[:2]:
        alerts.append(
            {
                "title": item.get("title", "未命名驱动"),
                "summary": item.get("summary") or item.get("direction_reason") or "可能通过风险情绪或关键参考资产传导到当前标的。",
                "occurred_at": item.get("published_at", ""),
                "occurred_at_label": item.get("published_at_label", "--"),
                "alert_level": "medium" if item.get("alert_level") != "low" else "low",
                "category": "driver_news",
                "category_label": "驱动线索",
            }
        )

    for item in cross_asset_watch.get("items", [])[:2]:
        if _alert_level_rank(item.get("alert_level", "low")) < 2:
            continue
        alerts.append(
            {
                "title": f"{item.get('name') or item.get('code')} 出现{item.get('alignment_label', '联动变化')}",
                "summary": (
                    f"{item.get('code')} 30分钟变化 {item.get('change_30m_pct', 0.0):.3f}% ，"
                    f"{item.get('reason') or '可作为当前资产的跨资产确认线索。'}"
                ),
                "occurred_at": "",
                "occurred_at_label": "联动观察",
                "alert_level": item.get("alert_level", "low"),
                "category": "cross_asset",
                "category_label": "跨资产联动",
            }
        )

    alerts.sort(
        key=lambda item: (
            _alert_level_rank(item.get("alert_level", "low")),
            str(item.get("occurred_at", "")),
        ),
        reverse=True,
    )

    overall_alert_level = price_state.get("alert_level", "low")
    if alerts:
        overall_alert_level = max(alerts[:3], key=lambda item: _alert_level_rank(item.get("alert_level", "low"))).get("alert_level", overall_alert_level)

    direct_headline = direct_news[0]["title"] if direct_news else ""
    driver_headline = driver_news[0]["title"] if driver_news else ""
    focus_summary_parts = [f"{current_code} 当前处于“{price_state.get('status_label', '等待信号')}”状态"]
    if direct_headline:
        focus_summary_parts.append(f"最相关的直接新闻是“{direct_headline}”")
    if driver_headline:
        focus_summary_parts.append(f"同时需留意驱动线索“{driver_headline}”")
    if not direct_headline and not driver_headline:
        focus_summary_parts.append("暂无足够强的新闻驱动，需要继续观察价格是否独立扩散")
    if cross_asset_watch.get("summary"):
        focus_summary_parts.append(cross_asset_watch["summary"].rstrip("。"))

    urgent_alert = _build_realtime_spike_alert(
        current_code=current_code,
        price_state=price_state,
        direct_news=direct_news,
        driver_news=driver_news,
        cross_asset_watch=cross_asset_watch,
    )
    topic_timeline = _build_realtime_topic_timeline(
        current_market=current_market,
        current_code=current_code,
        current_name=stock_info.get("name") or product_info.get("name_cn") or product_info.get("name_en") or current_code,
        price_state=price_state,
        alerts=alerts[:6],
        direct_news=direct_news,
        driver_news=driver_news,
        urgent_alert=urgent_alert,
        cross_asset_watch=cross_asset_watch,
    )
    topic_definitions = _get_asset_event_topic_definitions(current_market, current_code)

    return {
        "asset": {
            "market": current_market,
            "market_label": current_market.upper(),
            "code": current_code,
            "name": stock_info.get("name") or product_info.get("name_cn") or product_info.get("name_en") or current_code,
        },
        "alert_level": overall_alert_level,
        "price_state": price_state,
        "focus_summary": "；".join(focus_summary_parts) + "。",
        "direct_news": direct_news,
        "driver_news": driver_news,
        "cross_asset_watch": cross_asset_watch.get("items", []),
        "cross_asset_summary": cross_asset_watch.get("summary", ""),
        "scenario_route": scenario_route,
        "reflection_memory": reflection_memory,
        "quick_research": quick_research,
        "deep_research": deep_research,
        "risk_brief": risk_brief,
        "timesfm_forecast": timesfm_forecast,
        "timesfm_frequency": timesfm_frequency,
        "timesfm_context_length": timesfm_context_length,
        "urgent_alert": urgent_alert,
        "topic_definitions": topic_definitions,
        "topic_timeline": topic_timeline,
        "alerts": alerts[:6],
    }


def _compute_bar_atr_pct(price_bars: List[Dict[str, Any]], index: int, period: int = 20) -> float:
    if not price_bars:
        return 0.0
    start_index = max(0, index - period + 1)
    tr_values: List[float] = []
    for idx in range(start_index, index + 1):
        bar = price_bars[idx]
        prev_close = price_bars[idx - 1]["close"] if idx > 0 else bar["open"]
        tr = max(
            _safe_float(bar["high"]) - _safe_float(bar["low"]),
            abs(_safe_float(bar["high"]) - _safe_float(prev_close)),
            abs(_safe_float(bar["low"]) - _safe_float(prev_close)),
        )
        ref_price = max(abs(_safe_float(prev_close)), 1e-9)
        tr_values.append((tr / ref_price) * 100)
    return sum(tr_values) / len(tr_values) if tr_values else 0.0


def _merge_adjacent_price_events(
    events: List[Dict[str, Any]],
    gap_minutes: int,
) -> List[Dict[str, Any]]:
    if not events:
        return []

    merged = [dict(events[0])]
    for event in events[1:]:
        previous = merged[-1]
        gap = (event["trigger_dt"] - previous["trigger_dt"]).total_seconds() / 60
        same_direction = event["direction"] == previous["direction"]
        if gap <= gap_minutes and same_direction:
            previous["window_end"] = max(previous["window_end"], event["window_end"])
            previous["abs_return_pct"] = max(previous["abs_return_pct"], event["abs_return_pct"])
            previous["bar_range_pct"] = max(previous["bar_range_pct"], event["bar_range_pct"])
            previous["follow_30m_pct"] = event["follow_30m_pct"]
            previous["follow_120m_pct"] = event["follow_120m_pct"]
            previous["event_count"] = previous.get("event_count", 1) + 1
            continue
        merged.append(dict(event))

    for index, event in enumerate(merged, 1):
        event["event_id"] = f"evt_{index}"
    return merged


def _detect_price_events(
    price_bars: List[Dict[str, Any]],
    min_return_pct: float,
    min_range_pct: float,
    atr_multiple: float,
    event_window_minutes: int,
    merge_gap_minutes: int,
) -> List[Dict[str, Any]]:
    raw_events: List[Dict[str, Any]] = []
    for index, bar in enumerate(price_bars):
        reference_price = price_bars[index - 1]["close"] if index > 0 else bar["open"]
        reference_price = max(abs(_safe_float(reference_price)), 1e-9)
        close_price = _safe_float(bar["close"])
        return_pct = ((close_price - reference_price) / reference_price) * 100
        bar_range_pct = ((_safe_float(bar["high"]) - _safe_float(bar["low"])) / reference_price) * 100
        atr_pct = _compute_bar_atr_pct(price_bars, index)
        passed_threshold = (
            abs(return_pct) >= min_return_pct
            or bar_range_pct >= min_range_pct
            or (atr_pct > 0 and abs(return_pct) >= atr_pct * atr_multiple)
        )
        if not passed_threshold:
            continue

        direction_sign = 1 if return_pct >= 0 else -1
        future_30_index = min(len(price_bars) - 1, index + 6)
        future_120_index = min(len(price_bars) - 1, index + 24)
        follow_30m_pct = (
            ((_safe_float(price_bars[future_30_index]["close"]) - close_price) / max(abs(close_price), 1e-9))
            * 100
        )
        follow_120m_pct = (
            ((_safe_float(price_bars[future_120_index]["close"]) - close_price) / max(abs(close_price), 1e-9))
            * 100
        )
        raw_events.append(
            {
                "trigger_dt": bar["dt"],
                "window_start": bar["dt"] - timedelta(minutes=event_window_minutes),
                "window_end": bar["dt"] + timedelta(minutes=event_window_minutes),
                "direction": "bullish" if return_pct >= 0 else "bearish",
                "direction_sign": direction_sign,
                "reference_price": reference_price,
                "close_price": close_price,
                "return_pct": return_pct,
                "abs_return_pct": abs(return_pct),
                "bar_range_pct": bar_range_pct,
                "atr_pct": atr_pct,
                "follow_30m_pct": follow_30m_pct,
                "follow_120m_pct": follow_120m_pct,
                "event_count": 1,
            }
        )

    merged_events = _merge_adjacent_price_events(raw_events, merge_gap_minutes)
    merged_events.sort(key=lambda item: item["abs_return_pct"], reverse=True)
    return merged_events


def _extract_metadata_asset_list(metadata: Dict[str, Any], field: str) -> List[str]:
    value = metadata.get(field, [])
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().upper() for item in value.split(",") if item.strip()]
    return []


def _assess_event_absorption(event: Dict[str, Any]) -> Dict[str, Any]:
    direction_sign = event.get("direction_sign", 1)
    initial_move = max(event.get("abs_return_pct", 0.0), 1e-9)
    directional_30m = event.get("follow_30m_pct", 0.0) * direction_sign
    directional_120m = event.get("follow_120m_pct", 0.0) * direction_sign

    if directional_120m >= initial_move * 0.5:
        return {"status": "not_fully_priced", "reason": "事件后 30-120 分钟价格仍在顺着初始方向延续"}
    if directional_30m >= initial_move * 0.15:
        return {"status": "partially_absorbed", "reason": "事件后价格维持主要涨跌幅，但扩展有限"}
    return {"status": "absorbed", "reason": "事件后价格缺乏延续，主导影响大概率已被市场快速消化"}


_STORYLINE_KEYWORD_MAP = {
    "央行与利率": ["美联储", "fed", "ecb", "央行", "利率", "降息", "加息", "鲍威尔"],
    "宏观数据": ["cpi", "ppi", "非农", "pmi", "通胀", "就业", "零售销售", "gdp"],
    "地缘政治": ["战争", "冲突", "制裁", "中东", "俄乌", "台海", "伊朗", "以色列"],
    "风险情绪": ["避险", "risk", "美元指数", "dxy", "美债", "收益率"],
    "商品供给": ["原油", "库存", "opec", "供应", "金属", "黄金"],
    "政策监管": ["关税", "政策", "监管", "财政", "刺激", "出口管制"],
}


_EVENT_TOPIC_CONFIG_CACHE_KEY = "news:event_topic_config:v1"
_DEFAULT_EVENT_TOPIC_DEFINITIONS = [
    {
        "id": "iran-conflict",
        "label": "伊朗战争",
        "description": "聚焦伊朗相关战争、袭击、制裁与中东升级对资产的影响",
        "keywords": ["伊朗", "中东", "霍尔木兹", "以色列", "袭击", "导弹", "制裁"],
        "enabled": True,
    },
    {
        "id": "russia-ukraine-war",
        "label": "俄乌战争",
        "description": "聚焦俄乌冲突、能源供给与制裁升级",
        "keywords": ["俄乌", "乌克兰", "俄罗斯", "北溪", "制裁", "停火", "天然气"],
        "enabled": True,
    },
    {
        "id": "fed-officials",
        "label": "美联储官员讲话",
        "description": "聚焦 FOMC、鲍威尔及联储官员讲话对美元和利率预期的冲击",
        "keywords": ["美联储", "fed", "fomc", "鲍威尔", "票委", "官员讲话", "联储"],
        "enabled": True,
    },
    {
        "id": "trump-remarks",
        "label": "特朗普讲话",
        "description": "聚焦特朗普讲话、竞选表态、关税与政策预期变化",
        "keywords": ["特朗普", "trump", "关税", "竞选", "白宫", "讲话", "政策表态"],
        "enabled": True,
    },
    {
        "id": "inflation-data",
        "label": "通胀数据",
        "description": "聚焦 CPI、PPI、通胀预期等数据",
        "keywords": ["cpi", "ppi", "通胀", "核心通胀", "物价", "inflation"],
        "enabled": True,
    },
    {
        "id": "nonfarm-jobs",
        "label": "非农与就业",
        "description": "聚焦非农、失业率、就业数据冲击",
        "keywords": ["非农", "失业率", "就业", "薪资", "劳动力", "nfp"],
        "enabled": True,
    },
    {
        "id": "oil-supply",
        "label": "原油供给",
        "description": "聚焦 OPEC、库存、原油供给扰动",
        "keywords": ["原油", "opec", "库存", "供应", "减产", "油价", "炼厂"],
        "enabled": True,
    },
]

_ASSET_CLASS_EVENT_TOPIC_PRESETS = {
    "equity": [
        {"id": "earnings-guidance", "label": "财报与业绩指引", "description": "聚焦财报、业绩预告、盈利指引与一致预期修正", "keywords": ["财报", "业绩预告", "盈利预警", "业绩指引", "利润", "营收", "净利润", "预期上修", "预期下修"]},
        {"id": "industry-policy", "label": "产业政策", "description": "聚焦行业政策、补贴、监管与产业规划", "keywords": ["产业政策", "政策支持", "补贴", "规划", "监管", "牌照", "行业指导", "征求意见稿"]},
        {"id": "northbound-flow", "label": "北向资金", "description": "聚焦北向资金、外资配置与风险偏好变化", "keywords": ["北向资金", "沪股通", "深股通", "外资流入", "外资流出", "南向资金"]},
        {"id": "buyback-and-holding", "label": "回购与增减持", "description": "聚焦回购、增持、减持与股东行为", "keywords": ["回购", "增持", "减持", "股东", "实控人", "高管增持", "股份回购"]},
        {"id": "restricted-release", "label": "解禁与再融资", "description": "聚焦限售解禁、定增、配股与供给压力", "keywords": ["解禁", "限售股", "定增", "配股", "再融资", "减持计划"]},
    ],
    "fx": [
        {"id": "dxy-dollar", "label": "美元指数", "description": "聚焦美元指数、美元流动性与全球风险偏好", "keywords": ["美元指数", "DXY", "美元走强", "美元走弱", "美元流动性"]},
        {"id": "us-treasury-yields", "label": "美债收益率", "description": "聚焦美债收益率与实际利率变化", "keywords": ["美债收益率", "10年美债", "2年美债", "实际利率", "收益率上行", "收益率下行"]},
        {"id": "carry-trade", "label": "套息交易", "description": "聚焦利差交易、风险偏好与套息平仓", "keywords": ["套息交易", "利差交易", "carry", "平仓", "风险偏好", "风险厌恶"]},
        {"id": "central-bank-guidance", "label": "央行前瞻指引", "description": "聚焦主要央行措辞变化与前瞻指引", "keywords": ["前瞻指引", "央行措辞", "利率路径", "降息预期", "加息预期", "会议纪要"]},
    ],
    "commodity_futures": [
        {"id": "inventory-supply", "label": "库存与供给", "description": "聚焦库存变化、供给扰动与产量收缩", "keywords": ["库存", "供给", "减产", "增产", "停产", "开工率", "发运", "产量"]},
        {"id": "basis-spot", "label": "基差与现货", "description": "聚焦现货价格、基差与近远月结构", "keywords": ["基差", "现货", "升水", "贴水", "月差", "近强远弱", "近弱远强"]},
        {"id": "china-demand", "label": "中国需求", "description": "聚焦中国地产、制造业、基建与需求预期", "keywords": ["中国需求", "地产", "制造业", "基建", "PMI", "开工", "消费旺季", "需求恢复"]},
        {"id": "commodity-macro", "label": "美元与通胀", "description": "聚焦美元、通胀与全球需求周期", "keywords": ["美元指数", "通胀", "实际利率", "需求预期", "衰退预期", "软着陆"]},
    ],
    "rates_futures": [
        {"id": "pboc-liquidity", "label": "央行流动性", "description": "聚焦公开市场操作、MLF、逆回购与降准降息", "keywords": ["公开市场操作", "逆回购", "MLF", "LPR", "降准", "降息", "央行投放", "人民银行"]},
        {"id": "funding-stress", "label": "资金面", "description": "聚焦回购利率、资金松紧与季末扰动", "keywords": ["资金面", "回购利率", "DR007", "R007", "跨季", "跨月", "流动性收紧", "流动性宽松"]},
        {"id": "yield-curve", "label": "收益率曲线", "description": "聚焦曲线陡峭化、平坦化与期限利差", "keywords": ["收益率曲线", "期限利差", "陡峭化", "平坦化", "长端利率", "短端利率"]},
        {"id": "fiscal-supply", "label": "财政供给", "description": "聚焦国债供给、地方债发行与财政发力", "keywords": ["国债发行", "地方债", "特别国债", "财政刺激", "供给压力", "发债"]},
    ],
    "macro": [
        {"id": "global-risk", "label": "全球风险偏好", "description": "聚焦避险、风险资产轮动与跨资产冲击", "keywords": ["避险", "风险偏好", "风险厌恶", "波动率", "全球市场", "跨资产"]},
        {"id": "growth-expectation", "label": "增长预期", "description": "聚焦 PMI、GDP、工业生产与需求周期", "keywords": ["PMI", "GDP", "工业生产", "零售销售", "增长预期", "经济放缓", "经济复苏"]},
    ],
}


def _slugify_topic_id(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(label or "").strip().lower())
    normalized = normalized.strip("-")
    return normalized or f"topic-{uuid.uuid4().hex[:8]}"


def _normalize_topic_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,，\n]+", str(value or ""))
    keywords: List[str] = []
    seen: set = set()
    for item in raw_items:
        keyword = str(item or "").strip()
        if not keyword:
            continue
        key = keyword.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(keyword)
    return keywords[:24]


def _normalize_event_topic_definition(topic: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    label = str(topic.get("label", "") or "").strip() or f"自定义主题{index + 1}"
    topic_id = str(topic.get("id", "") or "").strip() or _slugify_topic_id(label)
    asset_classes = [
        str(item).strip()
        for item in (topic.get("asset_classes") or [])
        if str(item).strip()
    ]
    markets = [
        str(item).strip()
        for item in (topic.get("markets") or [])
        if str(item).strip()
    ]
    return {
        "id": topic_id,
        "label": label,
        "description": str(topic.get("description", "") or "").strip(),
        "keywords": _normalize_topic_keywords(topic.get("keywords", [])),
        "enabled": bool(topic.get("enabled", True)),
        "asset_classes": asset_classes,
        "markets": markets,
        "preset_source": str(topic.get("preset_source", "") or "").strip(),
    }


def _default_event_topic_definitions() -> List[Dict[str, Any]]:
    return [
        _normalize_event_topic_definition(item, index)
        for index, item in enumerate(_DEFAULT_EVENT_TOPIC_DEFINITIONS)
    ]


def _merge_event_topic_definitions(*topic_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for group in topic_groups:
        for index, item in enumerate(group or []):
            if not isinstance(item, dict):
                continue
            normalized = _normalize_event_topic_definition(item, index)
            key = normalized.get("id") or normalized.get("label")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(normalized)
    return merged


def _build_asset_topic_preset_definitions(current_market: str = "", current_code: str = "") -> List[Dict[str, Any]]:
    if current_code or current_market:
        try:
            product_info = _get_product_info(current_code or "", current_market or "")
        except TypeError:
            # 兼容旧测试桩和旧调用方式
            product_info = _get_product_info(current_code or "")
    else:
        product_info = {}
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    presets: List[Dict[str, Any]] = []
    for item in _ASSET_CLASS_EVENT_TOPIC_PRESETS.get(asset_class, []):
        preset = dict(item)
        preset["asset_classes"] = [asset_class]
        preset["markets"] = [str(current_market or "").lower()] if current_market else []
        preset["preset_source"] = "asset_default"
        presets.append(preset)

    info_text = " ".join(
        [
            str(product_info.get("name_cn") or ""),
            str(product_info.get("name_en") or ""),
            str(product_info.get("symbol") or ""),
            " ".join([str(item) for item in (product_info.get("keywords") or [])[:12]]),
        ]
    ).lower()
    if asset_class == "fx":
        fx_profile = _build_fx_market_data_profile(current_code, product_info)
        base_currency = str(fx_profile.get("base_currency") or "").upper()
        quote_currency = str(fx_profile.get("quote_currency") or "").upper()
        dynamic_topics: List[Dict[str, Any]] = []
        if "USD" in {base_currency, quote_currency}:
            dynamic_topics.extend(
                [
                    {"id": "fed-officials-fx", "label": "美联储官员讲话", "description": "聚焦联储讲话对美元与利差预期的冲击", "keywords": ["美联储", "Fed", "FOMC", "鲍威尔", "点阵图", "票委"], "asset_classes": ["fx"]},
                    {"id": "us-inflation-jobs-fx", "label": "美国通胀与就业", "description": "聚焦 CPI、PCE、非农和失业率对美元的影响", "keywords": ["CPI", "PCE", "非农", "失业率", "薪资", "美国就业"], "asset_classes": ["fx"]},
                ]
            )
        if "EUR" in {base_currency, quote_currency}:
            dynamic_topics.append({"id": "ecb-eurozone", "label": "欧洲央行与欧元区数据", "description": "聚焦 ECB、欧元区通胀与增长预期", "keywords": ["欧洲央行", "ECB", "拉加德", "欧元区", "德国", "欧元区通胀", "欧元区PMI"], "asset_classes": ["fx"]})
        if "JPY" in {base_currency, quote_currency}:
            dynamic_topics.append({"id": "boj-yen-intervention", "label": "日本央行与日元干预", "description": "聚焦 BOJ 政策、YCC 与汇率干预", "keywords": ["日本央行", "BOJ", "植田和男", "干预", "YCC", "日元"], "asset_classes": ["fx"]})
        if "GBP" in {base_currency, quote_currency}:
            dynamic_topics.append({"id": "boe-uk", "label": "英国央行与英国数据", "description": "聚焦 BOE、英国通胀与增长", "keywords": ["英国央行", "BOE", "英国通胀", "英国就业", "英国PMI", "英镑"], "asset_classes": ["fx"]})
        if "CNY" in {base_currency, quote_currency} or "CNH" in {base_currency, quote_currency}:
            dynamic_topics.append({"id": "pboc-rmb-fixing", "label": "人民币中间价与央行政策", "description": "聚焦中间价、逆周期因子与中美利差", "keywords": ["人民币中间价", "逆周期因子", "人民银行", "PBOC", "中美利差", "离岸人民币", "在岸人民币"], "asset_classes": ["fx"]})
        for item in dynamic_topics:
            item["preset_source"] = "asset_default"
            presets.append(item)
    elif asset_class == "commodity_futures":
        dynamic_topics = []
        if any(keyword in info_text for keyword in ["gold", "黄金", "xau", "au", "silver", "白银", "xag", "ag"]):
            dynamic_topics.extend(
                [
                    {"id": "precious-metals-real-yields", "label": "实际利率与贵金属", "description": "聚焦实际利率、美元与黄金白银的定价关系", "keywords": ["实际利率", "美债收益率", "黄金", "白银", "美元指数", "贵金属"], "asset_classes": ["commodity_futures"]},
                    {"id": "precious-metals-geopolitics", "label": "避险与地缘冲突", "description": "聚焦地缘冲突与避险需求对贵金属的推动", "keywords": ["避险", "地缘冲突", "中东", "黄金", "白银", "战争"], "asset_classes": ["commodity_futures"]},
                ]
            )
        if any(keyword in info_text for keyword in ["oil", "原油", "wti", "brent", "cl", "sc"]):
            dynamic_topics.extend(
                [
                    {"id": "opec-and-eia", "label": "OPEC 与 EIA 库存", "description": "聚焦 OPEC 产量、EIA/API 库存与油价波动", "keywords": ["OPEC", "EIA", "API", "原油库存", "减产", "增产", "WTI", "Brent"], "asset_classes": ["commodity_futures"]},
                    {"id": "middle-east-shipping", "label": "中东航运与地缘风险", "description": "聚焦中东冲突、航运中断与原油风险溢价", "keywords": ["霍尔木兹", "中东", "地缘风险", "航运", "油轮", "红海"], "asset_classes": ["commodity_futures"]},
                ]
            )
        if any(keyword in info_text for keyword in ["铜", "cu", "copper", "铝", "al", "锌", "zn", "工业硅", "多晶硅"]):
            dynamic_topics.append({"id": "china-manufacturing-demand", "label": "中国制造业与工业需求", "description": "聚焦地产、基建、制造业 PMI 与工业金属需求", "keywords": ["制造业PMI", "地产", "基建", "需求恢复", "铜", "铝", "工业金属", "库存去化"], "asset_classes": ["commodity_futures"]})
        for item in dynamic_topics:
            item["preset_source"] = "asset_default"
            presets.append(item)
    elif asset_class == "equity":
        dynamic_topics = []
        if any(keyword in info_text for keyword in ["银行", "券商", "保险", "金融"]):
            dynamic_topics.append({"id": "financial-regulation", "label": "金融监管与资本市场政策", "description": "聚焦监管节奏、资本市场政策与风险偏好", "keywords": ["监管", "资本市场", "券商", "银行", "保险", "两融", "印花税"], "asset_classes": ["equity"]})
        if any(keyword in info_text for keyword in ["芯片", "半导体", "算力", "ai", "人工智能", "科技"]):
            dynamic_topics.append({"id": "technology-cycle", "label": "科技周期与算力产业链", "description": "聚焦 AI、算力、芯片与科技景气", "keywords": ["AI", "人工智能", "算力", "芯片", "半导体", "服务器", "景气度"], "asset_classes": ["equity"]})
        if any(keyword in info_text for keyword in ["新能源", "锂", "电池", "光伏", "储能"]):
            dynamic_topics.append({"id": "new-energy-policy", "label": "新能源政策与价格链", "description": "聚焦新能源政策、原材料价格与需求节奏", "keywords": ["新能源", "锂", "光伏", "储能", "补贴", "装机", "电池"], "asset_classes": ["equity"]})
        for item in dynamic_topics:
            item["preset_source"] = "asset_default"
            presets.append(item)
    elif asset_class == "rates_futures":
        presets.extend(
            [
                _normalize_event_topic_definition({"id": "inflation-and-growth", "label": "通胀与增长预期", "description": "聚焦通胀、经济数据和宽信用预期", "keywords": ["通胀", "CPI", "PPI", "PMI", "社融", "信贷", "经济增长"], "asset_classes": ["rates_futures"], "preset_source": "asset_default"}),
                _normalize_event_topic_definition({"id": "policy-easing", "label": "货币宽松与政策发力", "description": "聚焦降准降息、财政刺激与政策协同", "keywords": ["降准", "降息", "财政刺激", "特别国债", "政策发力", "稳增长"], "asset_classes": ["rates_futures"], "preset_source": "asset_default"}),
            ]
        )
    return _merge_event_topic_definitions(presets)


def _get_asset_event_topic_definitions(current_market: str = "", current_code: str = "") -> List[Dict[str, Any]]:
    saved_topics = _load_event_topic_definitions()
    return _merge_event_topic_definitions(
        _default_event_topic_definitions(),
        _build_asset_topic_preset_definitions(current_market, current_code),
        saved_topics,
    )


_THEME_AGENT_CONFIG_CACHE_KEY = "news:theme_agent_config:v1"
_DEFAULT_THEME_AGENT_DEFINITIONS = [
    {
        "id": "evidence_scout",
        "label": "证据侦察 Agent",
        "description": "负责扫描主题直达新闻、驱动新闻与背景新闻，确认主题是否真的在发酵。",
        "agent_type": "evidence",
        "role": "主题证据与催化扫描",
        "asset_classes": ["equity", "fx", "commodity_futures", "rates_futures", "macro"],
        "theme_keywords": [],
        "focus_points": ["直达新闻", "驱动新闻", "主题强度", "新增催化"],
        "instructions": "优先给出最关键的新增催化，不要重复新闻搬运。",
        "enabled": True,
        "priority": 100,
        "preset_source": "system",
    },
    {
        "id": "market_validator",
        "label": "价格验证 Agent",
        "description": "负责验证新闻之后价格有没有真实跟随，以及方向是否一致。",
        "agent_type": "temporal",
        "role": "时间性与价格验证",
        "asset_classes": ["equity", "fx", "commodity_futures", "rates_futures", "macro"],
        "theme_keywords": [],
        "focus_points": ["时间性", "方向一致率", "30分钟跟随", "交易确认"],
        "instructions": "如果价格没有确认，要明确提示证据与价格脱节。",
        "enabled": True,
        "priority": 95,
        "preset_source": "system",
    },
    {
        "id": "market_structure",
        "label": "市场结构 Agent",
        "description": "负责读取市场数据底座中的事件、因子、结构指标与价格验证。",
        "agent_type": "market_data",
        "role": "底座因子与结构确认",
        "asset_classes": ["equity", "fx", "commodity_futures", "rates_futures", "macro"],
        "theme_keywords": [],
        "focus_points": ["底座事件", "因子快照", "结构指标", "验证样本"],
        "instructions": "优先引用已经同步的库存、基差、利差、曲线、资金流、CFTC 等结构证据。",
        "enabled": True,
        "priority": 92,
        "preset_source": "system",
    },
    {
        "id": "actor_tracker",
        "label": "主体跟踪 Agent",
        "description": "负责识别谁在推动这条主题，以及主体立场是否一致。",
        "agent_type": "actor",
        "role": "主体立场与行为跟踪",
        "asset_classes": ["equity", "fx", "commodity_futures", "rates_futures", "macro"],
        "theme_keywords": [],
        "focus_points": ["关键主体", "立场变化", "政策措辞", "驱动一致性"],
        "instructions": "优先输出具体主体而不是抽象情绪。",
        "enabled": True,
        "priority": 88,
        "preset_source": "system",
    },
    {
        "id": "cross_asset_resonance",
        "label": "跨资产共振 Agent",
        "description": "负责识别当前资产与联动资产之间是否形成共振或背离。",
        "agent_type": "cross_asset",
        "role": "跨资产与联动确认",
        "asset_classes": ["equity", "fx", "commodity_futures", "rates_futures", "macro"],
        "theme_keywords": [],
        "focus_points": ["跨资产共振", "联动方向", "背离", "风险传染"],
        "instructions": "优先输出是否共振，不要只罗列联动资产名字。",
        "enabled": True,
        "priority": 84,
        "preset_source": "system",
    },
    {
        "id": "risk_arbiter",
        "label": "裁决 Agent",
        "description": "负责汇总各 Agent 观点，识别一致结论、冲突点和风险边界。",
        "agent_type": "arbiter",
        "role": "多 Agent 裁决与风险边界",
        "asset_classes": ["equity", "fx", "commodity_futures", "rates_futures", "macro"],
        "theme_keywords": [],
        "focus_points": ["共识方向", "冲突来源", "执行边界", "失效条件"],
        "instructions": "必须告诉交易员哪些证据能交易，哪些证据不能直接交易。",
        "enabled": True,
        "priority": 110,
        "preset_source": "system",
    },
]
_ASSET_CLASS_THEME_AGENT_PRESETS = {
    "fx": [
        {"id": "fx_macro_policy", "label": "央行宏观 Agent", "description": "聚焦央行决议、利差路径、通胀和就业。", "agent_type": "macro_policy", "role": "央行与宏观主轴", "focus_points": ["央行决议", "利差", "通胀", "就业"], "theme_keywords": ["央行", "美联储", "欧洲央行", "CPI", "非农", "通胀", "就业"], "priority": 96},
        {"id": "fx_macro_surprise", "label": "宏观预期差 Agent", "description": "聚焦 CPI、非农、PMI 与增长数据的预期差。", "agent_type": "macro_surprise", "role": "宏观数据预期差", "focus_points": ["CPI", "非农", "PMI", "增长预期差"], "theme_keywords": ["CPI", "非农", "PMI", "GDP", "零售", "就业", "通胀"], "priority": 94},
        {"id": "fx_usd_regime", "label": "美元主线 Agent", "description": "聚焦美元指数、美债收益率与美元流动性。", "agent_type": "usd_regime", "role": "美元系统主线", "focus_points": ["美元指数", "美债收益率", "实际利率", "美元流动性"], "theme_keywords": ["美元", "DXY", "美债", "实际利率", "美元流动性"], "priority": 92},
        {"id": "fx_positioning", "label": "外汇持仓 Agent", "description": "聚焦 CFTC、美元拥挤度与趋势延续。", "agent_type": "positioning", "role": "外汇持仓与拥挤度", "focus_points": ["CFTC", "美元指数", "拥挤度", "延续性"], "theme_keywords": ["美元", "欧元", "英镑", "日元", "人民币"], "priority": 86},
        {"id": "fx_risk_sentiment", "label": "风险偏好 Agent", "description": "聚焦避险情绪、股债波动与资金回流方向。", "agent_type": "risk_sentiment", "role": "风险偏好与避险流", "focus_points": ["避险情绪", "股债波动", "VIX", "套息平仓"], "theme_keywords": ["避险", "风险偏好", "战争", "关税", "特朗普", "冲突"], "priority": 88},
        {"id": "fx_cross_asset", "label": "跨资产共振 Agent", "description": "聚焦利率、商品、股指与汇率是否形成共振。", "agent_type": "cross_asset", "role": "跨资产验证", "focus_points": ["利率", "商品", "股指", "汇率共振"], "theme_keywords": ["收益率", "黄金", "原油", "铜", "股指", "共振"], "priority": 84},
    ],
    "commodity_futures": [
        {"id": "commodity_supply_chain", "label": "供需链 Agent", "description": "聚焦供给扰动、库存变化、发运、开工。", "agent_type": "supply_chain", "role": "供给与库存主线", "focus_points": ["库存", "供给", "开工率", "发运"], "theme_keywords": ["库存", "供给", "减产", "增产", "发运", "开工"], "priority": 96},
        {"id": "commodity_basis", "label": "基差现货 Agent", "description": "聚焦现货、基差和期限结构确认。", "agent_type": "basis_structure", "role": "基差与现货验证", "focus_points": ["基差", "现货", "升贴水", "月差"], "theme_keywords": ["基差", "现货", "升水", "贴水", "月差"], "priority": 90},
        {"id": "commodity_geopolitics", "label": "地缘供给 Agent", "description": "聚焦战争、制裁、航运中断与商品风险溢价。", "agent_type": "geopolitics", "role": "地缘与风险溢价", "focus_points": ["战争", "制裁", "航运", "风险溢价"], "theme_keywords": ["战争", "制裁", "中东", "航运", "红海", "霍尔木兹", "伊朗"], "priority": 89},
    ],
    "equity": [
        {"id": "equity_earnings", "label": "业绩估值 Agent", "description": "聚焦财报、盈利预期和估值重定价。", "agent_type": "earnings", "role": "财报与估值主线", "focus_points": ["财报", "预期差", "盈利修正", "估值"], "theme_keywords": ["财报", "业绩", "利润", "营收", "预告", "指引"], "priority": 95},
        {"id": "equity_flow_sentiment", "label": "资金情绪 Agent", "description": "聚焦北向、主力资金、回购与解禁。", "agent_type": "flow", "role": "资金面与情绪确认", "focus_points": ["北向资金", "主力资金", "回购", "解禁"], "theme_keywords": ["北向资金", "回购", "解禁", "增持", "减持"], "priority": 88},
        {"id": "equity_policy_industry", "label": "产业政策 Agent", "description": "聚焦行业政策、监管、补贴和产业周期。", "agent_type": "policy_industry", "role": "产业政策与行业周期", "focus_points": ["政策", "监管", "补贴", "行业周期"], "theme_keywords": ["政策", "监管", "补贴", "牌照", "产业", "规划"], "priority": 90},
    ],
    "rates_futures": [
        {"id": "rates_liquidity_curve", "label": "流动性曲线 Agent", "description": "聚焦回购利率、收益率曲线和互换。", "agent_type": "liquidity_curve", "role": "流动性与曲线结构", "focus_points": ["DR007", "收益率曲线", "互换", "曲线陡峭化"], "theme_keywords": ["资金面", "回购利率", "收益率曲线", "互换", "流动性"], "priority": 96},
        {"id": "rates_policy_fiscal", "label": "政策供给 Agent", "description": "聚焦货币宽松、财政发力和债券供给。", "agent_type": "policy_supply", "role": "政策与供给约束", "focus_points": ["降准降息", "财政刺激", "国债供给", "地方债"], "theme_keywords": ["降准", "降息", "财政", "国债", "地方债", "特别国债"], "priority": 90},
    ],
}
_THEME_AGENT_MANDATORY_TYPES = {"evidence", "temporal", "market_data", "arbiter"}


def _normalize_theme_agent_definition(agent: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    label = str(agent.get("label", "") or "").strip() or f"自定义Agent{index + 1}"
    agent_id = str(agent.get("id", "") or "").strip() or _slugify_topic_id(label)
    asset_classes = [
        str(item).strip()
        for item in (agent.get("asset_classes") or [])
        if str(item).strip()
    ]
    return {
        "id": agent_id,
        "label": label,
        "description": str(agent.get("description", "") or "").strip(),
        "agent_type": str(agent.get("agent_type", "") or "").strip() or "custom",
        "role": str(agent.get("role", "") or "").strip() or label,
        "asset_classes": asset_classes,
        "theme_keywords": _normalize_topic_keywords(agent.get("theme_keywords", [])),
        "focus_points": _normalize_topic_keywords(agent.get("focus_points", [])),
        "instructions": str(agent.get("instructions", "") or "").strip(),
        "enabled": bool(agent.get("enabled", True)),
        "priority": int(agent.get("priority", 50) or 50),
        "preset_source": str(agent.get("preset_source", "") or "").strip(),
    }


def _default_theme_agent_definitions() -> List[Dict[str, Any]]:
    return [
        _normalize_theme_agent_definition(item, index)
        for index, item in enumerate(_DEFAULT_THEME_AGENT_DEFINITIONS)
    ]


def _merge_theme_agent_definitions(*agent_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged_map: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for group in agent_groups:
        for index, item in enumerate(group or []):
            if not isinstance(item, dict):
                continue
            normalized = _normalize_theme_agent_definition(item, index)
            key = normalized.get("id") or normalized.get("label")
            if key not in order:
                order.append(key)
            merged_map[key] = normalized
    merged = [merged_map[key] for key in order if key in merged_map]
    return sorted(merged, key=lambda item: (-int(item.get("priority", 50) or 50), str(item.get("label") or "")))


def _load_theme_agent_definitions() -> List[Dict[str, Any]]:
    cached = db.cache_get(_THEME_AGENT_CONFIG_CACHE_KEY)
    if not cached:
        return []
    raw_agents = cached
    if isinstance(cached, str):
        try:
            raw_agents = json.loads(cached)
        except Exception:
            raw_agents = []
    if not isinstance(raw_agents, list):
        return []
    return [
        _normalize_theme_agent_definition(item, index)
        for index, item in enumerate(raw_agents)
        if isinstance(item, dict)
    ]


def _save_theme_agent_definitions(agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for index, item in enumerate(agents or []):
        if not isinstance(item, dict):
            continue
        final_item = _normalize_theme_agent_definition(item, index)
        if final_item["id"] in seen_ids:
            final_item["id"] = f"{final_item['id']}-{index + 1}"
        seen_ids.add(final_item["id"])
        normalized.append(final_item)
    db.cache_set(_THEME_AGENT_CONFIG_CACHE_KEY, normalized, expire=0)
    return normalized


def _build_asset_theme_agent_preset_definitions(current_market: str = "", current_code: str = "", theme_label: str = "") -> List[Dict[str, Any]]:
    product_info = _get_product_info(current_code or "", current_market or "") if current_code or current_market else {}
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    theme_text = " ".join(
        [
            str(theme_label or ""),
            str(product_info.get("name_cn") or ""),
            str(product_info.get("name_en") or ""),
            str(product_info.get("symbol") or ""),
        ]
    ).lower()
    presets: List[Dict[str, Any]] = []
    for item in _ASSET_CLASS_THEME_AGENT_PRESETS.get(asset_class, []):
        preset = dict(item)
        preset["asset_classes"] = [asset_class]
        preset["preset_source"] = "asset_default"
        presets.append(preset)
    if asset_class == "fx":
        fx_route = _classify_fx_theme_route(current_code, {"label": theme_label, "description": "", "keywords": []}, product_info)
        pair_profile = fx_route.get("pair_profile", {}) if isinstance(fx_route, dict) else {}
        presets.append(
            {
                "id": "fx_pair_specialist",
                "label": str(pair_profile.get("label") or "货币对专属 Agent"),
                "description": str(pair_profile.get("description") or "聚焦该货币对独有的传导链和失效条件。"),
                "agent_type": "pair_specialist",
                "role": str(pair_profile.get("role") or "货币对结构与特殊机制"),
                "asset_classes": [asset_class],
                "theme_keywords": list(pair_profile.get("theme_keywords") or []),
                "focus_points": list(pair_profile.get("focus_points") or []),
                "instructions": f"优先从 {str(pair_profile.get('pair_code') or current_code or '该货币对')} 的专属机制解释主题，不要把所有外汇主题都当成同一种美元交易。",
                "enabled": True,
                "priority": 95,
                "preset_source": "asset_default",
            }
        )
    if any(keyword in theme_text for keyword in ["战争", "冲突", "袭击", "制裁", "地缘", "特朗普", "关税"]):
        presets.append(
            {
                "id": "macro_geopolitics",
                "label": "地缘事件 Agent",
                "description": "聚焦战争、制裁、讲话和政策冲击如何改变风险偏好。",
                "agent_type": "geopolitics",
                "role": "地缘与政策冲击识别",
                "asset_classes": [asset_class],
                "theme_keywords": ["战争", "冲突", "制裁", "特朗普", "关税", "地缘"],
                "focus_points": ["事件升级", "避险需求", "制裁链条", "政策冲击"],
                "instructions": "优先判断这类主题是一次性冲击还是会持续发酵。",
                "enabled": True,
                "priority": 93,
                "preset_source": "asset_default",
            }
        )
    if any(keyword in theme_text for keyword in ["讲话", "央行", "利率", "非农", "cpi", "pmi", "财报", "业绩"]):
        presets.append(
            {
                "id": "macro_catalyst",
                "label": "催化解释 Agent",
                "description": "聚焦宏观和事件催化是否足以改变资产定价节奏。",
                "agent_type": "catalyst",
                "role": "催化强弱识别",
                "asset_classes": [asset_class],
                "theme_keywords": ["讲话", "央行", "利率", "非农", "CPI", "PMI", "财报", "业绩"],
                "focus_points": ["预期差", "催化强度", "一次性/持续性", "情绪变化"],
                "instructions": "明确给出催化是超预期、符合预期还是低于预期。",
                "enabled": True,
                "priority": 87,
                "preset_source": "asset_default",
            }
        )
    return _merge_theme_agent_definitions(presets)


def _get_theme_agent_definitions(current_market: str = "", current_code: str = "", theme_label: str = "") -> List[Dict[str, Any]]:
    saved_agents = _load_theme_agent_definitions()
    return _merge_theme_agent_definitions(
        _default_theme_agent_definitions(),
        _build_asset_theme_agent_preset_definitions(current_market, current_code, theme_label),
        saved_agents,
    )


def _select_theme_agents(current_market: str, current_code: str, theme_definition: Dict[str, Any], agent_definitions: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    product_info = _get_product_info(current_code or "", current_market or "") if current_market or current_code else {}
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    fx_route = _classify_fx_theme_route(current_code, theme_definition, product_info) if asset_class == "fx" else {}
    theme_terms = {
        str(theme_definition.get("label") or "").strip().lower(),
        str(theme_definition.get("description") or "").strip().lower(),
    }
    theme_terms.update([str(item or "").strip().lower() for item in (theme_definition.get("keywords") or []) if str(item or "").strip()])
    selected: List[Dict[str, Any]] = []
    mandatory_selected: set = set()
    for item in (agent_definitions or _get_theme_agent_definitions(current_market, current_code, str(theme_definition.get("label") or ""))):
        if not item.get("enabled", True):
            continue
        score = 0
        agent_asset_classes = [str(agent_asset).strip().lower() for agent_asset in (item.get("asset_classes") or []) if str(agent_asset).strip()]
        if not agent_asset_classes or asset_class in agent_asset_classes or "all" in agent_asset_classes:
            score += 2
        theme_keywords = [str(keyword).strip().lower() for keyword in (item.get("theme_keywords") or []) if str(keyword).strip()]
        if theme_keywords and any(any(keyword in term for term in theme_terms if term) for keyword in theme_keywords):
            score += 3
        elif not theme_keywords:
            score += 1
        if asset_class == "fx":
            if str(item.get("id") or "") in set(fx_route.get("preferred_agent_ids") or []):
                score += 4
            if str(item.get("agent_type") or "") in set(fx_route.get("preferred_agent_types") or []):
                score += 2
        if str(item.get("agent_type") or "") in _THEME_AGENT_MANDATORY_TYPES:
            score += 3
        if score <= 0:
            continue
        final_item = dict(item)
        final_item["selection_score"] = score
        selected.append(final_item)
        if str(item.get("agent_type") or "") in _THEME_AGENT_MANDATORY_TYPES:
            mandatory_selected.add(final_item["id"])
    selected = sorted(selected, key=lambda item: (-int(item.get("selection_score", 0) or 0), -int(item.get("priority", 50) or 50), str(item.get("label") or "")))
    result: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for item in selected:
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        result.append(item)
        if len(result) >= 7 and mandatory_selected.issubset(seen_ids):
            break
    return result[:8]

def _load_event_topic_definitions() -> List[Dict[str, Any]]:
    cached = db.cache_get(_EVENT_TOPIC_CONFIG_CACHE_KEY)
    if not cached:
        return _default_event_topic_definitions()

    raw_topics = cached
    if isinstance(cached, str):
        try:
            raw_topics = json.loads(cached)
        except Exception:
            raw_topics = []
    if not isinstance(raw_topics, list):
        return _default_event_topic_definitions()

    normalized_topics = [
        _normalize_event_topic_definition(item, index)
        for index, item in enumerate(raw_topics)
        if isinstance(item, dict)
    ]
    return normalized_topics or _default_event_topic_definitions()


def _save_event_topic_definitions(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for index, item in enumerate(topics or []):
        if not isinstance(item, dict):
            continue
        final_item = _normalize_event_topic_definition(item, index)
        if not final_item["keywords"]:
            continue
        if final_item["id"] in seen_ids:
            final_item["id"] = f"{final_item['id']}-{index + 1}"
        seen_ids.add(final_item["id"])
        normalized.append(final_item)
    normalized = normalized or _default_event_topic_definitions()
    db.cache_set(_EVENT_TOPIC_CONFIG_CACHE_KEY, normalized, expire=0)
    return normalized


def _normalize_news_identity(title: str) -> str:
    return re.sub(r"[\W_]+", "", str(title or "").strip().lower())


def _deduplicate_news_details(news_details: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for item in sorted(
        news_details or [],
        key=lambda news: (
            _safe_float(news.get("event_news_score"), 0.0),
            _safe_float(news.get("importance_score"), 0.0),
            str(news.get("published_at", "") or ""),
        ),
        reverse=True,
    ):
        identity = _normalize_news_identity(item.get("title", ""))
        if identity and identity in seen_keys:
            continue
        if identity:
            seen_keys.add(identity)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _match_event_topics(
    event: Dict[str, Any],
    topic_definitions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    combined_text = " ".join(
        [
            str(event.get("storyline", "") or ""),
            str(event.get("cause_summary", "") or ""),
            " ".join(str(item.get("title", "") or "") for item in event.get("event_news_details", []) or []),
            " ".join(str(item.get("summary", "") or "") for item in event.get("event_news_details", []) or []),
            " ".join(str(item.get("impact_reason", "") or "") for item in event.get("event_news_details", []) or []),
        ]
    ).lower()
    matches: List[Dict[str, Any]] = []
    for topic in topic_definitions:
        if not topic.get("enabled", True):
            continue
        keywords = topic.get("keywords", []) or []
        hit_keywords = [keyword for keyword in keywords if keyword.lower() in combined_text]
        if not hit_keywords:
            continue
        matches.append(
            {
                "id": topic["id"],
                "label": topic["label"],
                "description": topic.get("description", ""),
                "matched_keywords": hit_keywords[:5],
                "score": len(hit_keywords),
            }
        )
    matches.sort(key=lambda item: (item["score"], item["label"]), reverse=True)
    if matches:
        return matches[:2]
    fallback_storyline = str(event.get("storyline", "") or "综合驱动")
    return [
        {
            "id": f"storyline-{_slugify_topic_id(fallback_storyline)}",
            "label": fallback_storyline,
            "description": "系统按主线自动归并的主题",
            "matched_keywords": [],
            "score": 0,
        }
    ]


def _build_topic_analysis_summary(topic_label: str, events: List[Dict[str, Any]], representative_news: List[Dict[str, Any]]) -> str:
    event_count = len(events)
    direction_score = sum(
        (_safe_float(item.get("return_pct"), 0.0) if item.get("direction") == "bullish" else -_safe_float(item.get("abs_return_pct"), abs(_safe_float(item.get("return_pct"), 0.0))))
        for item in events
    )
    dominant_label = "偏利多" if direction_score > 0 else "偏利空" if direction_score < 0 else "中性"
    main_news = representative_news[0]["title"] if representative_news else "暂无代表事件"
    return (
        f"主题“{topic_label}”在当前窗口共触发 {event_count} 次关键价格事件，整体影响{dominant_label}。"
        f"代表性驱动为“{main_news}”，同主题重复报道已自动归并。"
    )


def _build_historical_topic_timeline(
    events: List[Dict[str, Any]],
    topic_definitions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for event in events:
        event_news_details = _deduplicate_news_details(list(event.get("event_news_details", []) or []), limit=4)
        topic_matches = _match_event_topics(event, topic_definitions)
        for topic in topic_matches:
            bucket = grouped.setdefault(
                topic["id"],
                {
                    "topic_id": topic["id"],
                    "topic_label": topic["label"],
                    "topic_description": topic.get("description", ""),
                    "matched_keywords": [],
                    "event_count": 0,
                    "latest_trigger_dt": "",
                    "direction_score": 0.0,
                    "headline_events": [],
                    "representative_news_raw": [],
                },
            )
            bucket["event_count"] += 1
            bucket["matched_keywords"].extend(topic.get("matched_keywords", []))
            trigger_dt = event.get("trigger_dt")
            trigger_text = trigger_dt.isoformat() if hasattr(trigger_dt, "isoformat") else str(trigger_dt or "")
            if trigger_text > str(bucket.get("latest_trigger_dt", "") or ""):
                bucket["latest_trigger_dt"] = trigger_text
            move_score = _safe_float(event.get("abs_return_pct"), abs(_safe_float(event.get("return_pct"), 0.0)))
            bucket["direction_score"] += move_score if event.get("direction") == "bullish" else -move_score
            bucket["representative_news_raw"].extend(event_news_details)
            bucket["headline_events"].append(
                {
                    "event_id": event.get("event_id", ""),
                    "trigger_dt": trigger_text,
                    "direction": event.get("direction", "neutral"),
                    "return_pct": round(_safe_float(event.get("return_pct")), 4),
                    "bar_range_pct": round(_safe_float(event.get("bar_range_pct")), 4),
                    "storyline": event.get("storyline", "综合驱动"),
                    "analysis_summary": event.get("cause_summary", "") or f"该主题在该时点触发了{event.get('direction', 'neutral')}价格异动。",
                    "supporting_news": event_news_details[:3],
                }
            )

    timelines: List[Dict[str, Any]] = []
    for item in grouped.values():
        representative_news = _deduplicate_news_details(item.pop("representative_news_raw", []), limit=3)
        impact_label = "偏利多" if item["direction_score"] > 0 else "偏利空" if item["direction_score"] < 0 else "中性"
        item["matched_keywords"] = _normalize_topic_keywords(item.get("matched_keywords", []))[:6]
        item["impact_label"] = impact_label
        item["representative_news"] = representative_news
        item["topic_summary"] = _build_topic_analysis_summary(item["topic_label"], item["headline_events"], representative_news)
        item["headline_events"].sort(key=lambda event: event.get("trigger_dt", ""), reverse=True)
        timelines.append(item)

    timelines.sort(
        key=lambda item: (
            item.get("event_count", 0),
            abs(_safe_float(item.get("direction_score"), 0.0)),
            item.get("latest_trigger_dt", ""),
        ),
        reverse=True,
    )
    return timelines


def _build_realtime_topic_asset_performance(
    current_code: str,
    current_name: str,
    price_state: Dict[str, Any],
    cross_asset_watch: Dict[str, Any],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = [
        {
            "code": current_code,
            "name": current_name or current_code,
            "role": "当前资产",
            "change_5m_pct": round(_safe_float(price_state.get("change_5m_pct")), 4),
            "change_30m_pct": round(_safe_float(price_state.get("change_30m_pct")), 4),
            "status_label": price_state.get("status_label", "等待信号"),
            "alignment_label": price_state.get("status_label", "等待信号"),
        }
    ]
    for item in list((cross_asset_watch or {}).get("items", []) or [])[:3]:
        items.append(
            {
                "code": item.get("code", ""),
                "name": item.get("name") or item.get("code") or "参考资产",
                "role": "联动资产",
                "change_5m_pct": round(_safe_float(item.get("change_5m_pct")), 4),
                "change_30m_pct": round(_safe_float(item.get("change_30m_pct")), 4),
                "status_label": item.get("status_label", ""),
                "alignment_label": item.get("alignment_label", "联动观察"),
            }
        )
    return items


def _build_realtime_topic_timeline(
    current_market: str,
    current_code: str,
    current_name: str,
    price_state: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    direct_news: List[Dict[str, Any]],
    driver_news: List[Dict[str, Any]],
    urgent_alert: Optional[Dict[str, Any]],
    cross_asset_watch: Dict[str, Any],
) -> List[Dict[str, Any]]:
    topic_definitions = _get_asset_event_topic_definitions(current_market, current_code)
    topic_events: List[Dict[str, Any]] = []
    base_return = _safe_float(price_state.get("change_30m_pct"), 0.0)
    base_direction = "bullish" if base_return > 0 else "bearish" if base_return < 0 else "neutral"

    def add_candidate(title: str, summary: str, occurred_at: str, event_news_details: Optional[List[Dict[str, Any]]] = None, storyline: str = "") -> None:
        if not title and not summary:
            return
        topic_events.append(
            {
                "event_id": f"rt_{len(topic_events) + 1}",
                "trigger_dt": occurred_at or datetime.now().isoformat(),
                "direction": base_direction,
                "return_pct": base_return,
                "abs_return_pct": abs(base_return),
                "bar_range_pct": abs(_safe_float(price_state.get("range_60m_pct"), 0.0)),
                "storyline": storyline or "实时主题",
                "cause_summary": summary or title,
                "event_news_details": _deduplicate_news_details(list(event_news_details or []), limit=3),
            }
        )

    if urgent_alert and urgent_alert.get("enabled"):
        add_candidate(
            title=str(urgent_alert.get("cause_title", "") or ""),
            summary=str(urgent_alert.get("cause_summary", "") or ""),
            occurred_at=str(urgent_alert.get("event_time", "") or ""),
            event_news_details=[
                {
                    "title": urgent_alert.get("cause_title", "价格突变归因"),
                    "summary": urgent_alert.get("cause_summary", ""),
                    "impact_label": "偏利多" if base_direction == "bullish" else "偏利空" if base_direction == "bearish" else "中性",
                    "impact_reason": urgent_alert.get("cause_summary", ""),
                    "published_at": urgent_alert.get("event_time", ""),
                    "event_news_score": 12.0,
                }
            ],
            storyline="价格突变归因",
        )

    for item in direct_news[:4]:
        add_candidate(
            title=str(item.get("title", "") or ""),
            summary=str(item.get("summary") or item.get("direction_reason") or ""),
            occurred_at=str(item.get("published_at", "") or ""),
            event_news_details=[
                {
                    "title": item.get("title", "未命名新闻"),
                    "summary": item.get("summary", ""),
                    "impact_label": item.get("impact_label", "中性"),
                    "impact_reason": item.get("direction_reason", ""),
                    "published_at": item.get("published_at", ""),
                    "event_news_score": _safe_float(item.get("importance_score"), 0.0) + 10,
                }
            ],
            storyline=item.get("evidence_label", "直接新闻"),
        )

    for item in driver_news[:4]:
        add_candidate(
            title=str(item.get("title", "") or ""),
            summary=str(item.get("summary") or item.get("direction_reason") or ""),
            occurred_at=str(item.get("published_at", "") or ""),
            event_news_details=[
                {
                    "title": item.get("title", "未命名驱动"),
                    "summary": item.get("summary", ""),
                    "impact_label": item.get("impact_label", "中性"),
                    "impact_reason": item.get("direction_reason", ""),
                    "published_at": item.get("published_at", ""),
                    "event_news_score": _safe_float(item.get("importance_score"), 0.0) + 8,
                }
            ],
            storyline=item.get("evidence_label", "驱动线索"),
        )

    for item in alerts[:4]:
        add_candidate(
            title=str(item.get("title", "") or ""),
            summary=str(item.get("summary", "") or ""),
            occurred_at=str(item.get("occurred_at", "") or ""),
            storyline=item.get("category_label", "实时观察"),
        )

    if not topic_events:
        return []

    timelines = _build_historical_topic_timeline(topic_events, topic_definitions)
    asset_performance = _build_realtime_topic_asset_performance(
        current_code=current_code,
        current_name=current_name,
        price_state=price_state,
        cross_asset_watch=cross_asset_watch,
    )
    for item in timelines:
        item["asset_performance"] = asset_performance
        item["market"] = current_market
        item["current_asset_code"] = current_code
    return timelines[:5]


def _generate_theme_simulation_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    current_market = str(payload.get("current_market", "") or "").strip()
    current_code = _normalize_asset_code(payload.get("current_code", ""))
    theme_label = str(payload.get("theme_label", "") or "").strip()
    lookback_hours = max(6, min(int(payload.get("lookback_hours", 24) or 24), 24 * 30))
    max_news = max(4, min(int(payload.get("max_news", 8) or 8), 20))
    force_refresh = bool(payload.get("force_refresh", False))
    run_id = str(payload.get("run_id", "") or "").strip() or uuid.uuid4().hex[:12]
    generated_at = datetime.now().isoformat()
    uploaded_evidence = _normalize_uploaded_evidence_items(payload.get("uploaded_evidence", []))
    requested_theme_agents = [
        _normalize_theme_agent_definition(item, index)
        for index, item in enumerate(payload.get("theme_agents", []) or [])
        if isinstance(item, dict)
    ]
    if not current_market or not current_code:
        raise ValueError("请先提供市场和资产代码")
    if not theme_label:
        raise ValueError("请先提供主题名称")

    cache_payload = {
        "current_market": current_market,
        "current_code": current_code,
        "theme_label": theme_label,
        "lookback_hours": lookback_hours,
        "max_news": max_news,
        "uploaded_evidence_digest": hashlib.md5(
            json.dumps(
                [
                    {
                        "evidence_id": item.get("evidence_id"),
                        "title": item.get("title"),
                        "summary": item.get("summary"),
                    }
                    for item in uploaded_evidence
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "theme_agents_digest": hashlib.md5(
            json.dumps(requested_theme_agents, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    cached_result = None if force_refresh else _load_summary_result_cache("theme_simulation", cache_payload)
    if cached_result:
        cached_result["run_id"] = str(cached_result.get("run_id") or run_id)
        cached_result["generated_at"] = str(cached_result.get("generated_at") or generated_at)
        cached_result["analysis_scope"] = dict(cached_result.get("analysis_scope") or {})
        cached_result["analysis_scope"]["is_new_run"] = False
        cached_result["analysis_scope"]["force_refresh"] = False
        return cached_result

    product_info = _get_product_info(current_code, current_market)
    price_state = _summarize_realtime_price_state(current_market, current_code)
    cross_asset_watch = _build_cross_asset_watch(
        current_market=current_market,
        current_code=current_code,
        current_price_state=price_state,
        product_info=product_info,
    )
    theme_definition = resolve_theme_definition(theme_label, _get_asset_event_topic_definitions(current_market, current_code))
    themed_news = _build_theme_related_news_response(
        theme_definition=theme_definition,
        asset_code=current_code,
        market=current_market,
        lookback_hours=lookback_hours,
        limit=max_news,
        product_info=product_info,
    )
    fx_profile = _build_fx_market_data_profile(current_code, product_info) if _resolve_market_data_asset_class(current_market, product_info) == "fx" else {}
    fx_route = _classify_fx_theme_route(current_code, theme_definition, product_info) if fx_profile else {}
    asset_context = {
        "current_market": current_market,
        "current_code": current_code,
        "asset_name": product_info.get("name_cn") or product_info.get("name_en") or current_code,
        "asset_type": product_info.get("type", ""),
        "price_direction": price_state.get("direction", "neutral"),
        "latest_price": price_state.get("latest_price"),
        "latest_change_pct": price_state.get("change_30m_pct", 0.0),
        "status_label": price_state.get("status_label", ""),
        "base_currency": fx_profile.get("base_currency", ""),
        "quote_currency": fx_profile.get("quote_currency", ""),
        "fx_theme_route": fx_route.get("theme_type", ""),
        "fx_theme_route_label": fx_route.get("label", ""),
    }
    market_data_snapshot = _build_market_data_view_payload(current_market, current_code, limit=6)
    market_data_digest = _summarize_market_data_snapshot(market_data_snapshot)
    theme_agent_definitions = _get_theme_agent_definitions(current_market, current_code, theme_label)
    if requested_theme_agents:
        theme_agent_definitions = _merge_theme_agent_definitions(theme_agent_definitions, requested_theme_agents)
    selected_theme_agents = _select_theme_agents(
        current_market=current_market,
        current_code=current_code,
        theme_definition=theme_definition,
        agent_definitions=theme_agent_definitions,
    )
    toolkit_payload = _build_theme_research_agent_payload(
        theme_definition=theme_definition,
        asset_context=asset_context,
        asset_code=current_code,
        lookback_hours=lookback_hours,
        max_news=max_news,
        cross_asset_watch=cross_asset_watch,
        base_buckets=themed_news.get("buckets", {}),
        uploaded_evidence=uploaded_evidence,
    )
    temporal_evidence = _build_theme_temporal_evidence(
        market=current_market,
        code=current_code,
        theme_news=toolkit_payload.get("theme_news", []),
        frequency="5m",
    )
    toolkit_payload["theme_news"] = temporal_evidence.get("enriched_news", toolkit_payload.get("theme_news", []))
    toolkit_payload["temporal_evidence"] = temporal_evidence
    toolkit_payload["market_data_snapshot"] = market_data_snapshot
    multi_agent_panel = _build_theme_multi_agent_panel(
        theme_definition=theme_definition,
        asset_context=asset_context,
        toolkit_payload=toolkit_payload,
        temporal_evidence=temporal_evidence,
        market_data_snapshot=market_data_snapshot,
        cross_asset_watch=cross_asset_watch,
        agent_definitions=selected_theme_agents,
    )
    toolkit_payload["theme_multi_agent_panel"] = multi_agent_panel
    comprehensive_reasoning = _build_comprehensive_reasoning_payload(
        theme_definition=theme_definition,
        asset_context=asset_context,
        current_price_state=price_state,
        temporal_evidence=temporal_evidence,
        market_data_snapshot=market_data_snapshot,
        cross_asset_watch=cross_asset_watch,
        theme_multi_agent_panel=multi_agent_panel,
        product_info=product_info,
    )
    toolkit_payload["comprehensive_reasoning"] = comprehensive_reasoning
    research_tools = list(toolkit_payload.get("research_tools", []) or [])
    research_tools.insert(
        1,
        {
            "tool": "temporal_market_reaction",
            "label": "时间性与真实定价",
            "summary": temporal_evidence.get("summary", ""),
            "highlights": [
                temporal_evidence.get("freshness_label", ""),
                f"方向一致率 {float(temporal_evidence.get('alignment_rate', 0.0)) * 100:.0f}%",
                f"新闻后30分钟均值 {float(temporal_evidence.get('avg_follow_30m_pct', 0.0)):+.3f}%",
                f"2小时均值 {float(temporal_evidence.get('avg_follow_120m_pct', 0.0)):+.3f}%",
                f"6小时主导波动 {float(temporal_evidence.get('avg_dominant_move_pct', 0.0)):.3f}%",
            ],
            "confidence": 0.82 if temporal_evidence.get("reaction_count", 0) else 0.35,
        },
    )
    if market_data_digest.get("summary"):
        research_tools.insert(
            2,
            {
                "tool": "market_data_foundation",
                "label": "市场数据底座",
                "summary": market_data_digest.get("summary", ""),
                "highlights": market_data_digest.get("highlights", []),
                "confidence": 0.78,
            },
        )
    if multi_agent_panel.get("arbiter", {}).get("summary"):
        research_tools.insert(
            3,
            {
                "tool": "theme_multi_agent_arbiter",
                "label": "多 Agent 裁决",
                "summary": str((multi_agent_panel.get("arbiter") or {}).get("summary") or ""),
                "highlights": list((multi_agent_panel.get("arbiter") or {}).get("findings") or [])[:3],
                "confidence": _safe_float((multi_agent_panel.get("arbiter") or {}).get("confidence"), 0.72),
            },
        )
    if comprehensive_reasoning.get("summary"):
        research_tools.insert(
            4,
            {
                "tool": "comprehensive_reasoning",
                "label": "全面推演骨架",
                "summary": str(comprehensive_reasoning.get("summary") or ""),
                "highlights": [
                    "路由：" + str((comprehensive_reasoning.get("router") or {}).get("route_label") or "均衡观察"),
                    "跨资产：" + str((comprehensive_reasoning.get("cross_asset_evidence") or {}).get("regime_label") or "待确认"),
                    "定价阶段：" + str((comprehensive_reasoning.get("arbiter_execution") or {}).get("pricing_stage") or "待确认"),
                ],
                "confidence": _safe_float((comprehensive_reasoning.get("arbiter_execution") or {}).get("conviction_score"), 0.62),
            },
        )
    toolkit_payload["research_tools"] = research_tools[:8]
    asset_context["temporal_reaction_summary"] = temporal_evidence.get("summary", "")
    asset_context["temporal_alignment_rate"] = temporal_evidence.get("alignment_rate", 0.0)
    asset_context["latest_news_minutes"] = temporal_evidence.get("latest_news_minutes")
    asset_context["market_data_summary"] = market_data_digest.get("summary", "")
    asset_context["market_data_highlights"] = market_data_digest.get("highlights", [])
    asset_context["market_data_event_count"] = int((market_data_snapshot.get("summary") or {}).get("event_count", 0) or 0)
    asset_context["market_data_factor_count"] = int((market_data_snapshot.get("summary") or {}).get("factor_count", 0) or 0)
    asset_context["market_data_metric_count"] = int((market_data_snapshot.get("summary") or {}).get("metric_count", 0) or 0)
    asset_context["market_data_reaction_count"] = int((market_data_snapshot.get("summary") or {}).get("reaction_count", 0) or 0)
    asset_context["theme_agent_consensus"] = str((multi_agent_panel.get("consensus") or {}).get("stance") or "")
    asset_context["theme_agent_arbiter_summary"] = str((multi_agent_panel.get("arbiter") or {}).get("summary") or "")
    asset_context["comprehensive_route_label"] = str((comprehensive_reasoning.get("router") or {}).get("route_label") or "")
    asset_context["cross_asset_regime_label"] = str((comprehensive_reasoning.get("cross_asset_evidence") or {}).get("regime_label") or "")
    asset_context["cross_asset_confirmation_score"] = _safe_float((comprehensive_reasoning.get("cross_asset_evidence") or {}).get("confirmation_score"), 0.0)
    asset_context["pricing_stage"] = str((comprehensive_reasoning.get("arbiter_execution") or {}).get("pricing_stage") or "")
    asset_context["execution_bias"] = str((comprehensive_reasoning.get("arbiter_execution") or {}).get("execution_bias") or "")
    ontology = build_theme_ontology(
        theme_definition=theme_definition,
        asset_context=asset_context,
        entities=toolkit_payload.get("entities", []),
        propagation_chain=toolkit_payload.get("propagation_chain", []),
        actor_profiles=toolkit_payload.get("actor_profiles", []),
        cross_asset_signals=toolkit_payload.get("cross_asset_signals", []),
    )
    retrieval_summary = {
        "lookback_hours": lookback_hours,
        "search_terms": themed_news.get("theme_search_terms", []),
        "searched_news_count": themed_news.get("searched_news_count", 0),
        "supplemental_news_count": toolkit_payload.get("supplemental_news_count", 0),
        "agent_rounds_completed": toolkit_payload.get("rounds_completed", 0),
        "uploaded_evidence_count": len(uploaded_evidence),
        "temporal_reaction_count": temporal_evidence.get("reaction_count", 0),
        "temporal_alignment_rate": temporal_evidence.get("alignment_rate", 0.0),
        "research_digest": toolkit_payload.get("research_digest", ""),
        "market_data_event_count": int((market_data_snapshot.get("summary") or {}).get("event_count", 0) or 0),
        "market_data_factor_count": int((market_data_snapshot.get("summary") or {}).get("factor_count", 0) or 0),
        "market_data_metric_count": int((market_data_snapshot.get("summary") or {}).get("metric_count", 0) or 0),
        "market_data_reaction_count": int((market_data_snapshot.get("summary") or {}).get("reaction_count", 0) or 0),
        "theme_agent_count": len(multi_agent_panel.get("active_agents", []) or []),
        "theme_agent_consensus": str((multi_agent_panel.get("consensus") or {}).get("stance") or ""),
        "comprehensive_route_label": str((comprehensive_reasoning.get("router") or {}).get("route_label") or ""),
        "cross_asset_confirmation_score": _safe_float((comprehensive_reasoning.get("cross_asset_evidence") or {}).get("confirmation_score"), 0.0),
        "pricing_stage": str((comprehensive_reasoning.get("arbiter_execution") or {}).get("pricing_stage") or ""),
    }
    research_memory = _load_theme_research_memory(
        current_market=current_market,
        current_code=current_code,
        theme_definition=theme_definition,
    )
    report = build_theme_reasoning_report(
        theme_definition=theme_definition,
        asset_context=asset_context,
        theme_news=toolkit_payload.get("theme_news", []),
        propagation_chain=toolkit_payload.get("propagation_chain", []),
        ontology=ontology,
        retrieval_summary=retrieval_summary,
        research_payload=toolkit_payload,
        research_memory=research_memory,
    )
    research_memory = _save_theme_research_memory(
        current_market=current_market,
        current_code=current_code,
        theme_definition=theme_definition,
        report=report,
        toolkit_payload=toolkit_payload,
        retrieval_summary=retrieval_summary,
    )
    asset_performance = _build_realtime_topic_asset_performance(
        current_code=current_code,
        current_name=asset_context["asset_name"],
        price_state=price_state,
        cross_asset_watch=cross_asset_watch,
    )
    research_agent = dict(report.get("research_agent") or {})
    if research_memory:
        research_agent["memory_snapshot"] = research_memory
        research_agent["memory_summary"] = str(research_memory.get("memory_summary") or research_agent.get("memory_summary") or "")
    report["research_agent"] = research_agent
    result = {
        "run_id": run_id,
        "generated_at": generated_at,
        "theme": theme_definition,
        "asset_context": asset_context,
        "price_state": price_state,
        "asset_performance": asset_performance,
        "news_counts": {
            "direct": len(toolkit_payload.get("direct_theme_news", [])),
            "driver": len(toolkit_payload.get("driver_theme_news", [])),
            "background": len(toolkit_payload.get("background_theme_news", [])),
            "uploaded": len(toolkit_payload.get("uploaded_theme_evidence", [])),
            "searched": int(themed_news.get("searched_news_count", 0) or 0),
            "supplemental": int(toolkit_payload.get("supplemental_news_count", 0) or 0),
        },
        "theme_news": toolkit_payload.get("theme_news", []),
        "uploaded_evidence": toolkit_payload.get("uploaded_theme_evidence", []),
        "entities": toolkit_payload.get("entities", []),
        "propagation_chain": toolkit_payload.get("propagation_chain", []),
        "ontology": ontology,
        "report": report,
        "research_agent": research_agent,
        "research_memory": research_memory,
        "temporal_evidence": temporal_evidence,
        "market_data_snapshot": market_data_snapshot,
        "theme_agent_panel": multi_agent_panel,
        "comprehensive_reasoning": comprehensive_reasoning,
        "analysis_scope": {
            "lookback_hours": lookback_hours,
            "max_news": max_news,
            "theme_source": theme_definition.get("source", ""),
            "theme_search_terms": themed_news.get("theme_search_terms", []),
            "agent_rounds_completed": int(toolkit_payload.get("rounds_completed", 0) or 0),
            "uploaded_evidence_count": len(toolkit_payload.get("uploaded_theme_evidence", [])),
            "temporal_reaction_count": int(temporal_evidence.get("reaction_count", 0) or 0),
            "temporal_alignment_rate": float(temporal_evidence.get("alignment_rate", 0.0) or 0.0),
            "market_data_event_count": int((market_data_snapshot.get("summary") or {}).get("event_count", 0) or 0),
            "market_data_factor_count": int((market_data_snapshot.get("summary") or {}).get("factor_count", 0) or 0),
            "market_data_metric_count": int((market_data_snapshot.get("summary") or {}).get("metric_count", 0) or 0),
            "market_data_reaction_count": int((market_data_snapshot.get("summary") or {}).get("reaction_count", 0) or 0),
            "theme_agent_count": len(multi_agent_panel.get("active_agents", []) or []),
            "theme_agent_labels": [str(item.get("label") or "") for item in (multi_agent_panel.get("active_agents") or [])[:8] if str(item.get("label") or "").strip()],
            "theme_agent_consensus": str((multi_agent_panel.get("consensus") or {}).get("stance") or ""),
            "comprehensive_route_label": str((comprehensive_reasoning.get("router") or {}).get("route_label") or ""),
            "cross_asset_confirmation_score": _safe_float((comprehensive_reasoning.get("cross_asset_evidence") or {}).get("confirmation_score"), 0.0),
            "pricing_stage": str((comprehensive_reasoning.get("arbiter_execution") or {}).get("pricing_stage") or ""),
            "is_new_run": True,
            "force_refresh": force_refresh,
            "manual_trigger_only": True,
        },
    }
    _save_summary_result_cache("theme_simulation", cache_payload, result)
    return result


_ASSET_STORYLINE_TEMPLATES = {
    "USDCNY": {
        "focus": "优先关注人民币汇率政策、中美关系、美元强弱与风险溢价变化",
        "weights": {
            "政策监管": 1.45,
            "央行与利率": 1.25,
            "风险情绪": 1.15,
            "宏观数据": 1.0,
            "地缘政治": 0.95,
            "商品供给": 0.55,
        },
    },
    "EURUSD": {
        "focus": "优先关注美联储/欧洲央行利率路径、欧美宏观数据差与美元方向",
        "weights": {
            "央行与利率": 1.5,
            "宏观数据": 1.3,
            "风险情绪": 1.05,
            "地缘政治": 0.95,
            "政策监管": 0.8,
            "商品供给": 0.55,
        },
    },
    "XAU": {
        "focus": "优先关注避险需求、实际利率、美元方向与地缘政治冲击",
        "weights": {
            "风险情绪": 1.35,
            "地缘政治": 1.3,
            "央行与利率": 1.15,
            "宏观数据": 0.95,
            "商品供给": 0.8,
            "政策监管": 0.7,
        },
    },
    "CL": {
        "focus": "优先关注供给扰动、中东局势、库存/OPEC 与全球需求预期",
        "weights": {
            "商品供给": 1.55,
            "地缘政治": 1.2,
            "宏观数据": 1.0,
            "风险情绪": 0.85,
            "政策监管": 0.8,
            "央行与利率": 0.65,
        },
    },
    "USDJPY": {
        "focus": "优先关注美日利差、避险偏好、BOJ 政策与亚太地缘风险",
        "weights": {
            "央行与利率": 1.4,
            "风险情绪": 1.25,
            "地缘政治": 1.0,
            "宏观数据": 0.95,
            "政策监管": 0.7,
            "商品供给": 0.45,
        },
    },
}


def _get_asset_storyline_template(asset_code: Optional[str], market: str) -> Dict[str, Any]:
    normalized = _normalize_asset_code(asset_code)
    template = _ASSET_STORYLINE_TEMPLATES.get(normalized)
    if template:
        return template
    if market == "fx":
        return {
            "focus": "优先关注利率、宏观数据、美元方向与风险情绪",
            "weights": {"央行与利率": 1.2, "宏观数据": 1.1, "风险情绪": 1.0, "地缘政治": 0.9, "政策监管": 0.85, "商品供给": 0.5},
        }
    if market == "futures":
        return {
            "focus": "优先关注供给、地缘政治、宏观需求与政策扰动",
            "weights": {"商品供给": 1.2, "地缘政治": 1.1, "宏观数据": 1.0, "政策监管": 0.9, "风险情绪": 0.8, "央行与利率": 0.65},
        }
    return {
        "focus": "关注宏观数据、政策、情绪与地缘政治的综合影响",
        "weights": {label: 1.0 for label in _STORYLINE_KEYWORD_MAP.keys()},
    }


def _get_storyline_priority_weight(asset_code: Optional[str], market: str, storyline: str) -> float:
    template = _get_asset_storyline_template(asset_code, market)
    return float(template.get("weights", {}).get(storyline, 1.0))


def _get_storyline_keywords(storyline: str) -> List[str]:
    return list(_STORYLINE_KEYWORD_MAP.get(storyline, []))


def _derive_storyline_label(
    event_news: List[Dict[str, Any]],
    asset_code: Optional[str] = None,
    market: str = "",
) -> str:
    text = " ".join(
        f"{item.get('metadata', {}).get('title', '')} {item.get('document', '')}"
        for item in event_news[:10]
    ).lower()
    best_label = "综合驱动"
    best_score = 0.0
    for label, keywords in _STORYLINE_KEYWORD_MAP.items():
        hit_count = sum(1 for keyword in keywords if keyword.lower() in text)
        if hit_count <= 0:
            continue
        score = hit_count * _get_storyline_priority_weight(asset_code, market, label)
        if score > best_score:
            best_label = label
            best_score = score
    if best_score > 0:
        return best_label
    return "综合驱动"


def _collect_event_news(
    event: Dict[str, Any],
    current_market: str,
    current_code: str,
    query: str,
    product_info: Optional[Dict[str, Any]],
    stock_info: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    search_terms = _build_news_search_terms(
        query=query,
        product_code=current_code,
        product_info=product_info,
        stock_info=stock_info,
    )[:20]
    canonical_asset = _normalize_asset_code(current_code)
    news_items = _search_news_from_relational_db(
        query=query,
        search_terms=search_terms,
        start_date=event["window_start"],
        end_date=event["window_end"],
        n_results=40,
    )

    enriched_items = []
    for item in news_items:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {}
        direct_assets = _extract_metadata_asset_list(metadata, "direct_assets")
        driver_assets = _extract_metadata_asset_list(metadata, "driver_assets")
        direction_info = infer_asset_impact_direction(
            title=metadata.get("title", ""),
            body=item.get("document", ""),
            canonical_asset=canonical_asset,
        )
        relation_type = "background"
        relation_weight = 0.45
        if canonical_asset and canonical_asset in direct_assets:
            relation_type = "direct"
            relation_weight = 1.0
        elif canonical_asset and canonical_asset in driver_assets:
            relation_type = "driver"
            relation_weight = 0.75

        published_at = _parse_datetime_like(metadata.get("published_at"))
        time_weight = 0.5
        if published_at is not None:
            minutes_delta = abs((published_at - event["trigger_dt"]).total_seconds()) / 60
            time_weight = max(0.2, 1.0 - min(minutes_delta / max((event["window_end"] - event["window_start"]).total_seconds() / 60, 1), 0.8))

        importance_weight = _safe_float(metadata.get("importance_score", 0.0), 0.0)
        item["impact_direction"] = direction_info.get("impact_direction", "neutral")
        item["direction_score"] = direction_info.get("direction_score", 0.0)
        item["direction_reason"] = direction_info.get("reason", "")
        item["event_relation_type"] = relation_type
        item["event_news_score"] = round(relation_weight * 10 + time_weight * 4 + importance_weight, 4)
        enriched_items.append(item)

    enriched_items.sort(
        key=lambda item: (
            item.get("event_news_score", 0.0),
            item.get("metadata", {}).get("published_at", ""),
        ),
        reverse=True,
    )
    return enriched_items[:12]


def _format_historical_event_news_item(news: Dict[str, Any]) -> Dict[str, Any]:
    metadata = news.get("metadata", {}) if isinstance(news.get("metadata", {}), dict) else {}
    body = re.sub(r"\s+", " ", str(news.get("document") or metadata.get("title") or "")).strip()
    summary = body[:120] + "..." if len(body) > 120 else body
    relation_type = str(news.get("event_relation_type", "background") or "background")
    impact_direction = str(news.get("impact_direction", "neutral") or "neutral")
    return {
        "title": metadata.get("title") or "未命名新闻",
        "source": metadata.get("source", ""),
        "published_at": metadata.get("published_at", ""),
        "published_at_label": _format_focus_time_label(metadata.get("published_at", "")),
        "event_relation_type": relation_type,
        "event_relation_label": {
            "direct": "直接新闻",
            "driver": "驱动线索",
            "background": "背景线索",
        }.get(relation_type, "背景线索"),
        "impact_direction": impact_direction,
        "impact_label": {
            "bullish": "偏利多",
            "bearish": "偏利空",
            "neutral": "中性",
        }.get(impact_direction, "中性"),
        "impact_reason": str(news.get("direction_reason", "") or ""),
        "summary": summary,
        "importance_score": round(_safe_float(metadata.get("importance_score", 0.0)), 4),
        "event_news_score": round(_safe_float(news.get("event_news_score", 0.0)), 4),
    }


def _build_historical_event_cause_summary(event: Dict[str, Any]) -> str:
    news_details = list(event.get("event_news_details", []) or [])
    if news_details:
        top_news = news_details[0]
        reason = top_news.get("impact_reason") or top_news.get("summary") or "新闻内容与价格异动时间接近。"
        return (
            f"本次波动主要受{top_news.get('event_relation_label', '相关新闻')}“{top_news.get('title', '未命名新闻')}”影响，"
            f"对该资产判断为{top_news.get('impact_label', '中性')}；{reason}"
        )
    storyline = str(event.get("storyline", "") or "综合驱动")
    return f"事件窗口内未找到足够强的直接新闻证据，当前更像“{storyline}”主线下的价格自发扩散或多因素共振。"


def _build_historical_storylines(
    events: List[Dict[str, Any]],
    asset_code: Optional[str] = None,
    market: str = "",
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for event in events:
        label = event.get("storyline", "综合驱动")
        bucket = grouped.setdefault(
            label,
            {
                "storyline": label,
                "event_count": 0,
                "dominant_direction_score": 0.0,
                "total_abs_move": 0.0,
                "unpriced_count": 0,
                "partial_count": 0,
                "absorbed_count": 0,
                "total_news_count": 0,
                "headline_examples": [],
            },
        )
        bucket["event_count"] += 1
        bucket["dominant_direction_score"] += event.get("direction_sign", 1) * event.get("abs_return_pct", 0.0)
        bucket["total_abs_move"] += event.get("abs_return_pct", 0.0)
        bucket["total_news_count"] += event.get("news_count", 0)
        if event.get("absorption_status") == "not_fully_priced":
            bucket["unpriced_count"] += 1
        elif event.get("absorption_status") == "partially_absorbed":
            bucket["partial_count"] += 1
        else:
            bucket["absorbed_count"] += 1
        top_title = ""
        if event.get("top_news_titles"):
            top_title = event["top_news_titles"][0]
        if top_title and top_title not in bucket["headline_examples"]:
            bucket["headline_examples"].append(top_title)

    storylines = []
    for item in grouped.values():
        if item["dominant_direction_score"] > 0:
            direction = "偏利多"
        elif item["dominant_direction_score"] < 0:
            direction = "偏利空"
        else:
            direction = "中性"
        strength_score = (
            item["event_count"] * 1.4
            + item["total_abs_move"] * 1.8
            + item["unpriced_count"] * 1.6
            + item["partial_count"] * 0.8
            + min(item["total_news_count"], 10) * 0.25
        )
        template_weight = _get_storyline_priority_weight(asset_code, market, item["storyline"])
        strength_score *= template_weight
        storylines.append(
            {
                "storyline": item["storyline"],
                "event_count": item["event_count"],
                "direction": direction,
                "total_abs_move": round(item["total_abs_move"], 4),
                "strength_score": round(strength_score, 4),
                "template_weight": round(template_weight, 3),
                "unpriced_count": item["unpriced_count"],
                "partial_count": item["partial_count"],
                "absorbed_count": item["absorbed_count"],
                "total_news_count": item["total_news_count"],
                "headline_examples": item["headline_examples"][:3],
            }
        )

    storylines.sort(
        key=lambda item: (item["strength_score"], item["event_count"], item["total_abs_move"]),
        reverse=True,
    )
    return storylines


def _estimate_price_reaction_around_time(
    market: str,
    code: str,
    frequency: str,
    anchor_dt: datetime,
) -> Optional[Dict[str, Any]]:
    if isinstance(anchor_dt, datetime) and anchor_dt.tzinfo is not None:
        anchor_dt = anchor_dt.replace(tzinfo=None)
    frequency_minutes = max(_frequency_to_minutes(frequency), 5)
    pre_buffer_minutes = max(frequency_minutes * 6, 30)
    post_buffer_minutes = max(frequency_minutes * 72, 360)
    age_hours = max(int((datetime.now().replace(tzinfo=None) - anchor_dt.replace(tzinfo=None)).total_seconds() / 3600.0), 0)
    bars = _load_historical_price_bars(
        market=market,
        code=code,
        frequency=frequency,
        lookback_hours=max(age_hours + 8, 24),
        purpose="事件跟踪",
    )
    normalized_bars = []
    for bar in bars:
        dt_value = bar.get("dt")
        if isinstance(dt_value, datetime) and dt_value.tzinfo is not None:
            dt_value = dt_value.replace(tzinfo=None)
        if not isinstance(dt_value, datetime):
            continue
        normalized_bar = dict(bar)
        normalized_bar["dt"] = dt_value
        normalized_bars.append(normalized_bar)
    bars = normalized_bars
    relevant_bars = [
        bar for bar in bars
        if anchor_dt - timedelta(minutes=pre_buffer_minutes) <= bar["dt"] <= anchor_dt + timedelta(minutes=post_buffer_minutes)
    ]
    if len(relevant_bars) < 3:
        query_rows = db.klines_query(
            market=market,
            code=code,
            frequency=frequency,
            start_date=anchor_dt - timedelta(minutes=pre_buffer_minutes),
            end_date=anchor_dt + timedelta(minutes=post_buffer_minutes),
            limit=max(int((pre_buffer_minutes + post_buffer_minutes) / max(frequency_minutes, 1)) + 12, 60),
            order="asc",
        )
        relevant_bars = [
            {
                "dt": getattr(row, "dt", None).replace(tzinfo=None) if getattr(row, "dt", None) is not None and getattr(row, "dt", None).tzinfo is not None else getattr(row, "dt", None),
                "open": _safe_float(getattr(row, "o", None)),
                "close": _safe_float(getattr(row, "c", None)),
                "high": _safe_float(getattr(row, "h", None)),
                "low": _safe_float(getattr(row, "l", None)),
                "volume": _safe_float(getattr(row, "v", None)),
            }
            for row in query_rows
            if getattr(row, "dt", None) is not None
        ]
    normalized_relevant_bars = []
    for bar in relevant_bars:
        dt_value = bar.get("dt")
        if isinstance(dt_value, datetime) and dt_value.tzinfo is not None:
            dt_value = dt_value.replace(tzinfo=None)
        if not isinstance(dt_value, datetime):
            continue
        normalized_bar = dict(bar)
        normalized_bar["dt"] = dt_value
        normalized_relevant_bars.append(normalized_bar)
    relevant_bars = normalized_relevant_bars
    if len(relevant_bars) < 3:
        return None

    relevant_bars = sorted(relevant_bars, key=lambda item: item["dt"])
    pre_bars = [bar for bar in relevant_bars if bar["dt"] <= anchor_dt]
    post_bars = [bar for bar in relevant_bars if bar["dt"] >= anchor_dt]
    if not post_bars:
        return None
    reference_candidates = pre_bars[-min(len(pre_bars), 3):] if pre_bars else [post_bars[0]]
    reference_price = sum(_safe_float(item.get("close"), 0.0) for item in reference_candidates) / max(len(reference_candidates), 1)
    reference_price = max(abs(reference_price), 1e-9)
    trigger_bar = post_bars[0]
    delay_minutes = max((trigger_bar["dt"] - anchor_dt).total_seconds() / 60.0, 0.0)

    def _pick_forward_bar(target_minutes: int) -> Dict[str, Any]:
        target_dt = anchor_dt + timedelta(minutes=target_minutes)
        for bar in post_bars:
            if bar["dt"] >= target_dt:
                return bar
        return post_bars[-1]

    future_30_bar = _pick_forward_bar(30)
    future_120_bar = _pick_forward_bar(120)
    future_360_bar = _pick_forward_bar(360)
    event_window_bars = [bar for bar in post_bars if bar["dt"] <= anchor_dt + timedelta(minutes=360)] or post_bars
    initial_move_pct = ((_safe_float(trigger_bar["close"]) - reference_price) / reference_price) * 100
    follow_30m_pct = ((_safe_float(future_30_bar["close"]) - reference_price) / reference_price) * 100
    follow_120m_pct = ((_safe_float(future_120_bar["close"]) - reference_price) / reference_price) * 100
    follow_360m_pct = ((_safe_float(future_360_bar["close"]) - reference_price) / reference_price) * 100
    max_up_pct = ((max(_safe_float(bar.get("high"), 0.0) for bar in event_window_bars) - reference_price) / reference_price) * 100
    max_down_pct = ((min(_safe_float(bar.get("low"), reference_price) for bar in event_window_bars) - reference_price) / reference_price) * 100
    dominant_move_pct = max_up_pct if abs(max_up_pct) >= abs(max_down_pct) else max_down_pct
    if abs(dominant_move_pct) < max(0.03, abs(initial_move_pct) * 0.5):
        direction = "neutral"
    else:
        direction = "bullish" if dominant_move_pct > 0 else "bearish"
    event_shape = {
        "direction_sign": 0 if direction == "neutral" else (1 if direction == "bullish" else -1),
        "abs_return_pct": abs(dominant_move_pct),
        "follow_30m_pct": follow_30m_pct,
        "follow_120m_pct": follow_120m_pct,
    }
    absorption = _assess_event_absorption(event_shape)
    return {
        "return_pct": round(initial_move_pct, 4),
        "follow_30m_pct": round(follow_30m_pct, 4),
        "follow_120m_pct": round(follow_120m_pct, 4),
        "follow_360m_pct": round(follow_360m_pct, 4),
        "max_up_pct": round(max_up_pct, 4),
        "max_down_pct": round(max_down_pct, 4),
        "dominant_move_pct": round(dominant_move_pct, 4),
        "anchor_delay_minutes": round(delay_minutes, 1),
        "absorption_status": absorption["status"],
        "absorption_reason": absorption["reason"],
        "direction": direction,
    }


def _build_reaction_direction_label(direction: str) -> str:
    return {
        "bullish": "新闻后价格偏上行",
        "bearish": "新闻后价格偏下行",
        "neutral": "新闻后价格偏震荡",
    }.get(str(direction or "").lower(), "新闻后价格偏震荡")


def _build_theme_temporal_evidence(
    market: str,
    code: str,
    theme_news: List[Dict[str, Any]],
    frequency: str = "5m",
) -> Dict[str, Any]:
    enriched_news: List[Dict[str, Any]] = []
    aligned_count = 0
    reaction_count = 0
    followthrough_30m_samples: List[float] = []
    followthrough_120m_samples: List[float] = []
    followthrough_360m_samples: List[float] = []
    dominant_move_samples: List[float] = []
    latest_news_minutes: Optional[float] = None
    now_dt = datetime.now().replace(tzinfo=None)
    for item in theme_news or []:
        enriched = dict(item)
        published_at = _parse_datetime_like(item.get("published_at"))
        if isinstance(published_at, datetime):
            published_at = published_at.replace(tzinfo=None)
        reaction = None
        if published_at is not None:
            reaction = _estimate_price_reaction_around_time(
                market=market,
                code=code,
                frequency=frequency,
                anchor_dt=published_at,
            )
            age_minutes = max((now_dt - published_at).total_seconds() / 60.0, 0.0)
            latest_news_minutes = age_minutes if latest_news_minutes is None else min(latest_news_minutes, age_minutes)
            enriched["minutes_since_publish"] = round(age_minutes, 1)
        if reaction:
            reaction_count += 1
            followthrough_30m_samples.append(_safe_float(reaction.get("follow_30m_pct"), 0.0))
            followthrough_120m_samples.append(_safe_float(reaction.get("follow_120m_pct"), 0.0))
            followthrough_360m_samples.append(_safe_float(reaction.get("follow_360m_pct"), 0.0))
            dominant_move_samples.append(abs(_safe_float(reaction.get("dominant_move_pct"), 0.0)))
            impact_direction = str(item.get("impact_direction") or "neutral").lower()
            aligned = impact_direction in {"bullish", "bearish"} and impact_direction == str(reaction.get("direction") or "").lower()
            if aligned:
                aligned_count += 1
            enriched["price_reaction"] = reaction
            enriched["reaction_aligned"] = aligned
            enriched["reaction_label"] = _build_reaction_direction_label(reaction.get("direction"))
            enriched["reaction_summary"] = (
                f"{_build_reaction_direction_label(reaction.get('direction'))}，"
                f"首波 {float(reaction.get('return_pct', 0.0)):+.3f}% ，"
                f"30分钟 {float(reaction.get('follow_30m_pct', 0.0)):+.3f}% ，"
                f"120分钟 {float(reaction.get('follow_120m_pct', 0.0)):+.3f}% ，"
                f"6小时主导波动 {float(reaction.get('dominant_move_pct', 0.0)):+.3f}% 。"
            )
        enriched_news.append(enriched)
    alignment_rate = (aligned_count / reaction_count) if reaction_count else 0.0
    avg_follow_30m = (sum(followthrough_30m_samples) / len(followthrough_30m_samples)) if followthrough_30m_samples else 0.0
    avg_follow_120m = (sum(followthrough_120m_samples) / len(followthrough_120m_samples)) if followthrough_120m_samples else 0.0
    avg_follow_360m = (sum(followthrough_360m_samples) / len(followthrough_360m_samples)) if followthrough_360m_samples else 0.0
    avg_dominant_move = (sum(dominant_move_samples) / len(dominant_move_samples)) if dominant_move_samples else 0.0
    summary = "缺少可验证的新闻发布时间与价格联动样本。"
    if reaction_count:
        summary = (
            f"已验证 {reaction_count} 条带时间戳的主题证据，"
            f"{aligned_count} 条与新闻方向一致，"
            f"方向一致率 {alignment_rate * 100:.0f}% ，"
            f"新闻后30分钟平均变动 {avg_follow_30m:+.3f}% ，"
            f"2小时平均变动 {avg_follow_120m:+.3f}% ，"
            f"6小时主导波动均值 {avg_dominant_move:.3f}% 。"
        )
    if latest_news_minutes is not None:
        freshness_label = "最新证据较新" if latest_news_minutes <= 180 else "最新证据偏旧"
    else:
        freshness_label = "时间性待确认"
    return {
        "enriched_news": enriched_news,
        "reaction_count": reaction_count,
        "aligned_count": aligned_count,
        "alignment_rate": round(alignment_rate, 4),
        "avg_follow_30m_pct": round(avg_follow_30m, 4),
        "avg_follow_120m_pct": round(avg_follow_120m, 4),
        "avg_follow_360m_pct": round(avg_follow_360m, 4),
        "avg_dominant_move_pct": round(avg_dominant_move, 4),
        "latest_news_minutes": round(latest_news_minutes, 1) if latest_news_minutes is not None else None,
        "freshness_label": freshness_label,
        "summary": summary,
    }


def _collect_similar_historical_events(
    current_market: str,
    current_code: str,
    query: str,
    product_info: Optional[Dict[str, Any]],
    stock_info: Optional[Dict[str, Any]],
    storylines: List[Dict[str, Any]],
    reference_start_dt: datetime,
    frequency: str,
    max_samples: int = 5,
) -> List[Dict[str, Any]]:
    canonical_asset = _normalize_asset_code(current_code)
    asset_terms = _build_news_search_terms(
        query=query,
        product_code=current_code,
        product_info=product_info,
        stock_info=stock_info,
    )[:10]
    collected: Dict[str, Dict[str, Any]] = {}
    search_start = reference_start_dt - timedelta(days=90)
    search_end = reference_start_dt - timedelta(minutes=30)

    for storyline in storylines[:3]:
        storyline_name = storyline.get("storyline", "综合驱动")
        storyline_keywords = _get_storyline_keywords(storyline_name)
        search_terms = _deduplicate_terms(storyline_keywords + asset_terms)[:16]
        if not search_terms:
            continue

        historical_news = _search_news_from_relational_db(
            query=storyline_name,
            search_terms=search_terms,
            start_date=search_start,
            end_date=search_end,
            n_results=18,
        )
        for item in historical_news:
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {}
            news_id = metadata.get("news_id") or metadata.get("title")
            if not news_id or news_id in collected:
                continue
            published_at = _parse_datetime_like(metadata.get("published_at"))
            if published_at is None:
                continue

            text = f"{metadata.get('title', '')} {item.get('document', '')}".lower()
            keyword_hits = sum(1 for keyword in storyline_keywords if keyword.lower() in text)
            if keyword_hits == 0:
                continue

            sample_storyline = _derive_storyline_label([item])
            direct_assets = _extract_metadata_asset_list(metadata, "direct_assets")
            driver_assets = _extract_metadata_asset_list(metadata, "driver_assets")
            relation_weight = 0.35
            relation_type = "background"
            if canonical_asset and canonical_asset in direct_assets:
                relation_type = "direct"
                relation_weight = 1.0
            elif canonical_asset and canonical_asset in driver_assets:
                relation_type = "driver"
                relation_weight = 0.75

            reaction = _estimate_price_reaction_around_time(
                market=current_market,
                code=current_code,
                frequency=frequency,
                anchor_dt=published_at,
            )
            importance_weight = _safe_float(metadata.get("importance_score", 0.0), 0.0)
            similarity_score = (
                (2.8 if sample_storyline == storyline_name else 1.0)
                + keyword_hits * 0.35
                + relation_weight * 1.6
                + importance_weight
            )
            collected[news_id] = {
                "news_id": news_id,
                "title": metadata.get("title", ""),
                "published_at": published_at.isoformat(),
                "storyline": storyline_name,
                "sample_storyline": sample_storyline,
                "relation_type": relation_type,
                "similarity_score": round(similarity_score, 4),
                "importance_score": round(importance_weight, 4),
                "matched_keywords": storyline_keywords[: keyword_hits or 1],
                "reaction": reaction or {
                    "direction": "neutral",
                    "return_pct": 0.0,
                    "follow_30m_pct": 0.0,
                    "follow_120m_pct": 0.0,
                    "absorption_status": "absorbed",
                    "absorption_reason": "缺少当时价格数据，无法估计反应",
                },
            }

    similar_events = list(collected.values())
    similar_events.sort(
        key=lambda item: (
            item["similarity_score"],
            item["reaction"].get("follow_120m_pct", 0.0),
            item["published_at"],
        ),
        reverse=True,
    )
    return similar_events[:max_samples]


def _summarize_historical_pricing_state(
    events: List[Dict[str, Any]],
    storylines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    absorption_counts = {
        "absorbed": 0,
        "partially_absorbed": 0,
        "not_fully_priced": 0,
    }
    directional_bias_score = 0.0

    for event in events:
        status = event.get("absorption_status", "absorbed")
        if status not in absorption_counts:
            status = "absorbed"
        absorption_counts[status] += 1

        if status == "not_fully_priced":
            weight = 1.0
        elif status == "partially_absorbed":
            weight = 0.45
        else:
            weight = 0.1
        directional_bias_score += event.get("direction_sign", 1) * event.get("abs_return_pct", 0.0) * weight

    if directional_bias_score > 0.3:
        future_bias = "偏向延续上行"
    elif directional_bias_score < -0.3:
        future_bias = "偏向延续下行"
    else:
        future_bias = "偏向震荡等待"

    strongest_storyline = storylines[0] if storylines else {}
    return {
        "absorption_counts": absorption_counts,
        "directional_bias_score": round(directional_bias_score, 4),
        "future_bias": future_bias,
        "strongest_storyline": {
            "storyline": strongest_storyline.get("storyline", ""),
            "direction": strongest_storyline.get("direction", "中性"),
            "strength_score": strongest_storyline.get("strength_score", 0.0),
        },
    }


def _estimate_remaining_pricing_room(
    events: List[Dict[str, Any]],
    storylines: List[Dict[str, Any]],
    similar_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    strongest_storyline = storylines[0] if storylines else {}
    storyline_name = strongest_storyline.get("storyline", "")
    storyline_direction = strongest_storyline.get("direction", "中性")
    direction_sign = 1 if storyline_direction == "偏利多" else -1 if storyline_direction == "偏利空" else 0

    relevant_events = [event for event in events if event.get("storyline") == storyline_name] if storyline_name else list(events)
    unpriced_events = [
        event for event in relevant_events
        if event.get("absorption_status") in {"not_fully_priced", "partially_absorbed"}
    ]

    current_follow = 0.0
    if relevant_events:
        current_follow = max(
            abs(_safe_float(event.get("follow_120m_pct", 0.0)))
            for event in relevant_events
        )

    historical_continuations: List[float] = []
    aligned_samples = 0
    for sample in similar_events:
        reaction = sample.get("reaction", {})
        reaction_direction = reaction.get("direction", "neutral")
        reaction_sign = 1 if reaction_direction == "bullish" else -1 if reaction_direction == "bearish" else 0
        if storyline_name and sample.get("storyline") != storyline_name:
            continue
        if direction_sign and reaction_sign and reaction_sign != direction_sign:
            continue
        continuation = abs(_safe_float(reaction.get("follow_120m_pct", 0.0)))
        if continuation > 0:
            historical_continuations.append(continuation)
            aligned_samples += 1

    avg_historical_continuation = (
        sum(historical_continuations) / len(historical_continuations)
        if historical_continuations else 0.0
    )

    if direction_sign == 0 or not storyline_name:
        estimated_room_pct = 0.0
        bias_label = "方向不明，剩余空间有限"
        rationale = "当前最强主线方向不够清晰，暂不适合给出明确剩余定价空间"
    else:
        base_room = max(avg_historical_continuation - current_follow, 0.0)
        if unpriced_events:
            base_room += min(
                sum(abs(_safe_float(event.get("follow_30m_pct", 0.0))) for event in unpriced_events) / len(unpriced_events),
                1.2,
            ) * 0.35
        if strongest_storyline.get("strength_score", 0.0) >= 5:
            base_room *= 1.15
        estimated_room_pct = round(max(base_room, 0.0), 4)
        if estimated_room_pct >= 0.5:
            bias_label = "仍有可观剩余空间"
        elif estimated_room_pct >= 0.2:
            bias_label = "仍有一定剩余空间"
        else:
            bias_label = "剩余空间有限"
        rationale = (
            f"基于最强主线“{storyline_name}”的历史相似样本，平均120分钟延续约 {avg_historical_continuation:.3f}% ，"
            f"当前已走出约 {current_follow:.3f}% ，结合 {len(unpriced_events)} 个未完全消化事件，估算剩余空间约 {estimated_room_pct:.3f}%"
        )

    confidence = "high" if aligned_samples >= 3 else "medium" if aligned_samples >= 1 else "low"
    return {
        "storyline": storyline_name,
        "direction": storyline_direction,
        "estimated_room_pct": estimated_room_pct,
        "historical_avg_follow_120m_pct": round(avg_historical_continuation, 4),
        "current_follow_120m_pct": round(current_follow, 4),
        "aligned_sample_count": aligned_samples,
        "unpriced_event_count": len(unpriced_events),
        "confidence": confidence,
        "bias_label": bias_label,
        "rationale": rationale,
    }


def _build_historical_analysis_context(
    name: str,
    current_market: str,
    current_code: str,
    params: Dict[str, Any],
    events: List[Dict[str, Any]],
    storylines: List[Dict[str, Any]],
    topic_timeline: List[Dict[str, Any]],
    pricing_summary: Dict[str, Any],
    similar_events: List[Dict[str, Any]],
    pricing_room: Dict[str, Any],
) -> str:
    lookback_label = _format_lookback_label(params["lookback_hours"])
    event_lines = []
    for index, event in enumerate(events[: params["max_events"]], 1):
        absorption_label = {
            "absorbed": "已消化",
            "partially_absorbed": "部分消化",
            "not_fully_priced": "未充分定价",
        }.get(event.get("absorption_status", "absorbed"), "已消化")
        event_news_lines = []
        for news_index, news_item in enumerate(event.get("event_news_details", [])[:3], 1):
            event_news_lines.append(
                f"      {news_index}) {news_item.get('published_at_label', '--')} "
                f"[{news_item.get('event_relation_label', '背景线索')}][{news_item.get('impact_label', '中性')}] "
                f"{news_item.get('title', '未命名新闻')} | 影响说明={news_item.get('impact_reason') or news_item.get('summary') or '暂无'}"
            )
        event_lines.append(
            f"{index}. 时间={event['trigger_dt'].isoformat()} 方向={event['direction']} "
            f"5分钟涨跌={event['return_pct']:.3f}% 振幅={event['bar_range_pct']:.3f}% "
            f"后30分钟延续={event['follow_30m_pct']:.3f}% 状态={absorption_label}\n"
            f"   主线={event.get('storyline', '综合驱动')} 相关新闻={event.get('news_count', 0)} "
            f"代表新闻={'; '.join(event.get('top_news_titles', [])[:2]) or '暂无'}\n"
            f"   原因判断={event.get('cause_summary', '暂无')}\n"
            f"{chr(10).join(event_news_lines) if event_news_lines else '      1) 暂无可引用的高相关新闻'}"
        )

    storyline_lines = []
    for item in storylines[:5]:
        storyline_lines.append(
            f"- {item['storyline']} | 事件数={item['event_count']} | 方向={item['direction']} | "
            f"强度分={item['strength_score']:.2f} | 未充分定价={item['unpriced_count']} | "
            f"累计波动贡献={item['total_abs_move']:.3f}% | 代表新闻={'; '.join(item['headline_examples']) or '暂无'}"
        )

    topic_lines = []
    for item in topic_timeline[:6]:
        topic_lines.append(
            f"- {item.get('topic_label', '综合主题')} | 事件数={item.get('event_count', 0)} | 影响={item.get('impact_label', '中性')} | "
            f"关键词={','.join(item.get('matched_keywords', [])[:4]) or '无'} | 主题摘要={item.get('topic_summary', '暂无')}"
        )

    similar_event_lines = []
    for item in similar_events[:5]:
        reaction = item.get("reaction", {})
        similar_event_lines.append(
            f"- {item.get('published_at', '')} | 主线={item.get('storyline', '综合驱动')} | "
            f"相似度={item.get('similarity_score', 0):.2f} | 标题={item.get('title', '无标题')} | "
            f"当时30分钟延续={reaction.get('follow_30m_pct', 0):.3f}% | "
            f"120分钟延续={reaction.get('follow_120m_pct', 0):.3f}% | "
            f"状态={reaction.get('absorption_status', 'absorbed')}"
        )

    asset_template = _get_asset_storyline_template(current_code, current_market)

    return f"""
研究对象: {name or current_code}
市场: {current_market}
代码: {current_code}
分析窗口: 过去 {lookback_label}
事件检测周期: {params['event_frequency']}
阈值设置: 涨跌阈值={params['min_return_pct']}% 振幅阈值={params['min_range_pct']}% ATR倍数={params['atr_multiple']}
资产研究模板: {asset_template.get('focus', '综合分析')}

关键价格事件:
{chr(10).join(event_lines) if event_lines else '- 暂未检测到关键价格事件'}

24小时主线聚合:
{chr(10).join(storyline_lines) if storyline_lines else '- 暂无明显主线'}

主题事件时间线:
{chr(10).join(topic_lines) if topic_lines else '- 暂无主题聚合结果'}

市场定价状态聚合:
- 已消化事件: {pricing_summary.get('absorption_counts', {}).get('absorbed', 0)}
- 部分消化事件: {pricing_summary.get('absorption_counts', {}).get('partially_absorbed', 0)}
- 未充分定价事件: {pricing_summary.get('absorption_counts', {}).get('not_fully_priced', 0)}
- 市场未来偏向: {pricing_summary.get('future_bias', '偏向震荡等待')}
- 当前最强主线: {pricing_summary.get('strongest_storyline', {}).get('storyline', '暂无')} / {pricing_summary.get('strongest_storyline', {}).get('direction', '中性')}

相似历史事件对照:
{chr(10).join(similar_event_lines) if similar_event_lines else '- 暂未找到高相似历史样本'}

剩余定价空间估计:
- 最强主线: {pricing_room.get('storyline', '暂无')} / {pricing_room.get('direction', '中性')}
- 剩余空间判断: {pricing_room.get('bias_label', '剩余空间有限')}
- 估算剩余空间: {pricing_room.get('estimated_room_pct', 0):.3f}%
- 历史样本均值(120分钟): {pricing_room.get('historical_avg_follow_120m_pct', 0):.3f}%
- 当前已走幅度(120分钟): {pricing_room.get('current_follow_120m_pct', 0):.3f}%
- 样本数量/置信度: {pricing_room.get('aligned_sample_count', 0)} / {pricing_room.get('confidence', 'low')}
- 说明: {pricing_room.get('rationale', '暂无')}
""".strip()


def _generate_ai_historical_analysis(
    context_text: str,
    current_market: str,
    current_code: str,
    name: str,
    lookback_hours: int = 24,
) -> str:
    ai_client = AIAnalyse(current_market or "a")
    lookback_label = _format_lookback_label(lookback_hours)
    prompt = f"""
你是一位职业交易团队里的事件驱动研究员。请根据过去{lookback_label}的价格事件与新闻窗口，输出一份简洁、直接、可执行的“历史分析”报告。

分析对象: {name}({current_code})

结构化上下文:
{context_text}

请严格按以下结构输出：
1. 交易结论
2. 主驱动与关键新闻
3. 历史优势
4. 执行条件
5. 失效条件
6. 只需要继续观察的 2-3 个信号

要求：
- 以“价格事件 -> 新闻归因 -> 主线 -> 消化判断 -> 未来推演”的逻辑展开
- 不要写成长篇研报，不要泛泛而谈
- 先给结论，再给依据
- 不要空泛复述新闻，必须解释价格为什么会这样反应
- 每个关键价格事件都要点名 1-3 条具体新闻标题，并说明它们分别是利多、利空还是中性，以及通过什么路径影响价格
- 对“已消化/未消化”要给出判断依据
- 要明确说明当前最强主线是否仍在继续定价
- 若有相似历史样本，要说明本次与历史样本的异同与可借鉴点
- 对剩余定价空间要说明估计依据，不要只给结论
- 如果当前不适合交易，要明确写“先不交易”，并说明原因
- 直接输出中文 Markdown 报告
"""
    return _call_ai_and_get_content(ai_client, prompt)


def _generate_historical_analysis_payload(
    data: Dict[str, Any],
    progress_callback=None,
) -> Dict[str, Any]:
    data = data or {}
    current_market = str(data.get("current_market", "") or "").strip()
    current_code = str(data.get("current_code", "") or "").strip().upper()
    if not current_market or not current_code:
        raise ValueError("缺少市场或标的代码")

    params = _normalize_history_analysis_params(data)
    cache_payload = {
        "current_market": current_market,
        "current_code": current_code,
        **params,
    }
    cached_result = _load_summary_result_cache("historical_analysis", cache_payload)
    if cached_result:
        logger.info("历史分析命中结果缓存")
        return cached_result

    lookback_label = _format_lookback_label(params["lookback_hours"])

    def _progress(stage: str, message: str, progress: int) -> None:
        if progress_callback is not None:
            progress_callback(stage=stage, message=message, progress=progress)

    _progress("load_price", f"正在加载过去{lookback_label}价格数据", 10)
    price_bars = _load_historical_price_bars(
        market=current_market,
        code=current_code,
        frequency=params["event_frequency"],
        lookback_hours=params["lookback_hours"],
        purpose="历史分析",
    )
    if len(price_bars) < 10:
        latest_dt = None
        try:
            latest_dt = db.klines_last_datetime(
                current_market,
                current_code,
                params["event_frequency"],
            )
        except Exception:
            latest_dt = None
        raise ValueError(
            "历史价格数据不足，无法进行事件分析"
            + (
                f"（{params['event_frequency']} 最近可用数据时间：{latest_dt}）"
                if latest_dt
                else "（请先同步当前资产的分钟级K线）"
            )
        )

    product_info = _get_product_info(current_code)
    stock_info = {}
    try:
        stock_info = get_exchange(Market(current_market)).stock_info(current_code) or {}
    except Exception:
        stock_info = {}
    name = (
        stock_info.get("name")
        or product_info.get("name_cn")
        or product_info.get("cn_name")
        or current_code
    )

    _progress("detect_events", "正在识别关键价格波动事件", 28)
    detected_events = _detect_price_events(
        price_bars=price_bars,
        min_return_pct=params["min_return_pct"],
        min_range_pct=params["min_range_pct"],
        atr_multiple=params["atr_multiple"],
        event_window_minutes=params["event_window_minutes"],
        merge_gap_minutes=params["merge_gap_minutes"],
    )
    if not detected_events:
        raise ValueError(f"过去{lookback_label}未识别到满足阈值的关键波动事件")

    top_events = detected_events[: params["max_events"]]
    topic_definitions = _get_asset_event_topic_definitions(current_market, current_code)
    _progress("link_news", "正在关联价格事件窗口中的新闻", 48)
    query = data.get("query") or name or current_code
    for event in top_events:
        event_news = _collect_event_news(
            event=event,
            current_market=current_market,
            current_code=current_code,
            query=query,
            product_info=product_info,
            stock_info=stock_info,
        )
        event["event_news"] = event_news
        event["event_news_details"] = [_format_historical_event_news_item(item) for item in event_news[:5]]
        event["news_count"] = len(event_news)
        event["top_news_titles"] = [
            item.get("metadata", {}).get("title", "")
            for item in event_news[:3]
            if item.get("metadata", {}).get("title")
        ]
        event["storyline"] = _derive_storyline_label(
            event_news,
            asset_code=current_code,
            market=current_market,
        )
        absorption = _assess_event_absorption(event)
        event["absorption_status"] = absorption["status"]
        event["absorption_reason"] = absorption["reason"]
        event["cause_summary"] = _build_historical_event_cause_summary(event)

    _progress("build_storyline", "正在聚合 24 小时市场主线", 70)
    storylines = _build_historical_storylines(
        top_events,
        asset_code=current_code,
        market=current_market,
    )
    topic_timeline = _build_historical_topic_timeline(top_events, topic_definitions)
    pricing_summary = _summarize_historical_pricing_state(top_events, storylines)
    _progress("similar_events", "正在检索相似历史事件样本", 76)
    similar_events = _collect_similar_historical_events(
        current_market=current_market,
        current_code=current_code,
        query=query,
        product_info=product_info,
        stock_info=stock_info,
        storylines=storylines,
        reference_start_dt=min(event["trigger_dt"] for event in top_events),
        frequency=params["event_frequency"],
        max_samples=5,
    )
    pricing_room = _estimate_remaining_pricing_room(
        events=top_events,
        storylines=storylines,
        similar_events=similar_events,
    )
    scenario_route = _build_research_scenario_route(
        current_market=current_market,
        current_code=current_code,
        storylines=storylines,
        pricing_summary=pricing_summary,
    )
    reflection_memory = _build_reflection_memory(
        current_market=current_market,
        current_code=current_code,
        scenario_route=scenario_route,
    )
    quick_research = _build_quick_research_snapshot(
        asset_name=name,
        current_code=current_code,
        scenario_route=scenario_route,
        pricing_summary=pricing_summary,
    )
    deep_research = _build_deep_research_plan(scenario_route=scenario_route)
    timesfm_forecast = _build_timesfm_forecast(
        current_market=current_market,
        current_code=current_code,
        frequency=params["event_frequency"],
        price_bars=price_bars,
        scenario_route=scenario_route,
        pricing_summary=pricing_summary,
    )
    risk_brief = _build_rule_based_risk_brief(
        scenario_route=scenario_route,
        pricing_summary=pricing_summary,
        pricing_room=pricing_room,
        forecast_bundle=timesfm_forecast,
    )
    for event in top_events:
        event_direct_news = [_format_realtime_focus_news_item(item, "direct") for item in event.get("event_news", [])[:3]]
        event_covariates = build_timesfm_covariates(
            direct_news=event_direct_news,
            scenario_route=scenario_route,
            pricing_summary=pricing_summary,
        )
        event["timesfm_forecast"] = build_event_forecast(
            price_bars=price_bars,
            market=current_market,
            code=current_code,
            frequency=params["event_frequency"],
            event_time=event.get("trigger_dt"),
            actual_follow_30m_pct=_safe_float(event.get("follow_30m_pct")),
            actual_follow_120m_pct=_safe_float(event.get("follow_120m_pct")),
            covariates=event_covariates,
        )
    context_text = _build_historical_analysis_context(
        name=name,
        current_market=current_market,
        current_code=current_code,
        params=params,
        events=top_events,
        storylines=storylines,
        topic_timeline=topic_timeline,
        pricing_summary=pricing_summary,
        similar_events=similar_events,
        pricing_room=pricing_room,
    )

    _progress("summary", "AI 正在生成历史分析报告", 84)
    summary = _generate_ai_historical_analysis(
        context_text=context_text,
        current_market=current_market,
        current_code=current_code,
        name=name,
        lookback_hours=params["lookback_hours"],
    )
    trader_decision = _build_historical_trader_decision(
        events=top_events,
        storylines=storylines,
        pricing_summary=pricing_summary,
        pricing_room=pricing_room,
        timesfm_forecast=timesfm_forecast,
        risk_brief=risk_brief,
        lookback_label=lookback_label,
    )
    event_trade_templates = _build_historical_event_trade_templates(
        events=top_events,
        pricing_room=pricing_room,
    )

    _progress("save", "正在保存历史分析结果", 94)
    summary_id = db.market_summary_insert(
        {
            "title": f"{name} {lookback_label}历史分析",
            "content": summary,
            "market": current_market,
            "code": current_code,
            "summary_type": "historical_analysis",
            "chart_snapshot": _build_timesfm_review_metadata(
                {
                    "timesfm_forecast": timesfm_forecast,
                    "events": [
                        {
                            "trigger_dt": event.get("trigger_dt"),
                            "storyline": event.get("storyline", "综合驱动"),
                            "direction": event.get("direction"),
                            "follow_30m_pct": round(_safe_float(event.get("follow_30m_pct")), 4),
                            "follow_120m_pct": round(_safe_float(event.get("follow_120m_pct")), 4),
                            "timesfm_forecast": event.get("timesfm_forecast", {}),
                        }
                        for event in top_events
                    ],
                    "pricing_summary": pricing_summary,
                    "pricing_room": pricing_room,
                },
                params,
            ),
        }
    )

    result = {
        "summary": summary,
        "summary_id": summary_id,
        "event_count": len(top_events),
        "storyline_count": len(storylines),
        "topic_count": len(topic_timeline),
        "lookback_hours": params["lookback_hours"],
        "lookback_label": lookback_label,
        "analysis_window": {
            "label": lookback_label,
            "start": price_bars[0]["dt"].isoformat() if price_bars and hasattr(price_bars[0].get("dt"), "isoformat") else str(price_bars[0].get("dt") if price_bars else ""),
            "end": price_bars[-1]["dt"].isoformat() if price_bars and hasattr(price_bars[-1].get("dt"), "isoformat") else str(price_bars[-1].get("dt") if price_bars else ""),
        },
        "event_frequency": params["event_frequency"],
        "pricing_summary": pricing_summary,
        "pricing_room": pricing_room,
        "scenario_route": scenario_route,
        "reflection_memory": reflection_memory,
        "quick_research": quick_research,
        "deep_research": deep_research,
        "risk_brief": risk_brief,
        "timesfm_forecast": timesfm_forecast,
        "trader_decision": trader_decision,
        "event_trade_templates": event_trade_templates,
        "topic_definitions": topic_definitions,
        "topic_timeline": topic_timeline,
        "similar_events": similar_events,
        "events": [
            {
                "event_id": event.get("event_id"),
                "trigger_dt": event["trigger_dt"].isoformat(),
                "direction": event["direction"],
                "return_pct": round(event["return_pct"], 4),
                "bar_range_pct": round(event["bar_range_pct"], 4),
                "follow_30m_pct": round(event["follow_30m_pct"], 4),
                "follow_120m_pct": round(event["follow_120m_pct"], 4),
                "news_count": event.get("news_count", 0),
                "storyline": event.get("storyline", "综合驱动"),
                "absorption_status": event.get("absorption_status", "absorbed"),
                "absorption_reason": event.get("absorption_reason", ""),
                "cause_summary": event.get("cause_summary", ""),
                "top_news_titles": event.get("top_news_titles", []),
                "event_news_details": event.get("event_news_details", []),
                "timesfm_forecast": event.get("timesfm_forecast", {}),
            }
            for event in top_events
        ],
        "storylines": storylines,
        "cache_hit": False,
    }
    _save_summary_result_cache("historical_analysis", cache_payload, result)
    return result


def _run_historical_analysis_task(task_id: str, payload: Dict[str, Any]) -> None:
    try:
        _set_market_summary_task(
            task_id,
            task_type="historical_analysis",
            state="running",
            stage="prepare",
            message="任务已启动",
            progress=1,
            started_at=datetime.now().isoformat(),
        )
        result = _generate_historical_analysis_payload(
            payload,
            progress_callback=lambda stage, message, progress: _set_market_summary_task(
                task_id,
                stage=stage,
                message=message,
                progress=progress,
            ),
        )
        _set_market_summary_task(
            task_id,
            task_type="historical_analysis",
            state="completed",
            stage="completed",
            message="历史分析生成完成",
            progress=100,
            result=result,
            summary_id=result.get("summary_id"),
            summary_preview=(result.get("summary") or "")[:300],
            finished_at=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"异步生成历史分析失败: {str(e)}", exc_info=True)
        _set_market_summary_task(
            task_id,
            task_type="historical_analysis",
            state="failed",
            stage="failed",
            message=str(e),
            progress=100,
            error=str(e),
            finished_at=datetime.now().isoformat(),
        )


def _get_product_info(product_code: str, market: str = "") -> Dict[str, Any]:
    """
    根据产品代码获取产品信息，包括中英文名称、类型等。
    现在增加了从交易所动态获取信息的功能。
    
    Args:
        product_code: 产品代码，如EURUSD, FE.EURUSD, GOLD等
        market: 可选市场标识，保留兼容实时关注等新链路的调用方式
        
    Returns:
        Dict: 包含产品信息的字典
    """
    import re
    
    product_code_clean = product_code.strip().upper()
    
    # 产品信息映射表 (静态部分)

    product_mapping = {
        # 外汇货币对
        'EURUSD': {
            'name_cn': '欧元美元',
            'name_en': 'Euro US Dollar',
            'type': 'forex',
            'base_currency': 'EUR',
            'quote_currency': 'USD',
            'description': '欧元兑美元汇率',
            'keywords': ['欧元', '美元', '欧美', 'EURUSD', '欧央行', '美联储', 'ECB', 'Fed']
        },
        'GBPUSD': {
            'name_cn': '英镑美元',
            'name_en': 'British Pound US Dollar',
            'type': 'forex',
            'base_currency': 'GBP',
            'quote_currency': 'USD',
            'description': '英镑兑美元汇率',
            'keywords': ['英镑', '美元', '镑美', 'GBPUSD', '英央行', '美联储', 'BOE', 'Fed', '脱欧', 'Brexit']
        },
        'USDJPY': {
            'name_cn': '美元日元',
            'name_en': 'US Dollar Japanese Yen',
            'type': 'forex',
            'base_currency': 'USD',
            'quote_currency': 'JPY',
            'description': '美元兑日元汇率',
            'keywords': ['美元', '日元', '美日', 'USDJPY', '美联储', '日央行', 'Fed', 'BOJ']
        },
        'AUDUSD': {
            'name_cn': '澳元美元',
            'name_en': 'Australian Dollar US Dollar',
            'type': 'forex',
            'base_currency': 'AUD',
            'quote_currency': 'USD',
            'description': '澳元兑美元汇率',
            'keywords': ['澳元', '美元', '澳美', 'AUDUSD', '澳洲联储', '美联储', 'RBA', 'Fed', '商品货币', '铁矿石']
        },
        'USDCAD': {
            'name_cn': '美元加元',
            'name_en': 'US Dollar Canadian Dollar',
            'type': 'forex',
            'base_currency': 'USD',
            'quote_currency': 'CAD',
            'description': '美元兑加元汇率',
            'keywords': ['美元', '加元', '美加', 'USDCAD', '美联储', '加拿大央行', 'Fed', 'BOC', '原油', 'WTI']
        },
        'USDCHF': {
            'name_cn': '美元瑞郎',
            'name_en': 'US Dollar Swiss Franc',
            'type': 'forex',
            'base_currency': 'USD',
            'quote_currency': 'CHF',
            'description': '美元兑瑞士法郎汇率',
            'keywords': ['美元', '瑞郎', '美瑞', 'USDCHF', '美联储', '瑞士央行', 'Fed', 'SNB', '避险货币']
        },
        'USDCNY': {
            'name_cn': '美元人民币',
            'name_en': 'US Dollar Chinese Yuan',
            'type': 'forex',
            'base_currency': 'USD',
            'quote_currency': 'CNY',
            'description': '美元兑人民币汇率',
            'keywords': [
                '美元', '人民币', 'USDCNY', 'USDCNH', 'USD/CNY', 'USD/CNH',
                '美元兑人民币', '美元兑离岸人民币', '美元兑在岸人民币',
                '离岸人民币', '在岸人民币', '人民币汇率', '人民币中间价',
                '中国人民银行', '人民银行', 'PBOC', '美联储', 'Fed'
            ],
            'aliases': ['USDCNY', 'USDCNH', 'USD/CNY', 'USD/CNH', 'CNH', 'CNY'],
            'driver_keywords': [
                '中国人民银行', '人民银行', 'PBOC', '人民币中间价', '逆周期因子',
                '外汇存款准备金率', '中美利差', '美联储', 'Fed', '美元指数', 'DXY'
            ],
        },
        'USDCNH': {
            'name_cn': '美元离岸人民币',
            'name_en': 'US Dollar Offshore Chinese Yuan',
            'type': 'forex',
            'base_currency': 'USD',
            'quote_currency': 'CNH',
            'description': '美元兑离岸人民币汇率',
            'keywords': [
                '美元', '离岸人民币', 'USDCNH', 'USDCNY', 'USD/CNH', 'USD/CNY',
                '美元兑离岸人民币', '美元兑人民币', '人民币汇率', '中国人民银行',
                'PBOC', '美联储', 'Fed'
            ],
            'aliases': ['USDCNH', 'USDCNY', 'USD/CNH', 'USD/CNY', 'CNH', 'CNY'],
            'driver_keywords': [
                '中国人民银行', '人民银行', 'PBOC', '人民币中间价', '逆周期因子',
                '外汇存款准备金率', '中美利差', '美联储', 'Fed', '美元指数', 'DXY'
            ],
        },
        'CZ.ICL8': {
            'cn_name': '中证500股指期货',
            'en_name': 'CSI 500 Index Futures',
            'type': '股指期货',
            'symbol': 'IC',
            'description': '中国金融期货交易所的中证500指数期货主力合约。',
            'keywords': ['中证500', 'IC', '股指期货', 'A股', '中国股市', '上证', '深证'],
            'im': 1000,
            '1h': 50
        },
        # 贵金属
        'QS.AUL8 期货': {
            'name_cn': '黄金期货',
            'name_en': 'Gold Futures',
            'type': 'futures',
            'symbol': 'AU',
            'description': '上海期货交易所黄金主力合约',
            'keywords': ['黄金', '黄金期货', '沪金', 'SHFE Gold', '贵金属', '避险']
        },
        'CO.GC00Y': {
            'name_cn': '黄金',
            'name_en': 'Gold',
            'type': 'precious_metal',
            'symbol': 'XAU',
            'description': '黄金现货价格',
            'keywords': ['黄金', 'Gold', 'XAU', '贵金属', '避险', '通胀对冲', '美元指数', 'DXY']
        },
        'XAU': {
            'name_cn': '黄金',
            'name_en': 'Gold',
            'type': 'precious_metal',
            'symbol': 'XAU',
            'description': '黄金现货价格',
            'keywords': ['黄金', 'Gold', 'XAU', '贵金属', '避险', '通胀对冲', '美元指数', 'DXY']
        },
        'SILVER': {
            'name_cn': '白银',
            'name_en': 'Silver',
            'type': 'precious_metal',
            'symbol': 'XAG',
            'description': '白银现货价格',
            'keywords': ['白银', 'Silver', 'XAG', '贵金属', '工业金属', '避险']
        },
        'XAG': {
            'name_cn': '白银',
            'name_en': 'Silver',
            'type': 'precious_metal',
            'symbol': 'XAG',
            'description': '白银现货价格',
            'keywords': ['白银', 'Silver', 'XAG', '贵金属', '工业金属', '避险']
        },
        # 原油
        'OIL': {
            'name_cn': '原油',
            'name_en': 'Crude Oil',
            'type': 'commodity',
            'symbol': 'CL',
            'description': '原油期货价格',
            'keywords': ['原油', 'Oil', 'CL', 'WTI', 'Brent', '能源', 'OPEC', '欧佩克', 'EIA', 'API']
        },
        'CL': {
            'name_cn': '原油',
            'name_en': 'Crude Oil',
            'type': 'commodity',
            'symbol': 'CL',
            'description': '原油期货价格',
            'keywords': ['原油', 'Oil', 'CL', 'WTI', 'Brent', '能源', 'OPEC', '欧佩克', 'EIA', 'API']
        }
    }
    
    # 优先直接匹配静态表
    if product_code_clean in product_mapping:
        info = product_mapping[product_code_clean].copy()
        info['is_futures'] = '.' in product_code_clean
        info['original_code'] = product_code_clean
        return _enrich_product_info_with_akshare_symbol(info, product_code_clean)

    # 处理期货格式 (如 FE.EURUSD)
    if '.' in product_code_clean:
        parts = product_code_clean.split('.')
        if len(parts) == 2:
            prefix, base_code = parts
            if base_code in product_mapping:
                info = product_mapping[base_code].copy()
                info['is_futures'] = True
                info['futures_prefix'] = prefix
                info['original_code'] = product_code_clean
                return _enrich_product_info_with_akshare_symbol(info, product_code_clean)

    inferred_akshare_symbol = normalize_akshare_futures_symbol(product_code_clean)
    if inferred_akshare_symbol:
        inferred_name_cn = get_akshare_futures_symbol_name(inferred_akshare_symbol) or product_code_clean
        return _enrich_product_info_with_akshare_symbol(
            {
                'name_cn': inferred_name_cn,
                'name_en': product_code_clean,
                'type': 'futures' if '.' in product_code_clean or market.lower() == 'futures' else 'commodity',
                'symbol': inferred_akshare_symbol,
                'description': f"{inferred_name_cn} ({inferred_akshare_symbol})",
                'keywords': [inferred_name_cn, inferred_akshare_symbol, product_code_clean],
                'is_futures': '.' in product_code_clean or market.lower() == 'futures',
                'original_code': product_code_clean,
            },
            product_code_clean,
        )
    
    # 尝试从交易所动态获取信息 (借鉴 zixuan.py)
    try:
        # 简单的市场类型推断
        market_map = {'SH': 'a', 'SZ': 'a', 'BJ': 'a', 'HK': 'hk', 'US': 'us'}
        market_prefix = product_code_clean.split('.')[0]
        market_type = market_map.get(market_prefix, 'futures' if '.' in product_code_clean else 'a')

        ex = get_exchange(Market(market_type))
        stock_info = ex.stock_info(product_code_clean)
        if stock_info and stock_info.get('name'):
            return _enrich_product_info_with_akshare_symbol({
                'name_cn': stock_info.get('name'),
                'name_en': '', # 交易所信息通常不含英文名
                'type': market_type,
                'symbol': stock_info.get('code'),
                'description': f"{stock_info.get('name')} ({stock_info.get('code')})",
                'keywords': [stock_info.get('name'), stock_info.get('code')],
                'is_futures': market_type == 'futures',
                'original_code': product_code_clean
            }, product_code_clean)
    except Exception as e:
        logger.warning(f"从交易所获取 {product_code_clean} 信息时出错: {e}")

    # 尝试通用货币对模式匹配
    forex_pattern = r'^([A-Z]{3})/?([A-Z]{3})$'
    match = re.match(forex_pattern, product_code_clean)
    if match:
        base_curr, quote_curr = match.groups()
        currency_names = {
            'USD': {'cn': '美元', 'en': 'US Dollar'},
            'EUR': {'cn': '欧元', 'en': 'Euro'},
            'GBP': {'cn': '英镑', 'en': 'British Pound'},
            'JPY': {'cn': '日元', 'en': 'Japanese Yen'},
            'AUD': {'cn': '澳元', 'en': 'Australian Dollar'},
            'CAD': {'cn': '加元', 'en': 'Canadian Dollar'},
            'CHF': {'cn': '瑞郎', 'en': 'Swiss Franc'},
            'CNY': {'cn': '人民币', 'en': 'Chinese Yuan'},
        }
        base_cn = currency_names.get(base_curr, {}).get('cn', base_curr)
        quote_cn = currency_names.get(quote_curr, {}).get('cn', quote_curr)
        base_en = currency_names.get(base_curr, {}).get('en', base_curr)
        quote_en = currency_names.get(quote_curr, {}).get('en', quote_curr)

        return _enrich_product_info_with_akshare_symbol({
            'name_cn': f'{base_cn}{quote_cn}',
            'name_en': f'{base_en} {quote_en}',
            'type': 'forex',
            'base_currency': base_curr,
            'quote_currency': quote_curr,
            'description': f'{base_cn}兑{quote_cn}汇率',
            'keywords': [base_cn, quote_cn, f'{base_cn}{quote_cn}', product_code_clean],
            'is_futures': False,
            'original_code': product_code_clean
        }, product_code_clean)

    # 如果都找不到，返回一个基于输入代码的默认字典
    return _enrich_product_info_with_akshare_symbol({
        'name_cn': product_code_clean,
        'name_en': product_code_clean,
        'type': 'unknown',
        'description': f'未知产品: {product_code_clean}',
        'keywords': [product_code_clean],
        'is_futures': False,
        'original_code': product_code_clean
    }, product_code_clean)
    
    # === 1. 外汇相关检测和扩展 ===
    # 检测货币对格式，支持多种格式:
    # - 标准格式: EURUSD, GBPJPY
    # - 期货格式: FE.EURUSD, FX.GBPJPY
    # - 带分隔符: EUR/USD, GBP-JPY
    forex_patterns = [
        r'(?:FE\.|FX\.|FOREX\.|)?([A-Z]{3})[\./\-]?([A-Z]{3})$',  # 支持期货前缀和分隔符
        r'([A-Z]{3})/([A-Z]{3})$',  # EUR/USD格式
        r'([A-Z]{3})-([A-Z]{3})$'   # EUR-USD格式
    ]
    
    forex_match = None
    for pattern in forex_patterns:
        forex_match = re.match(pattern, query_upper)
        if forex_match:
            break
    
    logger.info(f"外汇检测: query={query_upper}, match={bool(forex_match)}")
    
    if forex_match or any(keyword in query_clean for keyword in ['汇率', '外汇', 'forex', 'FX']):
        forex_terms = [
            query_clean,
            '汇率', '外汇', '货币', '央行', '利率', '货币政策', 
            '美联储', '欧央行', '英央行', '日央行', '人民银行',
            'Fed', 'ECB', 'BOE', 'BOJ', 'PBOC',
            'FOMC', '利率决议', '非农', 'CPI', 'PPI', 'GDP'
        ]
        
        # 如果是具体货币对，添加相关货币术语
        if forex_match:
            base_curr = forex_match.group(1)
            quote_curr = forex_match.group(2)
            
            # 扩展的货币名称映射
            currency_names = {
                'USD': ['美元', 'Dollar', '美金', 'US Dollar','USD'], 
                'EUR': ['欧元', 'Euro', '欧洲央行', 'European Central Bank','USD'], 
                'GBP': ['英镑', 'Pound', 'Sterling', '英国央行', 'Bank of England','USD'],
                'JPY': ['日元', 'Yen', '日本央行', 'Bank of Japan','USD'],
                'CNY': ['人民币', 'Yuan', 'RMB', '中国人民银行', 'PBOC','USD'],
                'AUD': ['澳元', 'Australian Dollar', '澳洲联储', 'RBA','USD'],
                'CAD': ['加元', 'Canadian Dollar', '加拿大央行', 'Bank of Canada','USD'],
                'CHF': ['瑞郎', 'Swiss Franc', '瑞士央行', 'SNB','USD'],
                'NZD': ['纽元', 'New Zealand Dollar', '新西兰联储', 'RBNZ','USD']
            }
            
            # 添加货币相关术语
            if base_curr in currency_names:
                forex_terms.extend(currency_names[base_curr])
            if quote_curr in currency_names:
                forex_terms.extend(currency_names[quote_curr])
            
            # 如果是期货合约格式(如FE.EURUSD)，添加期货相关术语
            if query_upper.startswith(('FE.', 'FX.', 'FOREX.')):
                forex_terms.extend([
                    '外汇期货', '货币期货', 'Currency Futures', 'FX Futures',
                    '期货合约', '交割', '保证金', 'Margin',
                    'CME', 'CBOT', '芝商所', '期货交易所',
                    '持仓', 'Open Interest', '成交量', 'Volume'
                ])
            
            # 添加特定货币对的经济指标
            pair_indicators = {
                ('EUR', 'USD'): ['欧美', 'EURUSD', '欧元区GDP', '美国GDP', '欧美利差'],
                ('GBP', 'USD'): ['镑美', 'GBPUSD', '英国GDP', '脱欧', 'Brexit'],
                ('USD', 'JPY'): ['美日', 'USDJPY', '日本GDP', '日本通胀'],
                ('AUD', 'USD'): ['澳美', 'AUDUSD', '澳洲GDP', '商品价格', '铁矿石'],
                ('USD', 'CAD'): ['美加', 'USDCAD', '加拿大GDP', '原油价格', 'WTI']
            }
            
            pair_key = (base_curr, quote_curr)
            if pair_key in pair_indicators:
                forex_terms.extend(pair_indicators[pair_key])
        
        result = ' '.join(list(set(forex_terms)))
        logger.info(f"外汇搜索优化: {query_clean} -> 包含{len(set(forex_terms))}个相关术语")
        return result
    
    # === 2. 贵金属和商品相关检测和扩展 ===
    commodity_keywords = ['黄金', 'gold', 'XAU', '白银', 'silver', 'XAG', '原油', 'oil', 'CL', 
                         '天然气', 'gas', 'NG', '铜', 'copper', 'HG', '商品', 'commodity']
    
    if (any(keyword in query_clean.lower() for keyword in commodity_keywords) or 
        query_upper in ['GOLD', 'XAU', 'SILVER', 'XAG', 'OIL', 'CL', 'NG', 'HG', 'COPPER']):
        
        commodity_terms = [
            query_clean,
            '商品', '大宗商品', '贵金属', '工业金属', '能源',
            '黄金', '白银', '原油', '天然气', '铜',
            'Gold', 'Silver', 'Oil', 'Copper',
            '避险', '通胀', '通胀对冲', '避险资产',
            'OPEC', '欧佩克', '库存', 'EIA', 'API',
            '美元指数', 'DXY', '地缘政治',
            '央行储备', '实物需求', '工业需求', '投资需求'
        ]
        
        result = ' '.join(list(set(commodity_terms)))
        logger.info(f"商品搜索优化: {query_clean} -> 包含{len(set(commodity_terms))}个相关术语")
        return result
    
    # === 3. 股票相关检测和扩展 ===
    stock_keywords = ['股票', 'stock', '股市', '指数', 'index', 'A股', '美股', '港股',
                     '标普', 'SP500', '纳斯达克', 'NASDAQ', '道指', 'DOW',
                     '沪深300', 'CSI300', '上证', '深证', '恒生']
    
    if (any(keyword in query_clean for keyword in stock_keywords) or 
        query_upper in ['SPX', 'NDX', 'DJI', 'CSI300', 'HSI', 'SSE', 'SZSE']):
        
        stock_terms = [
            query_clean,
            '股票', '股市', '股指', '指数', '证券',
            'A股', '美股', '港股', '欧股',
            '上市公司', '财报', '业绩', '盈利',
            '牛市', '熊市', '调整', '反弹',
            '科技股', '金融股', '消费股', '医药股', '新能源股',
            '蓝筹股', '成长股', '价值股', '小盘股',
            'IPO', '并购', '重组', '分红',
            '券商', '基金', '机构', '散户','stock','index'
        ]
        # add eng
        
        result = ' '.join(list(set(stock_terms)))
        logger.info(f"股票搜索优化: {query_clean} -> 包含{len(set(stock_terms))}个相关术语")
        return result
    
    # === 4. 如果没有匹配到特定资产类型，返回原查询 ===
    logger.info(f"通用搜索: {query_clean}")
    return query_clean


def _resolve_market_data_asset_class(current_market: str, product_info: Optional[Dict[str, Any]] = None) -> str:
    market = str(current_market or "").lower()
    product_type = str((product_info or {}).get("type") or "").lower()
    name_text = f"{(product_info or {}).get('name_cn') or ''}{(product_info or {}).get('name_en') or ''}"
    if market in {"a", "hk", "us"} or product_type in {"stock", "stocks", "equity", "index"}:
        return "equity"
    if market in {"fx", "currency", "currency_spot"} or product_type in {"forex", "fx", "currency"}:
        return "fx"
    if market == "futures":
        if any(keyword in name_text for keyword in ["国债", "利率", "债券", "收益率"]):
            return "rates_futures"
        return "commodity_futures"
    return "macro"


def _build_market_data_related_classes(asset_class: str) -> List[str]:
    mapping = {
        "equity": ["equity", "macro"],
        "commodity_futures": ["commodity_futures", "macro", "cross_asset"],
        "fx": ["fx", "macro", "rates", "cross_asset"],
        "rates_futures": ["rates_futures", "rates", "macro"],
    }
    related = mapping.get(asset_class, [asset_class, "macro"])
    ordered: List[str] = []
    for item in related:
        if item and item not in ordered:
            ordered.append(item)
    return ordered


def _build_market_data_symbol_candidates(current_code: str, product_info: Optional[Dict[str, Any]] = None) -> List[str]:
    candidates = [
        str(current_code or "").strip(),
        str((product_info or {}).get("akshare_symbol") or "").strip(),
        str((product_info or {}).get("akshare_name_cn") or "").strip(),
        str((product_info or {}).get("symbol") or "").strip(),
        str((product_info or {}).get("name_cn") or "").strip(),
        str((product_info or {}).get("name_en") or "").strip(),
    ]
    if _resolve_market_data_asset_class("", product_info) == "fx":
        fx_profile = _build_fx_market_data_profile(current_code, product_info)
        candidates.extend(fx_profile.get("aliases", []))
    normalized: List[str] = []
    for item in candidates:
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _limit_unique_records(records: List[Any], key_name: str, limit: int) -> List[Any]:
    results: List[Any] = []
    seen = set()
    for item in records:
        key = getattr(item, key_name, None) or getattr(item, "id", None)
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def _serialize_market_event_fact(row: Any) -> Dict[str, Any]:
    return {
        "event_uid": getattr(row, "event_uid", ""),
        "event_type": getattr(row, "event_type", ""),
        "asset_class": getattr(row, "asset_class", ""),
        "region": getattr(row, "region", ""),
        "symbol": getattr(row, "symbol", ""),
        "title": getattr(row, "title", ""),
        "source_name": getattr(row, "source_name", ""),
        "importance_score": _safe_float(getattr(row, "importance_score", 0.0), 0.0),
        "actual_value": getattr(row, "actual_value", None),
        "forecast_value": getattr(row, "forecast_value", None),
        "previous_value": getattr(row, "previous_value", None),
        "surprise_value": getattr(row, "surprise_value", None),
        "published_at": getattr(row, "published_at", None).isoformat() if getattr(row, "published_at", None) else "",
        "effective_at": getattr(row, "effective_at", None).isoformat() if getattr(row, "effective_at", None) else "",
    }


def _serialize_market_factor_snapshot(row: Any) -> Dict[str, Any]:
    return {
        "snapshot_uid": getattr(row, "snapshot_uid", ""),
        "factor_group": getattr(row, "factor_group", ""),
        "factor_name": getattr(row, "factor_name", ""),
        "asset_class": getattr(row, "asset_class", ""),
        "symbol": getattr(row, "symbol", ""),
        "tenor": getattr(row, "tenor", ""),
        "value": getattr(row, "value", None),
        "unit": getattr(row, "unit", ""),
        "change_1d": getattr(row, "change_1d", None),
        "change_5d": getattr(row, "change_5d", None),
        "zscore_60d": getattr(row, "zscore_60d", None),
        "source_name": getattr(row, "source_name", ""),
        "as_of_time": getattr(row, "as_of_time", None).isoformat() if getattr(row, "as_of_time", None) else "",
    }


def _serialize_market_structure_metric(row: Any) -> Dict[str, Any]:
    return {
        "metric_uid": getattr(row, "metric_uid", ""),
        "asset_class": getattr(row, "asset_class", ""),
        "symbol": getattr(row, "symbol", ""),
        "metric_name": getattr(row, "metric_name", ""),
        "metric_value": getattr(row, "metric_value", None),
        "window": getattr(row, "window", ""),
        "cross_section_rank": getattr(row, "cross_section_rank", None),
        "source_name": getattr(row, "source_name", ""),
        "as_of_time": getattr(row, "as_of_time", None).isoformat() if getattr(row, "as_of_time", None) else "",
    }


def _serialize_agent_inference_log(row: Any) -> Dict[str, Any]:
    return {
        "run_id": getattr(row, "run_id", ""),
        "agent_name": getattr(row, "agent_name", ""),
        "asset_class": getattr(row, "asset_class", ""),
        "symbol": getattr(row, "symbol", ""),
        "question": getattr(row, "question", ""),
        "thesis": getattr(row, "thesis", ""),
        "confidence_before": getattr(row, "confidence_before", None),
        "confidence_after": getattr(row, "confidence_after", None),
        "changed_conclusion": getattr(row, "changed_conclusion", ""),
        "created_at": getattr(row, "created_at", None).isoformat() if getattr(row, "created_at", None) else "",
    }


def _serialize_event_price_reaction(row: Any) -> Dict[str, Any]:
    return {
        "reaction_uid": getattr(row, "reaction_uid", ""),
        "event_uid": getattr(row, "event_uid", ""),
        "symbol": getattr(row, "symbol", ""),
        "frequency": getattr(row, "frequency", ""),
        "return_30m_pct": getattr(row, "return_30m_pct", None),
        "return_120m_pct": getattr(row, "return_120m_pct", None),
        "return_1d_pct": getattr(row, "return_1d_pct", None),
        "return_5d_pct": getattr(row, "return_5d_pct", None),
        "direction_aligned": getattr(row, "direction_aligned", None),
        "reaction_label": getattr(row, "reaction_label", ""),
        "validated_at": getattr(row, "validated_at", None).isoformat() if getattr(row, "validated_at", None) else "",
    }


def _summarize_market_data_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    event_count = int(summary.get("event_count", 0) or 0)
    factor_count = int(summary.get("factor_count", 0) or 0)
    metric_count = int(summary.get("metric_count", 0) or 0)
    reaction_count = int(summary.get("reaction_count", 0) or 0)
    log_count = int(summary.get("agent_log_count", 0) or 0)
    if event_count + factor_count + metric_count + reaction_count + log_count <= 0:
        return {"summary": "", "highlights": []}

    highlights: List[str] = []
    events = [item for item in (payload.get("events") or []) if isinstance(item, dict)]
    factors = [item for item in (payload.get("factors") or []) if isinstance(item, dict)]
    metrics = [item for item in (payload.get("structure_metrics") or []) if isinstance(item, dict)]
    reactions = [item for item in (payload.get("price_reactions") or []) if isinstance(item, dict)]

    first_event = events[0] if events else {}
    event_title = str(first_event.get("title") or "").strip()
    if event_title:
        highlights.append(f"事件：{event_title}")

    first_factor = factors[0] if factors else {}
    factor_name = str(first_factor.get("factor_name") or "").strip()
    if factor_name:
        factor_value = first_factor.get("value")
        factor_unit = str(first_factor.get("unit") or "").strip()
        factor_text = factor_name
        if factor_value not in {None, ""}:
            try:
                factor_text += f"={float(factor_value):.3f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                factor_text += f"={factor_value}"
        factor_text += factor_unit
        highlights.append(f"因子：{factor_text}")

    first_metric = metrics[0] if metrics else {}
    metric_name = str(first_metric.get("metric_name") or "").strip()
    if metric_name:
        highlights.append(f"结构：{metric_name}")

    first_reaction = reactions[0] if reactions else {}
    reaction_label = str(first_reaction.get("reaction_label") or "").strip()
    if reaction_label:
        highlights.append(f"验证：{reaction_label}")

    return {
        "summary": (
            f"市场数据底座已命中 {event_count} 条事件、{factor_count} 条因子、"
            f"{metric_count} 条结构指标、{reaction_count} 条价格验证、{log_count} 条 Agent 日志。"
        ),
        "highlights": highlights[:4],
    }


def _build_market_data_catalog(
    asset_class: str,
    sync_plan: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    factors: List[Dict[str, Any]],
    metrics: List[Dict[str, Any]],
    reactions: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    plan_datasets = {
        str(item.get("dataset") or "").strip()
        for item in (sync_plan or [])
        if str(item.get("dataset") or "").strip()
    }
    event_type_counts: Dict[str, int] = {}
    for item in events:
        key = str(item.get("event_type") or "").strip()
        if key:
            event_type_counts[key] = event_type_counts.get(key, 0) + 1
    factor_key_counts: Dict[str, int] = {}
    for item in factors:
        for key in [str(item.get("factor_group") or "").strip(), str(item.get("factor_name") or "").strip()]:
            if key:
                factor_key_counts[key] = factor_key_counts.get(key, 0) + 1
    metric_key_counts: Dict[str, int] = {}
    for item in metrics:
        for key in [str(item.get("metric_name") or "").strip(), str(item.get("source_name") or "").strip()]:
            if key:
                metric_key_counts[key] = metric_key_counts.get(key, 0) + 1
    reaction_count = len(reactions or [])
    log_count = len(logs or [])
    registry: Dict[str, List[Dict[str, Any]]] = {
        "equity": [
            {"dataset": "stock_profit_forecast", "label": "盈利预测", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("earnings", 0), "description": "看一致预期是否上修或下修。", "analysis": "把盈利预期变化与价格趋势对照，判断上涨是否由基本面驱动。"},
            {"dataset": "stock_fund_flow", "label": "个股资金流", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("fund_flow", 0), "description": "看主力净流入和情绪热度。", "analysis": "消息若没有资金承接，通常只能形成短波动。"},
            {"dataset": "stock_hsgt", "label": "北向资金", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("cross_border_flow", 0), "description": "看外资风险偏好。", "analysis": "适合判断指数与核心权重股是否获得跨境增配。"},
            {"dataset": "stock_repurchase", "label": "回购事件", "category": "event", "storage": "事件事实", "count": event_type_counts.get("share_repurchase", 0), "description": "看管理层对估值的态度。", "analysis": "回购与价格走强叠加时，可信度更高。"},
            {"dataset": "stock_restricted_release", "label": "解禁事件", "category": "event", "storage": "事件事实", "count": event_type_counts.get("restricted_release", 0), "description": "看供给压力释放。", "analysis": "在上涨末端尤其要检查解禁是否会破坏趋势。"},
            {"dataset": "macro_calendar", "label": "宏观日历", "category": "event", "storage": "事件事实", "count": event_type_counts.get("macro_calendar", 0), "description": "看指数与板块的宏观催化。", "analysis": "把指数行情与 CPI、非农、PMI 等时点做映射。"},
            {"dataset": "price_reactions", "label": "价格验证", "category": "reaction", "storage": "价格验证", "count": reaction_count, "description": "看事件后收益与方向是否兑现。", "analysis": "只保留消息、资金、价格三者同向的交易主线。"},
            {"dataset": "agent_logs", "label": "Agent 日志", "category": "agent_log", "storage": "Agent 日志", "count": log_count, "description": "看研究过程是否改变结论。", "analysis": "帮助回溯哪些证据真正改变了交易判断。"},
        ],
        "commodity_futures": [
            {"dataset": "futures_inventory", "label": "商品库存", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("inventory", 0), "description": "看现货供给是否偏紧或偏松。", "analysis": "库存下降配合上涨更偏强趋势，库存累积时要警惕回撤。"},
            {"dataset": "futures_basis", "label": "现货基差", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("basis", 0), "description": "看现货与期货的强弱关系。", "analysis": "基差走强说明现货偏紧，适合验证趋势是否健康。"},
            {"dataset": "macro_calendar", "label": "宏观日历", "category": "event", "storage": "事件事实", "count": event_type_counts.get("macro_calendar", 0), "description": "看通胀、美元、需求预期冲击。", "analysis": "尤其适合把商品波动映射到美国数据与国内政策窗口。"},
            {"dataset": "price_reactions", "label": "价格验证", "category": "reaction", "storage": "价格验证", "count": reaction_count, "description": "看事件后期货是否延续。", "analysis": "用来判断库存和基差信号是否真的被市场定价。"},
            {"dataset": "agent_logs", "label": "Agent 日志", "category": "agent_log", "storage": "Agent 日志", "count": log_count, "description": "看供给/需求/宏观哪条线改变了结论。", "analysis": "回看推演是否过度依赖单一叙事。"},
        ],
        "fx": [
            {"dataset": "macro_calendar", "label": "宏观日历", "category": "event", "storage": "事件事实", "count": event_type_counts.get("macro_calendar", 0), "description": "看非农、通胀、PMI 等直接催化。", "analysis": "先做事件时点对齐，再判断是否改变货币对主逻辑。"},
            {"dataset": "central_bank_rate", "label": "央行决议", "category": "event", "storage": "事件事实", "count": event_type_counts.get("central_bank_rate", 0), "description": "看基准利率与措辞变化。", "analysis": "外汇最核心的是相对利差变化，而不是单边看某一家央行。"},
            {"dataset": "cftc", "label": "CFTC 持仓", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("cftc_net_position", 0), "description": "看投机资金净多净空。", "analysis": "适合识别主题是否已过度拥挤，防止追高追空。"},
            {"dataset": "fx_structure", "label": "外汇结构因子", "category": "structure", "storage": "结构指标", "count": metric_key_counts.get("derived_fx_market_data", 0), "description": "看利差、surprise 差和美元压力。", "analysis": "优先用结构因子解释货币对的中短线主方向。"},
            {"dataset": "price_reactions", "label": "价格验证", "category": "reaction", "storage": "价格验证", "count": reaction_count, "description": "看事件后 30m/120m 是否跟随。", "analysis": "过滤只会制造波动、不产生趋势的外汇新闻。"},
            {"dataset": "agent_logs", "label": "Agent 日志", "category": "agent_log", "storage": "Agent 日志", "count": log_count, "description": "看哪轮证据改变了方向判断。", "analysis": "适合复盘为何从看多切到看空，或相反。"},
        ],
        "rates_futures": [
            {"dataset": "bond_yield_curve", "label": "收益率曲线", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("yield_curve", 0), "description": "看 2Y/5Y/10Y/30Y 曲线形态。", "analysis": "利率期货核心是期限利差变化，而不是单点利率。"},
            {"dataset": "repo_rate", "label": "回购利率", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("funding", 0), "description": "看资金面是否收紧。", "analysis": "适合判断短端利率期货的资金扰动。"},
            {"dataset": "swap_curve", "label": "FR007 互换", "category": "factor", "storage": "因子快照", "count": factor_key_counts.get("swap_curve", 0), "description": "看利率预期曲线。", "analysis": "和国债收益率曲线结合看，能区分预期变化和供给变化。"},
            {"dataset": "macro_calendar", "label": "宏观日历", "category": "event", "storage": "事件事实", "count": event_type_counts.get("macro_calendar", 0), "description": "看政策与宏观数据窗口。", "analysis": "利率期货对增长/通胀数据和政策时点极敏感。"},
            {"dataset": "price_reactions", "label": "价格验证", "category": "reaction", "storage": "价格验证", "count": reaction_count, "description": "看宏观数据后曲线是否真的重定价。", "analysis": "可验证曲线陡峭化或平坦化是否持续。"},
            {"dataset": "agent_logs", "label": "Agent 日志", "category": "agent_log", "storage": "Agent 日志", "count": log_count, "description": "看资金面与基本面哪个在主导。", "analysis": "适合复盘对利率方向误判的来源。"},
        ],
        "macro": [
            {"dataset": "macro_calendar", "label": "宏观日历", "category": "event", "storage": "事件事实", "count": event_type_counts.get("macro_calendar", 0), "description": "看宏观事件主线。", "analysis": "先定义主线主题，再筛选真正能引发价格反应的数据点。"},
            {"dataset": "central_bank_rate", "label": "央行决议", "category": "event", "storage": "事件事实", "count": event_type_counts.get("central_bank_rate", 0), "description": "看政策方向。", "analysis": "适合构建跨资产顶层宏观框架。"},
            {"dataset": "price_reactions", "label": "价格验证", "category": "reaction", "storage": "价格验证", "count": reaction_count, "description": "看事件是否被市场共同定价。", "analysis": "用价格验证筛掉只在新闻层有效、没进入交易层的事件。"},
            {"dataset": "agent_logs", "label": "Agent 日志", "category": "agent_log", "storage": "Agent 日志", "count": log_count, "description": "看宏观推演过程。", "analysis": "帮助回顾哪类宏观证据最常改变结论。"},
        ],
    }
    catalog = registry.get(asset_class, registry["macro"])
    results: List[Dict[str, Any]] = []
    for item in catalog:
        dataset = str(item.get("dataset") or "")
        count = int(item.get("count", 0) or 0)
        results.append(
            {
                "dataset": dataset,
                "label": item.get("label", dataset),
                "category": item.get("category", ""),
                "storage": item.get("storage", ""),
                "sync_enabled": dataset in plan_datasets,
                "status": "已同步" if count > 0 else ("可同步" if dataset in plan_datasets else "待扩展"),
                "count": count,
                "description": item.get("description", ""),
                "analysis": item.get("analysis", ""),
            }
        )
    return results


def _build_market_data_analysis_playbook(asset_class: str, catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    available_labels = [str(item.get("label") or "") for item in catalog if int(item.get("count", 0) or 0) > 0][:4]
    available_text = "、".join([item for item in available_labels if item]) or "当前已同步数据"
    playbooks = {
        "equity": [
            {"step": "先找催化", "focus": "事件事实 + 宏观日历", "method": "先识别财报、政策、行业催化，再判断是否真正改变盈利预期。"},
            {"step": "再看资金", "focus": "个股资金流 + 北向资金", "method": "消息若没有资金承接，通常只能形成短波动。"},
            {"step": "最后验价", "focus": "价格验证", "method": "只保留消息、资金、价格三者同向的交易主线。"},
        ],
        "commodity_futures": [
            {"step": "先看供需", "focus": "库存 + 基差", "method": "库存和基差是商品趋势最直接的基本面锚。"},
            {"step": "再看宏观", "focus": "宏观日历", "method": "把美元、通胀、增长预期当作第二层驱动。"},
            {"step": "最后验价", "focus": "价格验证", "method": "供需和宏观都支持但价格不跟随时，要降低仓位。"},
        ],
        "fx": [
            {"step": "先定主轴", "focus": "央行决议 + 外汇结构因子", "method": "用利差、surprise 差和美元压力定义货币对主方向。"},
            {"step": "再找催化", "focus": "宏观日历", "method": "把非农、CPI、PMI 等数据当作触发器，而不是孤立事件。"},
            {"step": "最后看拥挤度", "focus": "CFTC 持仓 + 价格验证", "method": f"结合 {available_text}，判断主题是否已过度拥挤或仍有延续空间。"},
        ],
        "rates_futures": [
            {"step": "先看曲线", "focus": "收益率曲线 + 互换曲线", "method": "先判断是牛陡、牛平还是熊陡、熊平。"},
            {"step": "再看资金面", "focus": "回购利率", "method": "短端利率与资金面扰动往往先影响盘面节奏。"},
            {"step": "最后映射宏观", "focus": "宏观日历 + 价格验证", "method": "确认数据冲击后曲线是否真的重定价。"},
        ],
        "macro": [
            {"step": "先做主题归因", "focus": "宏观日历 + 央行决议", "method": "把零散新闻归并成少数几个宏观主线。"},
            {"step": "再看跨资产", "focus": "价格验证", "method": "观察是否同时反映在汇率、利率、股指、商品。"},
            {"step": "最后沉淀经验", "focus": "Agent 日志", "method": "保留真正改变跨资产价格的宏观证据模板。"},
        ],
    }
    return playbooks.get(asset_class, playbooks["macro"])


def _build_market_data_sync_plan(current_market: str, current_code: str, product_info: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    today_ymd = datetime.now().strftime("%Y-%m-%d")
    today_plain = datetime.now().strftime("%Y%m%d")
    product_type = str((product_info or {}).get("type") or "").lower()
    normalized_symbol = str(
        (product_info or {}).get("akshare_symbol")
        or (product_info or {}).get("symbol")
        or current_code
        or ""
    ).strip()
    if asset_class == "equity":
        return [
            {"dataset": "stock_profit_forecast", "label": "盈利预测", "args": {"symbol": str(current_code or "")}},
            {"dataset": "stock_fund_flow", "label": "个股资金流", "args": {"indicator": "即时"}},
            {"dataset": "stock_hsgt", "label": "北向资金", "args": {}},
            {"dataset": "stock_repurchase", "label": "回购事件", "args": {}},
            {"dataset": "stock_restricted_release", "label": "解禁事件", "args": {"symbol": "全部股票", "start_date": today_ymd, "end_date": today_ymd}},
        ]
    if asset_class == "commodity_futures":
        tasks = [{"dataset": "futures_basis", "label": "现货基差", "args": {"trade_date": today_plain}}]
        if product_type in {"futures", "期货", "commodity_futures", "股指期货"} or normalized_symbol:
            tasks.insert(0, {"dataset": "futures_inventory", "label": "商品库存", "args": {"symbol": normalized_symbol}})
        tasks.append({"dataset": "macro_calendar", "label": "宏观日历", "args": {"date": today_ymd}})
        return tasks
    if asset_class == "rates_futures":
        return [
            {"dataset": "bond_yield_curve", "label": "收益率曲线", "args": {}},
            {"dataset": "repo_rate", "label": "回购利率", "args": {}},
            {"dataset": "swap_curve", "label": "FR007 互换", "args": {"symbol": "FR007"}},
            {"dataset": "macro_calendar", "label": "宏观日历", "args": {"date": today_ymd}},
        ]
    if asset_class == "fx":
        fx_profile = _build_fx_market_data_profile(current_code, product_info)
        tasks: List[Dict[str, Any]] = [
            {"dataset": "macro_calendar", "label": "宏观日历", "args": {"date": today_ymd}},
        ]
        for bank in fx_profile.get("central_banks", [])[:2]:
            bank_label_map = {
                "federal_reserve": "美联储决议",
                "ecb": "欧洲央行决议",
                "boe": "英国央行决议",
                "boj": "日本央行决议",
                "rba": "澳洲联储决议",
                "rbnz": "新西兰联储决议",
                "snb": "瑞士央行决议",
                "boc": "加拿大央行决议",
                "pboc": "中国央行决议",
            }
            tasks.append(
                {
                    "dataset": "central_bank_rate",
                    "label": bank_label_map.get(bank, f"{bank} 决议"),
                    "args": {"bank": bank},
                }
            )
        cftc_symbol = str(fx_profile.get("cftc_symbol") or "").strip()
        if cftc_symbol:
            tasks.append({"dataset": "cftc", "label": "CFTC 持仓", "args": {"symbol": fx_profile.get("canonical_code") or cftc_symbol}})
        return tasks
    return [
        {"dataset": "macro_calendar", "label": "宏观日历", "args": {"date": today_ymd}},
        {"dataset": "central_bank_rate", "label": "美联储决议", "args": {"bank": "federal_reserve"}},
        {"dataset": "central_bank_rate", "label": "欧洲央行决议", "args": {"bank": "ecb"}},
    ]


def _build_fx_structure_metrics_from_task_records(
    current_code: str,
    product_info: Optional[Dict[str, Any]],
    task_records: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    fx_profile = _build_fx_market_data_profile(current_code, product_info)
    canonical_code = str(fx_profile.get("canonical_code") or current_code or "").strip()
    base_currency = str(fx_profile.get("base_currency") or "").strip().upper()
    quote_currency = str(fx_profile.get("quote_currency") or "").strip().upper()
    if not canonical_code:
        return []

    bank_to_currency = {
        "federal_reserve": "USD",
        "ecb": "EUR",
        "boe": "GBP",
        "boj": "JPY",
        "rba": "AUD",
        "rbnz": "NZD",
        "snb": "CHF",
        "boc": "CAD",
        "pboc": "CNY",
    }
    event_records = [item for item in (task_records.get("central_bank_rate") or []) if isinstance(item, dict)]
    latest_event_by_currency: Dict[str, Dict[str, Any]] = {}
    for item in event_records:
        currency = bank_to_currency.get(str(item.get("region") or "").strip().lower(), "")
        if not currency:
            continue
        event_time = item.get("effective_at") or item.get("published_at")
        existing = latest_event_by_currency.get(currency)
        if existing is None or str(event_time or "") >= str(existing.get("effective_at") or existing.get("published_at") or ""):
            latest_event_by_currency[currency] = item

    metrics: List[Dict[str, Any]] = []
    metric_names_seen = set()

    def _append_metric(metric_name: str, metric_value: Optional[float], metadata: Dict[str, Any], as_of_time: Any):
        if metric_value is None or metric_name in metric_names_seen:
            return
        metric_names_seen.add(metric_name)
        metrics.append(
            {
                "asset_class": "fx",
                "symbol": canonical_code,
                "metric_name": metric_name,
                "metric_value": float(metric_value),
                "window": "latest",
                "cross_section_rank": None,
                "source_name": "derived_fx_market_data",
                "as_of_time": as_of_time or datetime.now(),
                "metadata": metadata,
            }
        )

    base_event = latest_event_by_currency.get(base_currency, {})
    quote_event = latest_event_by_currency.get(quote_currency, {})
    base_rate = base_event.get("actual_value")
    quote_rate = quote_event.get("actual_value")
    base_surprise = base_event.get("surprise_value")
    quote_surprise = quote_event.get("surprise_value")
    as_of_candidates = [base_event.get("effective_at"), quote_event.get("effective_at")]
    as_of_time = next((item for item in as_of_candidates if item), datetime.now())

    if base_rate is not None and quote_rate is not None:
        _append_metric(
            "policy_rate_differential",
            float(base_rate) - float(quote_rate),
            {
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "base_rate": base_rate,
                "quote_rate": quote_rate,
            },
            as_of_time,
        )

    if base_surprise is not None and quote_surprise is not None:
        _append_metric(
            "policy_surprise_differential",
            float(base_surprise) - float(quote_surprise),
            {
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "base_surprise": base_surprise,
                "quote_surprise": quote_surprise,
            },
            as_of_time,
        )

    cftc_records = [item for item in (task_records.get("cftc") or []) if isinstance(item, dict)]
    if cftc_records:
        latest_cftc = sorted(cftc_records, key=lambda item: str(item.get("as_of_time") or ""), reverse=True)[0]
        cftc_value = latest_cftc.get("value")
        cftc_as_of_time = latest_cftc.get("as_of_time") or datetime.now()
        if cftc_value is not None:
            _append_metric(
                "cftc_positioning_bias",
                float(cftc_value),
                {
                    "reference_symbol": latest_cftc.get("symbol"),
                    "factor_group": latest_cftc.get("factor_group"),
                },
                cftc_as_of_time,
            )
            if base_currency == "USD":
                _append_metric(
                    "usd_counter_currency_pressure",
                    float(-cftc_value),
                    {
                        "reference_symbol": latest_cftc.get("symbol"),
                        "quote_currency": quote_currency,
                    },
                    cftc_as_of_time,
                )
            elif quote_currency == "USD":
                _append_metric(
                    "usd_counter_currency_pressure",
                    float(cftc_value),
                    {
                        "reference_symbol": latest_cftc.get("symbol"),
                        "base_currency": base_currency,
                    },
                    cftc_as_of_time,
                )

    if base_rate is not None and quote_rate is not None:
        direction_value = float(base_rate) - float(quote_rate)
        _append_metric(
            "policy_relative_strength_score",
            1.0 if direction_value > 0 else (-1.0 if direction_value < 0 else 0.0),
            {
                "base_currency": base_currency,
                "quote_currency": quote_currency,
            },
            as_of_time,
        )
    return metrics


def _execute_market_data_sync_task(adapter: AkshareMarketDataAdapter, task: Dict[str, Any]) -> List[Dict[str, Any]]:
    dataset = str((task or {}).get("dataset") or "")
    args = dict((task or {}).get("args") or {})
    if dataset == "macro_calendar":
        return adapter.fetch_macro_calendar_events(**args)
    if dataset == "central_bank_rate":
        return adapter.fetch_central_bank_rate_events(**args)
    if dataset == "cftc":
        return adapter.fetch_cftc_snapshots(**args)
    if dataset == "futures_inventory":
        return adapter.fetch_futures_inventory_snapshots(**args)
    if dataset == "futures_basis":
        return adapter.fetch_futures_basis_snapshots(**args)
    if dataset == "stock_profit_forecast":
        return adapter.fetch_stock_profit_forecast_snapshots(**args)
    if dataset == "stock_fund_flow":
        return adapter.fetch_stock_fund_flow_snapshots(**args)
    if dataset == "stock_hsgt":
        return adapter.fetch_stock_hsgt_snapshots()
    if dataset == "stock_repurchase":
        return adapter.fetch_stock_repurchase_events()
    if dataset == "stock_restricted_release":
        return adapter.fetch_stock_restricted_release_events(**args)
    if dataset == "bond_yield_curve":
        return adapter.fetch_bond_yield_curve_snapshots(**args)
    if dataset == "repo_rate":
        return adapter.fetch_repo_rate_snapshots()
    if dataset == "swap_curve":
        return adapter.fetch_swap_curve_snapshots(**args)
    return []


def _build_market_data_view_payload(current_market: str, current_code: str, limit: int = 8) -> Dict[str, Any]:
    product_info = _get_product_info(current_code, current_market)
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    related_classes = _build_market_data_related_classes(asset_class)
    symbol_candidates = _build_market_data_symbol_candidates(current_code, product_info)

    event_rows: List[Any] = []
    factor_rows: List[Any] = []
    metric_rows: List[Any] = []
    reaction_rows: List[Any] = []
    log_rows: List[Any] = []

    for symbol in symbol_candidates[:2]:
        if not symbol:
            continue
        event_rows.extend(db.market_event_fact_query(symbol=symbol, limit=limit))
        factor_rows.extend(db.market_factor_snapshot_query(symbol=symbol, limit=limit))
        metric_rows.extend(db.market_structure_metric_query(symbol=symbol, limit=limit))
        reaction_rows.extend(db.event_price_reaction_query(symbol=symbol, frequency="30m", limit=limit))
        log_rows.extend(db.agent_inference_log_query(symbol=symbol, limit=limit))

    for item_class in related_classes:
        event_rows.extend(db.market_event_fact_query(asset_class=item_class, limit=limit))
        factor_rows.extend(db.market_factor_snapshot_query(asset_class=item_class, limit=limit))
        metric_rows.extend(db.market_structure_metric_query(asset_class=item_class, limit=limit))

    unique_events = _limit_unique_records(event_rows, "event_uid", limit)
    unique_factors = _limit_unique_records(factor_rows, "snapshot_uid", limit)
    unique_metrics = _limit_unique_records(metric_rows, "metric_uid", limit)
    unique_reactions = _limit_unique_records(reaction_rows, "reaction_uid", limit)
    unique_logs = _limit_unique_records(log_rows, "id", limit)
    serialized_events = [_serialize_market_event_fact(item) for item in unique_events]
    serialized_factors = [_serialize_market_factor_snapshot(item) for item in unique_factors]
    serialized_metrics = [_serialize_market_structure_metric(item) for item in unique_metrics]
    serialized_reactions = [_serialize_event_price_reaction(item) for item in unique_reactions]
    serialized_logs = [_serialize_agent_inference_log(item) for item in unique_logs]
    sync_plan = _build_market_data_sync_plan(current_market, current_code, product_info)
    data_catalog = _build_market_data_catalog(
        asset_class,
        sync_plan,
        serialized_events,
        serialized_factors,
        serialized_metrics,
        serialized_reactions,
        serialized_logs,
    )
    analysis_playbook = _build_market_data_analysis_playbook(asset_class, data_catalog)
    synced_types = len([item for item in data_catalog if int(item.get("count", 0) or 0) > 0])

    return {
        "asset": {
            "market": current_market,
            "code": current_code,
            "name": product_info.get("name_cn") or product_info.get("name_en") or current_code,
            "asset_class": asset_class,
            "related_asset_classes": related_classes,
        },
        "summary": {
            "event_count": len(unique_events),
            "factor_count": len(unique_factors),
            "metric_count": len(unique_metrics),
            "reaction_count": len(unique_reactions),
            "agent_log_count": len(unique_logs),
            "catalog_total": len(data_catalog),
            "catalog_synced": synced_types,
        },
        "sync_plan": sync_plan,
        "data_catalog": data_catalog,
        "analysis_playbook": analysis_playbook,
        "events": serialized_events,
        "factors": serialized_factors,
        "structure_metrics": serialized_metrics,
        "price_reactions": serialized_reactions,
        "agent_logs": serialized_logs,
        "updated_at": datetime.now().isoformat(),
    }


def _sync_market_data_for_asset(current_market: str, current_code: str) -> Dict[str, Any]:
    product_info = _get_product_info(current_code, current_market)
    plan = _build_market_data_sync_plan(current_market, current_code, product_info)
    asset_class = _resolve_market_data_asset_class(current_market, product_info)
    adapter = AkshareMarketDataAdapter(db_instance=db)
    if not adapter.available:
        raise RuntimeError("AkShare 当前不可用，无法同步市场数据")
    task_results: List[Dict[str, Any]] = []
    total_saved = 0
    task_records: Dict[str, List[Dict[str, Any]]] = {}
    for task in plan:
        dataset_name = str(task.get("dataset") or "")
        dataset_type = "event" if dataset_name in {"macro_calendar", "central_bank_rate", "stock_repurchase", "stock_restricted_release"} else "factor"
        try:
            records = _execute_market_data_sync_task(adapter, task)
            task_records.setdefault(dataset_name, [])
            task_records[dataset_name].extend(records or [])
            saved = adapter.sync_records(dataset_type, records)
            total_saved += int(saved)
            task_results.append({"dataset": dataset_name, "label": task.get("label"), "saved": int(saved), "error": ""})
        except Exception as e:
            logger.warning(f"同步市场数据失败 {dataset_name}: {str(e)}")
            task_results.append({"dataset": dataset_name, "label": task.get("label"), "saved": 0, "error": str(e)})
    if asset_class == "fx":
        try:
            structure_records = _build_fx_structure_metrics_from_task_records(current_code, product_info, task_records)
            saved = adapter.sync_records("structure", structure_records)
            total_saved += int(saved)
            task_results.append({"dataset": "fx_structure", "label": "外汇结构因子", "saved": int(saved), "error": ""})
        except Exception as e:
            logger.warning(f"同步市场数据失败 fx_structure: {str(e)}")
            task_results.append({"dataset": "fx_structure", "label": "外汇结构因子", "saved": 0, "error": str(e)})
    payload = _build_market_data_view_payload(current_market, current_code, limit=8)
    payload["sync_result"] = {"tasks": task_results, "saved_total": total_saved}
    return payload


def register_vector_api_routes(app):
    """
    注册向量数据库相关的API路由
    
    Args:
        app: Flask应用实例
    """

    def _service_trace_id() -> str:
        return str(request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:20]).strip()

    def _service_auth_token() -> str:
        return str(
            os.environ.get("CHANLUN_SERVICE_TOKEN")
            or os.environ.get("CL_SERVICE_TOKEN")
            or getattr(config, "SERVICE_TOKEN", "")
            or getattr(config, "LOGIN_PWD", "")
            or ""
        ).strip()

    def _service_context(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        current_user_id = ""
        if getattr(current_user, "is_authenticated", False):
            current_user_id = str(current_user.get_id() or "").strip()
        return {
            "tenant_id": str(request.headers.get("X-Tenant-Id") or payload.get("tenant_id") or "default").strip() or "default",
            "user_id": str(request.headers.get("X-User-Id") or payload.get("user_id") or current_user_id or "service").strip() or "service",
            "session_id": str(request.headers.get("X-Session-Id") or payload.get("session_id") or "").strip(),
            "trace_id": _service_trace_id(),
            "request_source": str(request.headers.get("X-Request-Source") or payload.get("request_source") or "service").strip(),
        }

    def _service_json_success(data: Any, meta: Optional[Dict[str, Any]] = None, session_id: str = "", trace_id: str = ""):
        return jsonify(
            {
                "success": True,
                "trace_id": trace_id or _service_trace_id(),
                "session_id": session_id or "",
                "data": data,
                "meta": meta or {},
            }
        )

    def _service_json_error(
        code: str,
        message: str,
        status_code: int,
        trace_id: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "trace_id": trace_id or _service_trace_id(),
                    "error": {
                        "code": code,
                        "message": message,
                        "details": details or {},
                    },
                }
            ),
            status_code,
        )

    def _require_service_auth(payload: Optional[Dict[str, Any]] = None):
        expected_token = _service_auth_token()
        auth_header = str(request.headers.get("Authorization") or "").strip()
        supplied_token = ""
        if auth_header.lower().startswith("bearer "):
            supplied_token = auth_header[7:].strip()
        if not supplied_token:
            supplied_token = str(request.headers.get("X-Service-Token") or "").strip()
        if expected_token and supplied_token != expected_token:
            context = _service_context(payload)
            return _service_json_error(
                code="UNAUTHORIZED",
                message="服务鉴权失败",
                status_code=401,
                trace_id=context["trace_id"],
            )
        return None

    def _build_service_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = dict(payload or {})
        if "market" in payload and "current_market" not in payload:
            payload["current_market"] = payload.get("market")
        if "code" in payload and "current_code" not in payload:
            payload["current_code"] = payload.get("code")
        if "theme_text" in payload and "theme_label" not in payload:
            payload["theme_label"] = payload.get("theme_text")
        if "theme_id" in payload and "theme_label" not in payload:
            payload["theme_label"] = payload.get("theme_id")
        context = _service_context(payload)
        payload.setdefault("tenant_id", context["tenant_id"])
        payload.setdefault("user_id", context["user_id"])
        payload.setdefault("session_id", context["session_id"])
        payload.setdefault("request_source", context["request_source"])
        payload.setdefault("trace_id", context["trace_id"])
        return payload
    
    @app.route('/api/chanlun_data')
    def get_chanlun_data():
        """获取缠论数据API"""
        market = request.args.get('market', 'a')
        code = request.args.get('code', 'sh.000001')
        frequency = request.args.get('frequency', 'd')
        
        try:
            from chanlun.cl_utils import web_batch_get_cl_datas, query_cl_chart_config
            from chanlun.exchange import get_exchange
            
            # 获取交易所对象 - 将字符串转换为Market枚举
            from chanlun.base import Market
            try:
                market_enum = Market(market)
                ex = get_exchange(market_enum)
            except ValueError:
                return jsonify({
                    'error': f'不支持的市场类型: {market}'
                })
            
            # 这里可以添加更多的缠论数据处理逻辑
            return jsonify({'message': 'API under development'})
            
        except Exception as e:
            return jsonify({'error': str(e)})
    
    @app.route("/api/news/market_summary/list", methods=["GET"])
    @login_required
    def get_market_summary_list():
        """
        获取研究报告列表API
        
        查询参数:
        - page: 页码，默认1
        - limit: 每页数量，默认20
        - market: 市场筛选
        - code: 标的代码筛选
        - start_date: 开始日期
        - end_date: 结束日期
        
        返回:
        {
            "code": 0,
            "msg": "查询成功",
            "data": {
                "list": [总结列表],
                "total": 总数,
                "page": 当前页,
                "limit": 每页数量
            }
        }
        """
        try:
            from chanlun.db import db
            import datetime
            
            # 获取查询参数
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            market = request.args.get('market')
            code = request.args.get('code')
            summary_type = request.args.get('summary_type')
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            # 处理日期参数
            start_date = None
            end_date = None
            if start_date_str:
                try:
                    start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
                except ValueError:
                    pass
            if end_date_str:
                try:
                    end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                except ValueError:
                    pass
            
            # 计算偏移量
            offset = (page - 1) * limit
            
            market_filter_map = {
                'STOCK': 'a',
                'FOREX': 'fx',
                'FUTURES': 'futures',
                'all': None,
                'ALL': None,
                'UNKNOWN': None,
            }
            normalized_market = market_filter_map.get(market, market)

            if market == 'UNKNOWN':
                all_rows = db.market_summary_query(
                    limit=1000,
                    offset=0,
                    market=None,
                    code=code,
                    summary_type=summary_type,
                    start_date=start_date,
                    end_date=end_date
                )
                filtered_rows = [
                    row for row in all_rows
                    if (row.market or '').lower() not in {'a', 'fx', 'futures', 'all'}
                ]
                total_count = len(filtered_rows)
                summary_list = filtered_rows[offset: offset + limit]
            else:
                summary_list = db.market_summary_query(
                    limit=limit,
                    offset=offset,
                    market=normalized_market,
                    code=code,
                    summary_type=summary_type,
                    start_date=start_date,
                    end_date=end_date
                )
                
                total_count = db.market_summary_count(
                    market=normalized_market,
                    code=code,
                    summary_type=summary_type,
                    start_date=start_date,
                    end_date=end_date
                )
            
            # 转换为字典格式
            summary_data = []
            for summary in summary_list:
                summary_dict = {
                    'id': summary.id,
                    'title': summary.title,
                    'content': summary.content,
                    'market': summary.market,
                    'code': summary.code,
                    'summary_type': summary.summary_type,
                    'created_at': summary.created_at.strftime('%Y-%m-%d %H:%M:%S') if summary.created_at else None,
                    'updated_at': summary.updated_at.strftime('%Y-%m-%d %H:%M:%S') if summary.updated_at else None
                }
                summary_data.append(summary_dict)
            
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "list": summary_data,
                    "total": total_count,
                    "page": page,
                    "limit": limit
                }
            })
            
        except Exception as e:
            logger.error(f"查询研究报告列表失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None
            })

    @app.route("/api/news/market_summary/stats", methods=["GET"])
    @login_required
    def get_market_summary_stats():
        try:
            import datetime

            code = request.args.get('code')
            summary_type = request.args.get('summary_type')
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            start_date = None
            end_date = None
            if start_date_str:
                try:
                    start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
                except ValueError:
                    pass
            if end_date_str:
                try:
                    end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                except ValueError:
                    pass

            total = db.market_summary_count(
                code=code,
                summary_type=summary_type,
                start_date=start_date,
                end_date=end_date,
            )
            stock_count = db.market_summary_count(
                market='a',
                code=code,
                summary_type=summary_type,
                start_date=start_date,
                end_date=end_date,
            )
            forex_count = db.market_summary_count(
                market='fx',
                code=code,
                summary_type=summary_type,
                start_date=start_date,
                end_date=end_date,
            )
            futures_count = db.market_summary_count(
                market='futures',
                code=code,
                summary_type=summary_type,
                start_date=start_date,
                end_date=end_date,
            )
            all_market_count = db.market_summary_count(
                market='all',
                code=code,
                summary_type=summary_type,
                start_date=start_date,
                end_date=end_date,
            )
            unknown_count = max(
                0,
                total - stock_count - forex_count - futures_count - all_market_count,
            )

            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "total": total,
                    "markets": {
                        "all": total,
                        "STOCK": stock_count,
                        "FOREX": forex_count,
                        "FUTURES": futures_count,
                        "UNKNOWN": unknown_count,
                    },
                    "summary_types": {
                        "market_analysis": db.market_summary_count(
                            code=code,
                            summary_type='market_analysis',
                            start_date=start_date,
                            end_date=end_date,
                        ),
                        "daily_news_summary": db.market_summary_count(
                            code=code,
                            summary_type='daily_news_summary',
                            start_date=start_date,
                            end_date=end_date,
                        ),
                        "historical_analysis": db.market_summary_count(
                            code=code,
                            summary_type='historical_analysis',
                            start_date=start_date,
                            end_date=end_date,
                        ),
                    }
                }
            })
        except Exception as e:
            logger.error(f"查询研究报告统计失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询统计失败: {str(e)}",
                "data": None
            })

    @app.route("/api/news/asset_news", methods=["GET"])
    @login_required
    def get_asset_news():
        try:
            asset_code = request.args.get("asset", "").strip()
            market = request.args.get("market", "").strip()
            days = max(1, min(int(request.args.get("days", 7)), 90))
            limit = max(5, min(int(request.args.get("limit", 20)), 100))

            if not asset_code:
                return jsonify({
                    "code": 400,
                    "msg": "缺少资产代码 asset",
                    "data": None,
                })

            data = _build_asset_news_response(
                asset_code=asset_code,
                market=market,
                days=days,
                limit=limit,
            )
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": data,
            })
        except Exception as e:
            logger.error(f"按资产查询新闻失败: {str(e)}", exc_info=True)
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/asset_links/backfill", methods=["POST"])
    @login_required
    def backfill_asset_links():
        try:
            data = request.get_json(silent=True) or {}
            limit = max(10, min(int(data.get("limit", 500)), 2000))
            days = max(1, min(int(data.get("days", 60)), 365))

            result = _backfill_news_asset_links(limit=limit, days=days)
            return jsonify({
                "code": 0,
                "msg": "资产关系回填完成",
                "data": result,
            })
        except Exception as e:
            logger.error(f"回填新闻资产关系失败: {str(e)}", exc_info=True)
            return jsonify({
                "code": 500,
                "msg": f"回填失败: {str(e)}",
                "data": None,
            })
    
    @app.route("/api/news/market_summary/<int:summary_id>", methods=["GET"])
    @login_required
    def get_market_summary_detail(summary_id):
        """
        获取研究报告详情API
        
        返回:
        {
            "code": 0,
            "msg": "查询成功",
            "data": {
                "summary": 总结详情
            }
        }
        """
        try:
            from chanlun.db import db
            
            summary = db.market_summary_get_by_id(summary_id)
            if not summary:
                return jsonify({
                    "code": 404,
                    "msg": "总结不存在",
                    "data": None
                })
            
            summary_dict = {
                'id': summary.id,
                'title': summary.title,
                'content': summary.content,
                'market': summary.market,
                'code': summary.code,
                'summary_type': summary.summary_type,
                'created_at': summary.created_at.strftime('%Y-%m-%d %H:%M:%S') if summary.created_at else None,
                'updated_at': summary.updated_at.strftime('%Y-%m-%d %H:%M:%S') if summary.updated_at else None
            }
            
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "summary": summary_dict
                }
            })
            
        except Exception as e:
            logger.error(f"查询研究报告详情失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/market_summary/<int:summary_id>/download", methods=["GET"])
    @login_required
    def download_market_summary(summary_id):
        """
        下载研究报告API
        
        返回文件下载
        """
        try:
            from chanlun.db import db
            from flask import Response
            import re
            
            summary = db.market_summary_get_by_id(summary_id)
            if not summary:
                return jsonify({
                    "code": 404,
                    "msg": "总结不存在",
                    "data": None
                })
            
            # 生成文件名
            filename = f"market_summary_{summary.id}_{summary.created_at.strftime('%Y%m%d_%H%M%S')}.md"
            
            # 生成Markdown内容
            content = f"# {summary.title}\n\n"
            content += f"**市场**: {summary.market or 'N/A'}\n\n"
            content += f"**标的代码**: {summary.code or 'N/A'}\n\n"
            content += f"**生成时间**: {summary.created_at.strftime('%Y-%m-%d %H:%M:%S') if summary.created_at else 'N/A'}\n\n"
            content += f"**总结类型**: {summary.summary_type or 'N/A'}\n\n"
            content += "---\n\n"
            content += summary.content or ''
            
            return Response(
                content,
                mimetype='text/markdown',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': 'text/markdown; charset=utf-8'
                }
            )
            
        except Exception as e:
            logger.error(f"下载研究报告失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"下载失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/market_summary/<int:summary_id>", methods=["DELETE"])
    @login_required
    def delete_market_summary(summary_id):
        """
        删除市场总结API
        
        请求参数:
        {
            "code": "验证码"
        }
        
        返回:
        {
            "code": 0,
            "msg": "删除成功",
            "data": null
        }
        """
        try:
            from chanlun.db import db
            
            # 获取请求参数
            if not request.is_json:
                return jsonify({
                    "code": 400,
                    "msg": "请求必须是JSON格式",
                    "data": None
                })
            
            data = request.get_json()
            verification_code = data.get('code', '')
            
            # 验证码校验（默认为'spdb'）
            if verification_code != 'spdb':
                return jsonify({
                    "code": 403,
                    "msg": "验证码错误，删除失败",
                    "data": None
                })
            
            # 检查总结是否存在
            summary = db.market_summary_get_by_id(summary_id)
            if not summary:
                return jsonify({
                    "code": 404,
                    "msg": "总结不存在",
                    "data": None
                })
            
            # 执行删除操作
            success = db.market_summary_delete(summary_id)
            
            if success:
                logger.info(f"市场总结删除成功: ID={summary_id}, 标题={summary.title}")
                return jsonify({
                    "code": 0,
                    "msg": "删除成功",
                    "data": None
                })
            else:
                return jsonify({
                    "code": 500,
                    "msg": "删除失败",
                    "data": None
                })
                
        except Exception as e:
            logger.error(f"删除市场总结失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"删除失败: {str(e)}",
                "data": None
            })
           
    @app.route("/api/news/semantic_search", methods=["POST"])
    @login_required
    def semantic_search_news():
        """
        语义搜索新闻API - 简化版本，获取与主题相关的前50条最新新闻
        
        请求参数:
        {
            "query": "搜索查询文本",
            "product_code": "产品代码(可选)",  # 如EURUSD, FE.EURUSD等
            "n_results": 50,  # 可选，返回结果数量，默认50
            "days": 7         # 可选，搜索最近几天的新闻，默认7天
        }
        
        返回:
        {
            "code": 0,
            "msg": "搜索成功",
            "data": {
                "results": [...],
                "total": 50,
                "query": "搜索查询文本",
                "product_info": {...},  # 产品信息
                "date_range": "最近7天"
            }
        }
        """
        try:
            # 获取请求参数
            if not request.is_json:
                return jsonify({
                    "code": 400,
                    "msg": "请求必须是JSON格式",
                    "data": None
                })
            
            data = request.get_json()
            query_payload = data.get('query')
            market = data.get('market', '')
            product_code = data.get('product_code', '')
            query = query_payload

            if isinstance(query_payload, dict):
                query = query_payload.get('query', '')
                product_code = query_payload.get('query', product_code)
                market = query_payload.get('market', market)

            if not query:
                return jsonify({
                    "code": 400,
                    "msg": "缺少查询参数 'query'",
                    "data": None
                })
            if not market:
                market = data.get('current_market', '')
            if not market:
                return jsonify({
                    "code": 400,
                    "msg": "缺少市场参数 'market'",
                    "data": None
                })

            n_results = max(1, min(int(data.get('n_results', 20)), 50))
            days = max(1, min(int(data.get('days', 7)), 30))
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            product_info = _get_product_info((product_code or query).strip().upper())

            search_results = get_vector_news(
                product_code or query,
                market,
                days,
                n_results=n_results,
                query=query,
                product_info=product_info,
            )

            return jsonify({
                "code": 0,
                "msg": "搜索成功",
                "data": {
                    "results": search_results,
                    "total": len(search_results),
                    "query": query,
                    "product_info": product_info,
                    "date_range": f"最近{days}天",
                    "search_period": {
                        "start_date": start_date.strftime('%Y-%m-%d'),
                        "end_date": end_date.strftime('%Y-%m-%d')
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"语义搜索失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"搜索失败: {str(e)}",
                "data": None
            })
    import json
    import re

    def extract_json_from_llm_response(
        response: Union[str, Dict, List]
    ) -> Union[Dict, List]:
        """
        【已升级】从LLM可能返回的各种格式中，智能地提取并返回一个Python对象（字典或列表）。

        Args:
            response: LLM返回的原始响应，可以是字符串、字典或列表。

        Returns:
            Union[Dict, List]: 解析后的Python对象。

        Raises:
            ValueError: 如果输入是字符串但无法解析为JSON。
        """
        # 1. 【新增】检查输入是否已经是我们想要的对象
        if isinstance(response, (dict, list)):
            print("输入已经是字典或列表，直接返回。")
            return response

        # 2. 【新增】检查输入是否为None或非字符串
        if not isinstance(response, str):
            raise TypeError(f"输入类型不受支持: {type(response)}。期望是字符串、字典或列表。")

        # 3. 如果是字符串，执行之前的解析逻辑
        print("输入是字符串，开始解析...")
        response_str = response.strip()
        
        # 尝试从Markdown代码块中提取
        match = re.search(r'```json\s*([\s\S]*?)\s*```', response_str)
        if match:
            json_str = match.group(1)
            print("成功从Markdown代码块中提取JSON。")
            return json.loads(json_str)

        # 尝试直接解析
        print("未找到Markdown代码块，尝试直接解析字符串...")
        return json.loads(response_str)
    def generate_search_keywords_with_llm(
        product_info: Dict[str, Any],
        market: str,
    ) -> List[str]:
        """
        【已升级】根据给定的金融资产信息，调用LLM生成一个用于新闻检索的、
        合并后的中英文关键词列表。

        Args:
            product_info (Dict[str, Any]): 包含name, code, category的字典。
            market (str): 市场代码，用于初始化AIAnalyse。

        Returns:
            List[str]: 一个包含了中英文、并已去重的关键词列表。
        """
        
        # 1. 【核心优化】修改Prompt，让LLM直接输出关键词
        prompt_template = """
    你是一位顶级的金融情报分析师，专长是为特定的金融资产构建全面的、多语言的信息检索策略。

    你的任务是：根据用户提供的**【目标资产】**，生成一个包含**中文和英文核心关键词**的JSON对象。

    **【目标资产】**: {product_info_json}

    **思考指南 (请在内部遵循此逻辑):**
    - 对于**外汇** (如EURUSD)，关键词应包括：两个经济体的名称、央行、关键经济数据（CPI, 非农）、领导人。
    - 对于**股票** (如浦发银行)，关键词应包括：公司名、行业、相关宏观政策（货币、房地产）、核心业务概念（不良贷款）。
    - 对于**大宗商品** (如黄金)，关键词应包括：商品名、金融属性（避险）、关键驱动因素（美元、实际利率）。

    ---
    现在，请为以下目标资产生成关键词。请严格按照只包含 `keywords_zh` 和 `keywords_en` 两个键的JSON格式输出，不要有任何额外的说明或注释。

    **【目标资产】**: {product_info_json}
    """
        
        product_info_json = json.dumps(product_info, ensure_ascii=False)
        prompt = prompt_template.format(product_info_json=product_info_json)
        
        try:
            # 2. 调用LLM
            # 假设 AIAnalyse 和 extract_json_from_llm_response 已经定义
            ai_analyse = AIAnalyse(market)
            response_str = ai_analyse.req_llm_ai_model(prompt)
            llm_content_str = response_str.get('msg')
            # 3. 解析JSON
            keyword_plan = extract_json_from_llm_response(llm_content_str)
            print('keyword_plan', keyword_plan)
            # 4. 验证、合并与去重
            keywords_zh = keyword_plan.get('keywords_zh', [])
            keywords_en = keyword_plan.get('keywords_en', [])
            
            if not isinstance(keywords_zh, list) or not isinstance(keywords_en, list):
                raise TypeError("LLM返回的关键词不是列表格式。")

            # 合并所有关键词
            all_keywords = keywords_zh + keywords_en
            
            # 去重并转换为小写（可选，但推荐，以避免 "USD" 和 "usd" 被视为不同）
            unique_keywords = sorted(list(set(k.lower() for k in all_keywords if k)))
            
            logger.info(f"成功为 {product_info.get('name')} 生成 {len(unique_keywords)} 个唯一关键词。")
            return unique_keywords
            
        except (TypeError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"为 {product_info.get('name')} 生成关键词失败: {e}", exc_info=True)
            # 在失败时，返回一个基于产品名称和代码的安全默认列表
            default_keywords = [
                product_info.get("name", ""),
                product_info.get("code", "").split('.')[-1]
            ]
            # 清理空值并去重
            return sorted(list(set(k.lower() for k in default_keywords if k)))
        except Exception as e:
            logger.error(f"调用LLM或处理时发生未知错误: {e}", exc_info=True)
            # 同样返回默认值
            default_keywords = [
                product_info.get("name", ""),
                product_info.get("code", "").split('.')[-1]
            ]
            return sorted(list(set(k.lower() for k in default_keywords if k)))
        
    

    # --- 智能评分辅助函数 ---

    # _calculate_smart_relevance_score函数已移除，直接使用semantic_search返回的score

    # --- 主函数 (重构版) ---

    def get_vector_news(
        code: str,
        market: str,
        days: int = 7,
        n_results: int = 50,
        query: Optional[str] = None,
        product_info: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """
        根据资产代码，从向量数据库获取相关新闻。
        
        优化版本特点：
        1. 单次综合搜索替代多次分别搜索
        2. 智能查询扩展，包含市场术语
        3. 基于匹配类型的智能评分
        4. 详细的调试日志和score分布统计

        Args:
            code (str): 资产代码 (e.g., "FE.EURUSD", "KH.01211")
            market (str): 市场代码 (e.g., "fx", "hk", "a")
            days (int): 检索最近N天的新闻
            n_results (int): 返回的新闻数量

        Returns:
            List[Dict]: 搜索到的新闻结果列表，每个新闻包含id、document、metadata等字段
        """
        return _get_vector_news_impl(
            code=code,
            market=market,
            days=days,
            n_results=n_results,
            query=query,
            product_info=product_info,
        )

    
    @app.route("/api/news/market_summary", methods=["POST"])  # pyright: ignore[reportUnreachable]
    @login_required
    def generate_market_summary():
        """
        生成研究报告API - 使用向量数据库搜索新闻
        
        请求体:
        {
            "query": "搜索查询文本",
            "current_market": "市场代码",
            "current_code": "标的代码",
            "product_code": "产品代码(可选)",
            "n_results": 20,  # 可选，搜索新闻数量，默认20
            "days": 7         # 可选，搜索最近几天的新闻，默认7天
        }
        
        返回:
        {
            "code": 0,
            "msg": "生成成功",
            "data": {
                "summary": "研究报告内容"
            }
        }
        """
        try:
            result = _generate_market_summary_payload(request.get_json())
            return jsonify({
                "code": 0,
                "msg": "生成成功",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"生成研究报告失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"生成失败: {str(e)}",
                "data": None
            })

    @app.route("/api/news/market_summary/async", methods=["POST"])
    @login_required
    def create_market_summary_task():
        try:
            payload = request.get_json()
            if not payload:
                return jsonify({
                    "code": 400,
                    "msg": "请求体不能为空",
                    "data": None,
                })

            task_id = uuid.uuid4().hex
            _set_market_summary_task(
                task_id,
                task_id=task_id,
                task_type="market_summary",
                state="queued",
                stage="queued",
                message="任务已提交，等待执行",
                progress=0,
                created_at=datetime.now().isoformat(),
                result=None,
                error="",
                params={
                    "current_market": payload.get("current_market", ""),
                    "current_code": payload.get("current_code", ""),
                    "product_code": payload.get("product_code", ""),
                    "days": payload.get("days", 7),
                    "frequency": payload.get("frequency", "d"),
                },
            )

            worker = threading.Thread(
                target=_run_market_summary_task,
                args=(task_id, payload),
                daemon=True,
            )
            worker.start()

            return jsonify({
                "code": 0,
                "msg": "市场总结任务已提交",
                "data": {
                    "task_id": task_id,
                    "state": "queued",
                },
            })
        except Exception as e:
            logger.error(f"创建市场总结任务失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"创建任务失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/market_summary/task/<task_id>", methods=["GET"])
    @login_required
    def get_market_summary_task(task_id: str):
        task = _get_market_summary_task(task_id)
        if not task:
            return jsonify({
                "code": 404,
                "msg": "任务不存在或已过期",
                "data": None,
            })

        return jsonify({
            "code": 0,
            "msg": "查询成功",
            "data": task,
        })
    
    @app.route("/api/news/similar/<news_id>", methods=["GET"])
    @login_required
    def get_similar_news(news_id: str):
        """
        获取相似新闻API
        
        URL参数:
        - news_id: 新闻ID
        
        查询参数:
        - n_results: 返回结果数量，默认5
        
        返回:
        {
            "code": 0,
            "msg": "获取成功",
            "data": {
                "similar_news": [...],
                "total": 5,
                "news_id": "原新闻ID"
            }
        }
        """
        try:
            n_results = request.args.get('n_results', 5, type=int)
            
            # 获取相似新闻
            vector_db = get_vector_db(db_path="./chroma_db")
            similar_news = vector_db.get_similar_news(
                news_id=news_id,
                n_results=n_results
            )
            
            return jsonify({
                "code": 0,
                "msg": "获取成功",
                "data": {
                    "similar_news": similar_news,
                    "total": len(similar_news),
                    "news_id": news_id
                }
            })
            
        except Exception as e:
            logger.error(f"获取相似新闻失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"获取相似新闻失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/market_relevant", methods=["GET"])
    @login_required
    def get_market_relevant_news():
        """
        获取市场相关新闻API
        
        查询参数:
        - min_relevance: 最小相关性分数，默认0.3
        - limit: 返回数量限制，默认100
        
        返回:
        {
            "code": 0,
            "msg": "获取成功",
            "data": {
                "market_news": [...],
                "total": 50,
                "min_relevance": 0.3
            }
        }
        """
        try:
            min_relevance = request.args.get('min_relevance', 0.3, type=float)
            limit = request.args.get('limit', 100, type=int)
            print('min_relevance',min_relevance)
            
            # 获取市场相关新闻
            vector_db = get_vector_db(db_path="./chroma_db")
            market_news = vector_db.get_market_relevant_news(
                min_relevance=min_relevance,
                limit=limit
            )
            
            return jsonify({
                "code": 0,
                "msg": "获取成功",
                "data": {
                    "market_news": market_news,
                    "total": len(market_news),
                    "min_relevance": min_relevance
                }
            })
            
        except Exception as e:
            logger.error(f"获取市场相关新闻失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"获取市场相关新闻失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/sentiment_analysis", methods=["GET"])
    @login_required
    def get_sentiment_analysis():
        """
        获取情感分析统计API
        
        查询参数:
        - start_date: 开始日期，格式: YYYY-MM-DD
        - end_date: 结束日期，格式: YYYY-MM-DD
        
        返回:
        {
            "code": 0,
            "msg": "获取成功",
            "data": {
                "total": 100,
                "positive": 30,
                "negative": 20,
                "neutral": 50,
                "avg_sentiment": 0.1,
                "sentiment_distribution": [...]
            }
        }
        """
        try:
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            start_date = None
            end_date = None
            
            if start_date_str:
                try:
                    start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
                except ValueError:
                    return jsonify({
                        "code": 400,
                        "msg": "开始日期格式错误，请使用 YYYY-MM-DD 格式",
                        "data": None
                    })
            
            if end_date_str:
                try:
                    end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
                    # 设置为当天结束时间
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                except ValueError:
                    return jsonify({
                        "code": 400,
                        "msg": "结束日期格式错误，请使用 YYYY-MM-DD 格式",
                        "data": None
                    })
            
            # 获取情感分析统计
            vector_db = get_vector_db(db_path="./chroma_db")
            sentiment_stats = vector_db.get_sentiment_analysis(
                start_date=start_date,
                end_date=end_date
            )
            
            return jsonify({
                "code": 0,
                "msg": "获取成功",
                "data": sentiment_stats
            })
            
        except Exception as e:
            logger.error(f"获取情感分析失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"获取情感分析失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/vector_stats", methods=["GET"])
    @login_required
    def get_vector_db_stats():
        """
        获取向量数据库统计信息API
        
        返回:
        {
            "code": 0,
            "msg": "获取成功",
            "data": {
                "total_documents": 1000,
                "collection_name": "news_vectors",
                "model_name": "paraphrase-multilingual-MiniLM-L12-v2",
                "db_path": "./chroma_db"
            }
        }
        """
        try:
            # 获取统计信息
            vector_db = get_vector_db(db_path="./chroma_db")
            stats = vector_db.get_collection_stats()
            
            return jsonify({
                "code": 0,
                "msg": "获取成功",
                "data": stats
            })
            
        except Exception as e:
            logger.error(f"获取向量数据库统计失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"获取向量数据库统计失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/vector_delete/<news_id>", methods=["DELETE"])
    @login_required
    def delete_news_vector(news_id: str):
        """
        删除新闻向量API
        
        URL参数:
        - news_id: 新闻ID
        
        返回:
        {
            "code": 0,
            "msg": "删除成功",
            "data": {
                "news_id": "删除的新闻ID"
            }
        }
        """
        try:
            # 删除新闻向量
            vector_db = get_vector_db(db_path="./chroma_db")
            success = vector_db.delete_news(news_id)
            
            if success:
                return jsonify({
                    "code": 0,
                    "msg": "删除成功",
                    "data": {
                        "news_id": news_id
                    }
                })
            else:
                return jsonify({
                    "code": 404,
                    "msg": "新闻不存在或删除失败",
                    "data": None
                })
            
        except Exception as e:
            logger.error(f"删除新闻向量失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"删除新闻向量失败: {str(e)}",
                "data": None
            })
    
    @app.route("/api/news/quantitative_analysis", methods=["POST"])
    @login_required
    def quantitative_analysis():
        """
        量化分析API - 基于新闻数据进行量化分析
        
        请求参数:
        {
            "analysis_type": "sentiment_trend",  # 分析类型: sentiment_trend, market_impact, topic_clustering
            "time_range": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31"
            },
            "filters": {
                "source": ["新浪财经", "东方财富"],
                "min_market_relevance": 0.5
            },
            "parameters": {
                "window_size": 7,  # 时间窗口大小（天）
                "threshold": 0.1   # 阈值参数
            }
        }
        
        返回:
        {
            "code": 0,
            "msg": "分析完成",
            "data": {
                "analysis_type": "sentiment_trend",
                "results": {...},
                "metadata": {...}
            }
        }
        """
        try:
            # 获取请求参数
            if not request.is_json:
                return jsonify({
                    "code": 400,
                    "msg": "请求必须是JSON格式",
                    "data": None
                })
            
            data = request.get_json()
            analysis_type = data.get('analysis_type')
            if not analysis_type:
                return jsonify({
                    "code": 400,
                    "msg": "缺少分析类型参数 'analysis_type'",
                    "data": None
                })
            
            time_range = data.get('time_range', {})
            filters = data.get('filters', {})
            parameters = data.get('parameters', {})
            
            # 获取向量数据库实例
            vector_db = get_vector_db(db_path="./chroma_db")
            
            # 根据分析类型执行不同的分析
            if analysis_type == "sentiment_trend":
                results = _analyze_sentiment_trend(vector_db, time_range, filters, parameters)
            elif analysis_type == "market_impact":
                results = _analyze_market_impact(vector_db, time_range, filters, parameters)
            elif analysis_type == "topic_clustering":
                results = _analyze_topic_clustering(vector_db, time_range, filters, parameters)
            else:
                return jsonify({
                    "code": 400,
                    "msg": f"不支持的分析类型: {analysis_type}",
                    "data": None
                })
            
            return jsonify({
                "code": 0,
                "msg": "分析完成",
                "data": {
                    "analysis_type": analysis_type,
                    "results": results,
                    "metadata": {
                        "time_range": time_range,
                        "filters": filters,
                        "parameters": parameters,
                        "analyzed_at": datetime.datetime.now().isoformat()
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"量化分析失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"量化分析失败: {str(e)}",
                "data": None
            })

    @app.route("/api/news/daily_summary", methods=["POST"])
    @login_required
    def generate_daily_news_summary():
        """
        生成每日新闻总结API
        
        请求体:
        {
            "days": 1  // 分析天数，默认1天
        }
        
        返回:
        {
            "code": 0,
            "msg": "生成成功",
            "data": {
                "summary": "每日新闻总结内容",
                "summary_id": "保存的总结ID",
                "analyzed_targets": ["分析的标的列表"],
                "news_count": 50
            }
        }
        """
        try:
            result = _generate_daily_summary_payload(request.get_json() or {})
            return jsonify({
                "code": 0,
                "msg": "生成成功",
                "data": result
            })
            
        except Exception as e:
            logger.error(f"生成每日新闻总结失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"生成失败: {str(e)}",
                "data": None
            })

    @app.route("/api/news/daily_summary/async", methods=["POST"])
    @login_required
    def create_daily_summary_task():
        try:
            payload = request.get_json() or {}
            task_id = uuid.uuid4().hex
            _set_market_summary_task(
                task_id,
                task_id=task_id,
                task_type="daily_news_summary",
                state="queued",
                stage="queued",
                message="任务已提交，等待执行",
                progress=0,
                created_at=datetime.now().isoformat(),
                result=None,
                error="",
                params={"days": payload.get("days", 1)},
            )

            worker = threading.Thread(
                target=_run_daily_summary_task,
                args=(task_id, payload),
                daemon=True,
            )
            worker.start()

            return jsonify({
                "code": 0,
                "msg": "每日新闻总结任务已提交",
                "data": {
                    "task_id": task_id,
                    "state": "queued",
                },
            })
        except Exception as e:
            logger.error(f"创建每日新闻总结任务失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"创建任务失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/daily_summary/task/<task_id>", methods=["GET"])
    @login_required
    def get_daily_summary_task(task_id: str):
        task = _get_market_summary_task(task_id)
        if not task:
            return jsonify({
                "code": 404,
                "msg": "任务不存在或已过期",
                "data": None,
            })

        return jsonify({
            "code": 0,
            "msg": "查询成功",
            "data": task,
        })

    @app.route("/api/news/historical_analysis", methods=["POST"])
    @login_required
    def generate_historical_analysis():
        try:
            result = _generate_historical_analysis_payload(request.get_json() or {})
            return jsonify({
                "code": 0,
                "msg": "生成成功",
                "data": result,
            })
        except Exception as e:
            logger.error(f"生成历史分析失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"生成失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/historical_analysis/async", methods=["POST"])
    @login_required
    def create_historical_analysis_task():
        try:
            payload = request.get_json() or {}
            task_id = uuid.uuid4().hex
            _set_market_summary_task(
                task_id,
                task_id=task_id,
                task_type="historical_analysis",
                state="queued",
                stage="queued",
                message="任务已提交，等待执行",
                progress=0,
                created_at=datetime.now().isoformat(),
                result=None,
                error="",
                params={
                    "current_market": payload.get("current_market", ""),
                    "current_code": payload.get("current_code", ""),
                    "lookback_hours": payload.get("lookback_hours", 24),
                    "event_frequency": payload.get("event_frequency", "5m"),
                    "event_window_minutes": payload.get("event_window_minutes", 5),
                    "min_return_pct": payload.get("min_return_pct", 0.35),
                    "min_range_pct": payload.get("min_range_pct", 0.55),
                    "atr_multiple": payload.get("atr_multiple", 1.2),
                    "max_events": payload.get("max_events", 8),
                },
            )

            worker = threading.Thread(
                target=_run_historical_analysis_task,
                args=(task_id, payload),
                daemon=True,
            )
            worker.start()

            return jsonify({
                "code": 0,
                "msg": "历史分析任务已提交",
                "data": {
                    "task_id": task_id,
                    "state": "queued",
                },
            })
        except Exception as e:
            logger.error(f"创建历史分析任务失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"创建任务失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/historical_analysis/task/<task_id>", methods=["GET"])
    @login_required
    def get_historical_analysis_task(task_id: str):
        task = _get_market_summary_task(task_id)
        if not task:
            return jsonify({
                "code": 404,
                "msg": "任务不存在或已过期",
                "data": None,
            })

        return jsonify({
            "code": 0,
            "msg": "查询成功",
            "data": task,
        })

    @app.route("/api/news/historical_analysis/topics", methods=["GET"])
    @login_required
    def get_historical_analysis_topics():
        try:
            current_market = str(request.args.get("current_market", "") or "").strip()
            current_code = _normalize_asset_code(request.args.get("current_code", ""))
            product_info = _get_product_info(current_code, current_market) if current_market or current_code else {}
            topics = _get_asset_event_topic_definitions(current_market, current_code)
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "topics": topics,
                    "asset_context": {
                        "market": current_market,
                        "code": current_code,
                        "asset_class": _resolve_market_data_asset_class(current_market, product_info) if (current_market or current_code) else "macro",
                        "name": str(product_info.get("name_cn") or product_info.get("name_en") or current_code or ""),
                    },
                },
            })
        except Exception as e:
            logger.error(f"查询历史分析主题失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/historical_analysis/topics", methods=["POST"])
    @login_required
    def save_historical_analysis_topics():
        try:
            payload = request.get_json() or {}
            topics = payload.get("topics", [])
            saved_topics = _save_event_topic_definitions(topics)
            return jsonify({
                "code": 0,
                "msg": "主题设置已保存",
                "data": {
                    "topics": saved_topics,
                },
            })
        except Exception as e:
            logger.error(f"保存历史分析主题失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"保存失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/theme_agents", methods=["GET"])
    @login_required
    def get_theme_agents():
        try:
            current_market = str(request.args.get("current_market", "") or "").strip()
            current_code = _normalize_asset_code(request.args.get("current_code", ""))
            theme_label = str(request.args.get("theme_label", "") or "").strip()
            product_info = _get_product_info(current_code, current_market) if current_market or current_code else {}
            agents = _get_theme_agent_definitions(current_market, current_code, theme_label)
            selected_agents = _select_theme_agents(
                current_market=current_market,
                current_code=current_code,
                theme_definition=resolve_theme_definition(theme_label, _get_asset_event_topic_definitions(current_market, current_code)),
                agent_definitions=agents,
            ) if theme_label else []
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "agents": agents,
                    "selected_agents": selected_agents,
                    "asset_context": {
                        "market": current_market,
                        "code": current_code,
                        "asset_class": _resolve_market_data_asset_class(current_market, product_info) if (current_market or current_code) else "macro",
                        "name": str(product_info.get("name_cn") or product_info.get("name_en") or current_code or ""),
                    },
                    "theme_context": {
                        "label": theme_label,
                    },
                },
            })
        except Exception as e:
            logger.error(f"查询主题 Agent 失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/theme_agents", methods=["POST"])
    @login_required
    def save_theme_agents():
        try:
            payload = request.get_json() or {}
            current_market = str(payload.get("current_market", "") or "").strip()
            current_code = _normalize_asset_code(payload.get("current_code", ""))
            theme_label = str(payload.get("theme_label", "") or "").strip()
            saved_agents = _save_theme_agent_definitions(payload.get("agents", []) or [])
            effective_agents = _get_theme_agent_definitions(current_market, current_code, theme_label)
            selected_agents = _select_theme_agents(
                current_market=current_market,
                current_code=current_code,
                theme_definition=resolve_theme_definition(theme_label, _get_asset_event_topic_definitions(current_market, current_code)),
                agent_definitions=effective_agents,
            ) if theme_label else []
            return jsonify({
                "code": 0,
                "msg": "主题 Agent 设置已保存",
                "data": {
                    "agents": saved_agents,
                    "effective_agents": effective_agents,
                    "selected_agents": selected_agents,
                },
            })
        except Exception as e:
            logger.error(f"保存主题 Agent 失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"保存失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/realtime_focus", methods=["GET"])
    @login_required
    def get_realtime_focus():
        try:
            payload = _build_realtime_focus_payload(
                request.args.get("current_market", ""),
                request.args.get("current_code", ""),
                request.args.get("timesfm_frequency", "30m"),
                request.args.get("timesfm_context_length", 0),
            )
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": payload,
            })
        except Exception as e:
            logger.error(f"查询实时关注失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/market_data/view", methods=["GET"])
    @login_required
    def get_market_data_view():
        try:
            limit = int(request.args.get("limit", 8) or 8)
            payload = _build_market_data_view_payload(
                request.args.get("current_market", ""),
                request.args.get("current_code", ""),
                max(1, min(limit, 30)),
            )
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": payload,
            })
        except Exception as e:
            logger.error(f"查询市场数据失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/market_data/sync", methods=["POST"])
    @login_required
    def sync_market_data_view():
        try:
            payload = request.get_json() or {}
            result = _sync_market_data_for_asset(
                str(payload.get("current_market") or ""),
                str(payload.get("current_code") or ""),
            )
            return jsonify({
                "code": 0,
                "msg": "同步成功",
                "data": result,
            })
        except Exception as e:
            logger.error(f"同步市场数据失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"同步失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/theme_simulation", methods=["POST"])
    @login_required
    def get_theme_simulation():
        try:
            result = _generate_theme_simulation_payload(request.get_json() or {})
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": result,
            })
        except Exception as e:
            logger.error(f"查询主题推演失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/theme_evidence/upload", methods=["POST"])
    @login_required
    def upload_theme_evidence():
        try:
            upload_files = request.files.getlist("files")
            if not upload_files and request.files.get("file"):
                upload_files = [request.files["file"]]
            if not upload_files:
                raise ValueError("请先上传至少一个文件")
            evidence_items: List[Dict[str, Any]] = []
            for upload_file in upload_files[:6]:
                file_name = str(getattr(upload_file, "filename", "") or "").strip()
                if not file_name:
                    continue
                evidence_items.append(_extract_uploaded_file_text(file_name, upload_file.read()))
            if not evidence_items:
                raise ValueError("未能从上传文件中提取到有效证据")
            return jsonify({
                "code": 0,
                "msg": "上传成功",
                "data": {"evidence_items": evidence_items},
            })
        except Exception as e:
            logger.error(f"上传主题证据失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"上传失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/service/health", methods=["GET"])
    def service_health():
        context = _service_context()
        auth_error = _require_service_auth()
        if auth_error:
            return auth_error
        return _service_json_success(
            {
                "service": "chanlun-pro",
                "status": "ok",
            },
            meta={"request_source": context["request_source"]},
            trace_id=context["trace_id"],
        )

    @app.route("/api/service/theme_simulation", methods=["POST"])
    def service_theme_simulation():
        payload = request.get_json(silent=True) or {}
        auth_error = _require_service_auth(payload)
        if auth_error:
            return auth_error
        service_payload = _build_service_payload(payload)
        context = _service_context(service_payload)
        try:
            result = _generate_theme_simulation_payload(service_payload)
            return _service_json_success(
                {
                    "analysis_type": "theme_simulation",
                    "summary": result.get("summary", ""),
                    "report": result.get("report", {}),
                    "research_agent": result.get("research_agent", {}),
                    "comprehensive_reasoning": result.get("comprehensive_reasoning", {}),
                    "citations": result.get("citations", []),
                    "raw": result,
                },
                meta={"request_source": context["request_source"]},
                session_id=context["session_id"],
                trace_id=context["trace_id"],
            )
        except ValueError as e:
            return _service_json_error("INVALID_ARGUMENT", str(e), 400, trace_id=context["trace_id"])
        except Exception as e:
            logger.error(f"Service theme_simulation failed: {e}", exc_info=True)
            return _service_json_error("INTERNAL_ERROR", str(e), 500, trace_id=context["trace_id"])

    @app.route("/api/service/market_data/view", methods=["POST"])
    def service_market_data_view():
        payload = request.get_json(silent=True) or {}
        auth_error = _require_service_auth(payload)
        if auth_error:
            return auth_error
        service_payload = _build_service_payload(payload)
        context = _service_context(service_payload)
        try:
            current_market = str(service_payload.get("current_market") or "").strip()
            current_code = str(service_payload.get("current_code") or "").strip()
            limit = max(1, min(int(service_payload.get("limit", 8) or 8), 30))
            result = _build_market_data_view_payload(current_market, current_code, limit)
            return _service_json_success(
                result,
                meta={"request_source": context["request_source"]},
                session_id=context["session_id"],
                trace_id=context["trace_id"],
            )
        except ValueError as e:
            return _service_json_error("INVALID_ARGUMENT", str(e), 400, trace_id=context["trace_id"])
        except Exception as e:
            logger.error(f"Service market_data/view failed: {e}", exc_info=True)
            return _service_json_error("INTERNAL_ERROR", str(e), 500, trace_id=context["trace_id"])

    @app.route("/api/service/market_data/sync", methods=["POST"])
    def service_market_data_sync():
        payload = request.get_json(silent=True) or {}
        auth_error = _require_service_auth(payload)
        if auth_error:
            return auth_error
        service_payload = _build_service_payload(payload)
        context = _service_context(service_payload)
        try:
            current_market = str(service_payload.get("current_market") or "").strip()
            current_code = str(service_payload.get("current_code") or "").strip()
            result = _sync_market_data_for_asset(current_market, current_code)
            return _service_json_success(
                result,
                meta={"request_source": context["request_source"]},
                session_id=context["session_id"],
                trace_id=context["trace_id"],
            )
        except ValueError as e:
            return _service_json_error("INVALID_ARGUMENT", str(e), 400, trace_id=context["trace_id"])
        except Exception as e:
            logger.error(f"Service market_data/sync failed: {e}", exc_info=True)
            return _service_json_error("INTERNAL_ERROR", str(e), 500, trace_id=context["trace_id"])

    @app.route("/api/service/historical_analysis", methods=["POST"])
    def service_historical_analysis():
        payload = request.get_json(silent=True) or {}
        auth_error = _require_service_auth(payload)
        if auth_error:
            return auth_error
        service_payload = _build_service_payload(payload)
        context = _service_context(service_payload)
        try:
            result = _generate_historical_analysis_payload(service_payload)
            return _service_json_success(
                {
                    "analysis_type": "historical_analysis",
                    "summary": result.get("summary", ""),
                    "events": result.get("events", []),
                    "timesfm_forecast": result.get("timesfm_forecast", {}),
                    "raw": result,
                },
                meta={"request_source": context["request_source"]},
                session_id=context["session_id"],
                trace_id=context["trace_id"],
            )
        except ValueError as e:
            return _service_json_error("INVALID_ARGUMENT", str(e), 400, trace_id=context["trace_id"])
        except Exception as e:
            logger.error(f"Service historical_analysis failed: {e}", exc_info=True)
            return _service_json_error("INTERNAL_ERROR", str(e), 500, trace_id=context["trace_id"])

    @app.route("/api/news/timesfm/forecast", methods=["POST"])
    @login_required
    def get_timesfm_forecast():
        try:
            result = _generate_timesfm_forecast_payload(request.get_json() or {})
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": result,
            })
        except Exception as e:
            logger.error(f"查询 TimesFM 预测失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/timesfm/event_forecast", methods=["POST"])
    @login_required
    def get_timesfm_event_forecast():
        try:
            result = _generate_timesfm_event_forecast_payload(request.get_json() or {})
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": result,
            })
        except Exception as e:
            logger.error(f"查询 TimesFM 事件预测失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })

    @app.route("/api/news/timesfm/review", methods=["GET"])
    @login_required
    def get_timesfm_review():
        try:
            result = _generate_timesfm_review_payload(
                {
                    "current_market": request.args.get("current_market", ""),
                    "current_code": request.args.get("current_code", ""),
                    "review_days": request.args.get("review_days", 14),
                    "frequency": request.args.get("frequency", "30m"),
                    "context_length": request.args.get("context_length", 0),
                    "max_items": request.args.get("max_items", 8),
                }
            )
            return jsonify({
                "code": 0,
                "msg": "查询成功",
                "data": result,
            })
        except Exception as e:
            logger.error(f"查询 TimesFM 历史回顾失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"查询失败: {str(e)}",
                "data": None,
            })


def _analyze_sentiment_trend(vector_db, time_range: Dict, filters: Dict, parameters: Dict) -> Dict:
    """
    情感趋势分析
    
    Args:
        vector_db: 向量数据库实例
        time_range: 时间范围
        filters: 过滤条件
        parameters: 分析参数
    
    Returns:
        Dict: 分析结果
    """
    try:
        # 解析时间范围
        start_date = None
        end_date = None
        
        if 'start_date' in time_range:
            start_date = datetime.datetime.strptime(time_range['start_date'], '%Y-%m-%d')
        if 'end_date' in time_range:
            end_date = datetime.datetime.strptime(time_range['end_date'], '%Y-%m-%d')
            end_date = end_date.replace(hour=23, minute=59, second=59)
        
        # 获取情感分析数据
        sentiment_stats = vector_db.get_sentiment_analysis(start_date, end_date)
        
        # 这里可以添加更复杂的趋势分析逻辑
        # 例如：按时间窗口聚合、计算移动平均等
        
        return {
            "sentiment_distribution": {
                "positive": sentiment_stats.get('positive', 0),
                "negative": sentiment_stats.get('negative', 0),
                "neutral": sentiment_stats.get('neutral', 0)
            },
            "average_sentiment": sentiment_stats.get('avg_sentiment', 0.0),
            "total_analyzed": sentiment_stats.get('total', 0),
            "trend_direction": "positive" if sentiment_stats.get('avg_sentiment', 0) > 0 else "negative",
            "confidence_score": min(1.0, sentiment_stats.get('total', 0) / 100.0)  # 基于样本数量的置信度
        }
        
    except Exception as e:
        logger.error(f"情感趋势分析失败: {str(e)}")
        return {"error": str(e)}



def _analyze_important_targets(news_list):
    """
    分析新闻中提到的重要标的（优化支持英文新闻）
    
    Args:
        news_list: 新闻列表
    
    Returns:
        List: 重要标的列表
    """
    try:
        import re
        from collections import Counter
        
        # 股票代码正则表达式（优化支持更多格式）
        stock_patterns = [
            r'\b\d{6}\b',  # 6位数字（A股代码）
            r'\b[A-Z]{1,5}\b',  # 1-5位大写字母（美股代码）
            r'\b\d{5}\.[A-Z]{2}\b',  # 港股代码格式
            r'\b[A-Z]{2,4}\d{4,6}\b',  # 期货代码格式
            r'\$[A-Z]{1,5}\b',  # 美股代码带$符号
        ]
        
        # 外汇对正则表达式
        forex_patterns = [
            r'\b[A-Z]{3}/[A-Z]{3}\b',  # EUR/USD格式
            r'\b[A-Z]{6}\b',  # EURUSD格式
            r'\b[A-Z]{3}-[A-Z]{3}\b',  # EUR-USD格式
        ]
        
        # 扩展的标的名称关键词（中英文）
        target_keywords = {
            # 中国公司
            '茅台': ['moutai', 'kweichow moutai'],
            '腾讯': ['tencent', 'tencent holdings'],
            '阿里': ['alibaba', 'ali', 'baba'],
            '比亚迪': ['byd', 'build your dreams'],
            '宁德时代': ['catl', 'contemporary amperex'],
            '美团': ['meituan'],
            '小米': ['xiaomi', 'mi'],
            '字节跳动': ['bytedance', 'tiktok'],
            '百度': ['baidu'],
            '京东': ['jd.com', 'jingdong'],
            '网易': ['netease'],
            '拼多多': ['pdd', 'pinduoduo'],
            
            # 美国公司
            '苹果': ['apple', 'aapl'],
            '特斯拉': ['tesla', 'tsla'],
            '微软': ['microsoft', 'msft'],
            '谷歌': ['google', 'alphabet', 'googl', 'goog'],
            '亚马逊': ['amazon', 'amzn'],
            '英伟达': ['nvidia', 'nvda'],
            '脸书': ['facebook', 'meta', 'fb'],
            '奈飞': ['netflix', 'nflx'],
            '推特': ['twitter', 'x corp'],
            '优步': ['uber'],
            '空客': ['airbus'],
            '波音': ['boeing'],
            '摩根大通': ['jpmorgan', 'jp morgan'],
            '高盛': ['goldman sachs'],
            '摩根士丹利': ['morgan stanley'],
            
            # 商品和货币
            '黄金': ['gold', 'xau'],
            '白银': ['silver', 'xag'],
            '原油': ['oil', 'crude', 'wti', 'brent'],
            '天然气': ['natural gas', 'ng'],
            '铜': ['copper'],
            '美元': ['usd', 'dollar', 'dxy'],
            '人民币': ['cny', 'yuan', 'rmb'],
            '欧元': ['eur', 'euro'],
            '日元': ['jpy', 'yen'],
            '英镑': ['gbp', 'pound'],
            '澳元': ['aud'],
            '加元': ['cad'],
            '瑞郎': ['chf'],
            '比特币': ['bitcoin', 'btc'],
            '以太坊': ['ethereum', 'eth'],
            
            # 指数
            '上证指数': ['shanghai composite', 'shcomp'],
            '深证成指': ['szse component'],
            '创业板': ['chinext'],
            '科创板': ['star market'],
            '恒生指数': ['hang seng', 'hsi'],
            '纳斯达克': ['nasdaq', 'ndx', 'ixic'],
            '标普500': ['s&p 500', 'spx', 'spy'],
            '道琼斯': ['dow jones', 'djia', 'dji'],
            '富时100': ['ftse 100'],
            '日经225': ['nikkei', 'n225'],
            '德国dax': ['dax'],
        }
        
        # 常见金融术语
        financial_terms = [
            'fed', 'federal reserve', 'ecb', 'boe', 'boj', 'pboc',
            'gdp', 'cpi', 'ppi', 'nfp', 'unemployment',
            'interest rate', 'inflation', 'recession',
            'earnings', 'revenue', 'profit', 'loss',
            'ipo', 'merger', 'acquisition', 'dividend'
        ]
        
        target_counts = Counter()
        
        for news in news_list:
            # 获取新闻内容，转换为小写以便匹配
            content = news.get('document', '') + ' ' + news.get('metadata', {}).get('title', '')
            content_lower = content.lower()
            
            # 查找股票代码（保持原大小写）
            for pattern in stock_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    # 过滤掉常见的非股票代码
                    if match.upper() not in ['THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'HAD', 'BUT', 'HAS']:
                        target_counts[match.upper()] += 1
            
            # 查找外汇对
            for pattern in forex_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    target_counts[match.upper()] += 1
            
            # 查找标的名称关键词（支持中英文）
            for chinese_name, english_names in target_keywords.items():
                # 检查中文名称
                if chinese_name in content:
                    target_counts[chinese_name] += 1
                
                # 检查英文名称（大小写不敏感）
                for english_name in english_names:
                    if english_name.lower() in content_lower:
                        target_counts[chinese_name] += 1
                        break
            
            # 查找金融术语
            for term in financial_terms:
                if term.lower() in content_lower:
                    target_counts[term.upper()] += 1
        
        # 按出现频次排序，取前30个
        most_common_targets = target_counts.most_common(30)
        
        # 过滤掉出现次数太少的标的（至少出现2次）
        filtered_targets = [target for target, count in most_common_targets if count >= 2]
        
        logger.info(f"分析出{len(filtered_targets)}个重要标的: {filtered_targets[:10]}")
        
        return filtered_targets
        
    except Exception as e:
        logger.error(f"分析重要标的失败: {str(e)}")
        return []


def _validate_news_quality(news_list):
    """
    验证新闻数据质量，过滤掉不完整或质量差的新闻
    
    Args:
        news_list: 新闻列表
    
    Returns:
        List: 验证后的高质量新闻列表
    """
    try:
        validated_news = []
        
        for news in news_list:
            # 基本字段检查
            title = news.get('title', '').strip()
            content = news.get('content', '').strip()
            source = news.get('source', '').strip()
            published_at = news.get('published_at', '')
            
            # 质量验证规则
            quality_checks = [
                # 标题不能为空且长度合理
                len(title) >= 5 and len(title) <= 200,
                # 内容不能为空且有足够信息量
                len(content) >= 20 and len(content) <= 10000,
                # 来源不能为空
                len(source) >= 2,
                # 发布时间不能为空
                published_at and published_at != '未知时间',
                # 标题和内容不能完全相同（避免重复数据）
                title.lower() != content.lower(),
                # 内容不能只是标题的重复
                not (len(content) < 100 and title.lower() in content.lower() and len(content) - len(title) < 20),
                # 避免明显的垃圾内容
                not any(spam_word in title.lower() + content.lower() for spam_word in [
                    '广告', '推广', '点击', '链接', '下载', '注册', '免费', '赚钱',
                    'advertisement', 'promotion', 'click here', 'download', 'register', 'free money'
                ]),
                # 内容不能包含过多特殊字符（至少70%应该是正常字符）
                sum(1 for c in content if c.isalnum() or c.isspace() or c in '，。！？；：""''()[]{}') >= len(content) * 0.7
            ]
            
            # 所有质量检查都通过才保留新闻
            if all(quality_checks):
                # 额外的内容质量检查
                content_words = len(content.split())
                title_words = len(title.split())
                
                # 内容应该比标题有更多信息
                if content_words > title_words * 1.5:
                    validated_news.append(news)
        
        logger.info(f"新闻质量验证完成：原始{len(news_list)}条 -> 验证后{len(validated_news)}条")
        
        return validated_news
        
    except Exception as e:
        logger.error(f"新闻质量验证失败: {str(e)}")
        # 如果验证失败，返回原始新闻列表
        return news_list


def _filter_financial_news(news_list):
    """
    筛选金融相关新闻，过滤掉非金融市场的新闻
    
    Args:
        news_list: 新闻列表
    
    Returns:
        List: 筛选后的金融新闻列表
    """
    try:
        import re
        
        # 金融关键词白名单（中英文）- 扩展版
        financial_keywords = {
            # 市场相关
            '股票', '股市', '股价', '股指', '上市', '退市', '停牌', '复牌', '涨停', '跌停', '开盘', '收盘', '盘中', '盘后',
            '沪指', '深指', '创业板', '科创板', '北交所', '新三板', '主板', '中小板',
            'stock', 'stocks', 'equity', 'equities', 'share', 'shares', 'market', 'trading', 'nasdaq', 'nyse', 'dow',
            'sp500', 's&p', 'russell', 'ftse', 'nikkei', 'hang seng', 'shanghai composite',
            
            # 外汇相关
            '外汇', '汇率', '美元', '欧元', '日元', '英镑', '人民币', '澳元', '加元', '瑞郎', '新西兰元', '港币',
            'forex', 'fx', 'currency', 'exchange rate', 'usd', 'eur', 'jpy', 'gbp', 'cny', 'aud', 'cad', 'chf', 'nzd', 'hkd',
            'dollar', 'euro', 'yen', 'pound', 'yuan', 'rmb', 'dxy', 'dollar index',
            
            # 债券相关
            '债券', '国债', '企业债', '公司债', '可转债', '收益率', '利率', '央行', '货币政策', '降息', '加息',
            '国开债', '地方债', '城投债', '信用债', '利差', '久期',
            'bond', 'bonds', 'treasury', 'corporate bond', 'yield', 'interest rate', 'central bank',
            'monetary policy', 'fed', 'federal reserve', 'ecb', 'boe', 'boj', 'pboc', 'rate cut', 'rate hike',
            
            # 金融机构
            '银行', '保险', '证券', '基金', '信托', '期货', '投资', '融资', '贷款', '券商', '私募', '公募',
            '资管', '理财', '财富管理', '投行', '风投', 'vc', 'pe', '对冲基金',
            'bank', 'banking', 'insurance', 'securities', 'fund', 'trust', 'futures', 'investment',
            'financing', 'loan', 'credit', 'broker', 'asset management', 'wealth management', 'hedge fund',
            
            # 经济指标
            'gdp', 'cpi', 'ppi', 'pmi', 'nfp', 'unemployment', 'inflation', 'deflation', 'recession',
            '通胀', '通缩', '失业率', '经济增长', '经济数据', '财报', '业绩', '营收', '利润', '净利润', '毛利率',
            '同比', '环比', '季报', '年报', '中报', 'roe', 'roa', '资产负债率',
            'earnings', 'revenue', 'profit', 'financial results', 'quarterly', 'annual report',
            
            # 金融产品
            '期权', '衍生品', '商品', '黄金', '白银', '原油', '天然气', '铜', '大宗商品', '农产品',
            '铁矿石', '煤炭', '钢铁', '有色金属', '贵金属', '能源', '化工',
            'options', 'derivatives', 'commodities', 'gold', 'silver', 'oil', 'crude', 'natural gas',
            'copper', 'metals', 'iron ore', 'coal', 'steel', 'energy', 'chemicals',
            
            # 加密货币
            '比特币', '以太坊', '加密货币', '数字货币', '区块链', '虚拟货币', 'defi', 'nft',
            'bitcoin', 'ethereum', 'cryptocurrency', 'crypto', 'blockchain', 'btc', 'eth', 'usdt', 'usdc',
            'binance', 'coinbase', 'digital asset',
            
            # 金融术语
            'ipo', 'merger', 'acquisition', 'dividend', 'buyback', 'split', 'volatility', 'liquidity',
            '并购', '收购', '分红', '回购', '拆股', '波动率', '市值', '估值', '流动性', '杠杆',
            '做多', '做空', '套利', '对冲', '风险', '收益', '资本', '资金',
            'market cap', 'valuation', 'pe ratio', 'pb ratio', 'leverage', 'arbitrage', 'hedge',
            
            # 行业和板块
            '科技股', '金融股', '地产股', '消费股', '医药股', '新能源', '芯片', '半导体',
            '5g', '人工智能', 'ai', '新基建', '碳中和', '双碳', 'esg',
            'tech stock', 'fintech', 'biotech', 'semiconductor', 'renewable energy', 'electric vehicle',
            
            # 监管和政策
            '证监会', '银保监会', '央行', '发改委', '财政部', '国资委', 'sec', 'cftc', 'finra',
            '监管', '政策', '法规', '合规', '审批', '备案',
            'regulation', 'policy', 'compliance', 'approval'
        }
        
        # 非金融关键词黑名单（缩减版，只排除明显无关的内容）
        non_financial_keywords = {
            # 娱乐体育（明显无关）
            '娱乐圈', '明星八卦', '电视剧', '电影票房', '音乐排行', '综艺节目',
            'celebrity gossip', 'tv drama', 'movie box office', 'music chart', 'variety show',
            
            # 纯生活消费（非商业投资）
            '美食推荐', '旅游攻略', '时尚搭配', '健身减肥', '育儿教育',
            'food recommendation', 'travel guide', 'fashion style', 'fitness', 'parenting',
            
            # 纯社会新闻（非经济影响）
            '刑事案件', '交通事故', '自然灾害', '天气预报',
            'criminal case', 'traffic accident', 'natural disaster', 'weather forecast'
        }
        
        filtered_news = []
        
        for news in news_list:
            # 获取新闻内容
            title = news.get('title', '').lower()
            content = news.get('content', '').lower()
            body = news.get('body', '').lower()
            category = news.get('category', '').lower()
            
            # 合并所有文本内容
            full_text = f"{title} {content} {body} {category}"
            
            # 检查是否包含金融关键词
            has_financial_keywords = any(keyword.lower() in full_text for keyword in financial_keywords)
            
            # 检查是否包含非金融关键词（排除项）
            has_non_financial_keywords = any(keyword.lower() in full_text for keyword in non_financial_keywords)
            
            # 特殊规则：如果标题或内容明确包含股票代码、外汇对等，直接保留
            has_financial_codes = bool(
                re.search(r'\b\d{6}\b', full_text) or  # A股代码
                re.search(r'\b[A-Z]{3}/[A-Z]{3}\b', full_text) or  # 外汇对
                re.search(r'\$[A-Z]{1,5}\b', full_text) or  # 美股代码
                re.search(r'\b(fed|ecb|boe|boj|pboc)\b', full_text, re.IGNORECASE)  # 央行
            )
            
            # 优化后的筛选逻辑（更宽松的条件）：
            # 1. 包含金融代码的直接保留
            # 2. 包含金融关键词的保留（放宽条件，不再严格要求无非金融关键词）
            # 3. 对于同时包含金融和非金融关键词的新闻，降低筛选门槛
            if has_financial_codes:
                filtered_news.append(news)
            elif has_financial_keywords:
                if not has_non_financial_keywords:
                    # 纯金融新闻，直接保留
                    filtered_news.append(news)
                else:
                    # 计算金融关键词密度
                    financial_count = sum(1 for keyword in financial_keywords if keyword.lower() in full_text)
                    non_financial_count = sum(1 for keyword in non_financial_keywords if keyword.lower() in full_text)
                    
                    # 降低筛选门槛：金融关键词数量 >= 非金融关键词数量即可保留
                    # 或者金融关键词数量 >= 2（表示有一定的金融相关性）
                    if financial_count >= non_financial_count or financial_count >= 2:
                        filtered_news.append(news)
        
        logger.info(f"新闻筛选完成：原始{len(news_list)}条 -> 筛选后{len(filtered_news)}条")
        
        return filtered_news
        
    except Exception as e:
        logger.error(f"筛选金融新闻失败: {str(e)}")
        # 如果筛选失败，返回原始新闻列表
        return news_list


def _generate_daily_news_summary(news_list, analyzed_targets, days):
    """
    生成每日新闻总结（包含价格变动信息）
    
    Args:
        news_list: 新闻列表
        analyzed_targets: 分析出的重要标的
        days: 分析天数
    
    Returns:
        str: 生成的总结内容
    """
    try:
        from chanlun.tools.ai_analyse import AIAnalyse
        from chanlun.zixuan import ZiXuan
        from chanlun.exchange import get_exchange
        from chanlun.base import Market
        import datetime
        
        # 首先进行新闻数据质量验证
        validated_news = _validate_news_quality(news_list)
        logger.info(f"新闻质量验证：原始{len(news_list)}条 -> 验证后{len(validated_news)}条")
        
        # 然后筛选金融相关新闻
        filtered_news = _filter_financial_news(validated_news)
        
        # 如果筛选后没有新闻，返回提示信息
        if not filtered_news:
            return "暂无相关金融市场新闻。"
        
        # 获取用户关注产品的价格信息
        price_info = ""
        mentioned_products = set()  # 存储新闻中提及的自选产品
        
        try:
            # 支持的市场类型
            supported_markets = ['a', 'hk', 'us', 'fx', 'futures', 'currency']
            all_price_data = []
            
            for market in supported_markets:
                try:
                    zx = ZiXuan(market)
                    # 获取所有自选组的股票
                    all_zx_stocks = zx.query_all_zs_stocks()
                    
                    # 收集所有股票代码和名称
                    market_codes = []
                    stock_info = {}  # 代码到名称的映射
                    
                    for zx_group in all_zx_stocks:
                        for stock in zx_group['stocks']:
                            code = stock['code']
                            name = stock['name']
                            market_codes.append(code)
                            stock_info[code] = name
                            stock_info[name] = code  # 双向映射
                    
                    if market_codes:
                        # 获取价格数据
                        ex = get_exchange(Market(market))
                        ticks = ex.ticks(market_codes)
                        
                        market_names = {
                            'a': 'A股',
                            'hk': '港股', 
                            'us': '美股',
                            'fx': '外汇',
                            'futures': '期货',
                            'currency': '数字货币'
                        }
                        market_name = market_names.get(market, market)
                        
                        for code, tick in ticks.items():
                            stock_name = stock_info.get(code, code)
                            
                            price_data = {
                                'market': market_name,
                                'code': code,
                                'name': stock_name,
                                'price': getattr(tick, 'last', 0),
                                'rate': getattr(tick, 'rate', 0)
                            }
                            all_price_data.append(price_data)
                            
                            # 检查新闻中是否提及该产品
                            for news in filtered_news:
                                news_text = (news.get('title', '') + ' ' + news.get('content', '')).lower()
                                if (code.lower() in news_text or 
                                    stock_name.lower() in news_text or
                                    (len(stock_name) > 2 and stock_name[:4].lower() in news_text)):
                                    mentioned_products.add((market_name, code, stock_name, price_data['price'], price_data['rate']))
                            
                except Exception as e:
                    logger.warning(f"获取{market}市场价格数据失败: {str(e)}")
                    continue
            
            # 构建价格信息文本
            if all_price_data:
                price_info = "\n\n## 关注产品当前价格\n"
                current_market_data = {}
                for data in all_price_data:
                    market = data['market']
                    if market not in current_market_data:
                        current_market_data[market] = []
                    current_market_data[market].append(data)
                
                for market, stocks in current_market_data.items():
                    price_info += f"\n**{market}市场:**\n"
                    for stock in stocks[:10]:  # 限制每个市场最多显示10只股票
                        rate_str = f"{stock['rate']:+.2f}%" if stock['rate'] != 0 else "0.00%"
                        price_info += f"- {stock['name']}({stock['code']}): {stock['price']:.2f} ({rate_str})\n"
                        
        except Exception as e:
            logger.error(f"获取关注产品价格信息失败: {str(e)}")
            price_info = "\n\n## 关注产品价格\n暂时无法获取价格信息，请稍后重试。\n"
        
        # 构建提示词 - 包含价格分析指导
        current_date = datetime.datetime.now().strftime('%Y年%m月%d日')
        
        # 简单格式化筛选后的新闻列表
        news_content = ""
        for i, news in enumerate(filtered_news[:50], 1):  # 限制最多50条新闻
            title = news.get('title', '无标题')
            source = news.get('source', '未知来源')
            published_at = news.get('published_at', '未知时间')
            content = news.get('content', '')[:500]  # 限制内容长度
            
            news_content += f"""
{i}. 【{title}】
   来源：{source} | 时间：{published_at}
   内容：{content}{'...' if len(news.get('content', '')) > 500 else ''}

"""
        
        # 构建新闻中提及的自选产品信息
        mentioned_products_info = ""
        if mentioned_products:
            mentioned_products_info = "\n\n## 新闻中提及的关注产品\n"
            for market_name, code, name, price, rate in mentioned_products:
                rate_str = f"{rate:+.2f}%" if rate != 0 else "0.00%"
                mentioned_products_info += f"- {name}({code}) [{market_name}]: {price:.2f} ({rate_str})\n"
        
        prompt = f"""
请基于以下{days}天的金融市场新闻内容，生成一份给职业交易员看的简洁、直接、有效的新闻交易简报。

## 基本信息
- 时间范围：过去{days}天
- 原始新闻总数：{len(news_list)}条
- 筛选后金融新闻：{len(filtered_news)}条
- 报告时间：{current_date}

## 新闻内容
{news_content}

{mentioned_products_info}

## 输出要求
请按以下格式生成简洁交易简报：

# {days}天新闻交易简报

## 今日主线
[只写 2-3 条最重要的市场主线]

## 必看新闻
[只保留 3 条最重要新闻；每条必须说明：
- 影响资产
- 偏利多 / 偏利空 / 中性
- 为什么会影响价格
- 现在是已交易、未交易，还是需等待确认]

## 重点资产清单
[只列 3-5 个最值得继续跟踪的资产，并写明为什么]

## 交易员结论
[明确写出：
- 哪些只适合观察，不适合直接交易
- 哪些需要切到单资产历史分析再确认
- 今天最该等待的确认信号]

## 分析要求：
1. 不要写成长篇宏观研报，不要空话
2. 先给结论，再给依据
3. 只保留对交易有用的信息
4. 如果没有直接可交易机会，要明确写“今天先观察，不直接交易”
5. 输出中文 Markdown，控制在简洁可读范围内
"""
        
        # 创建AI客户端并调用生成总结
        ai_client = AIAnalyse("a")  # 默认使用A股市场
        summary = _call_ai_and_get_content(ai_client, prompt)
        
        if not summary or "AI分析失败" in summary or "AI分析异常" in summary:
            return "AI生成总结失败，请稍后重试"
        
        # 将价格信息添加到总结末尾
        final_summary = summary + price_info
        
        logger.info(f"每日新闻总结生成成功，长度: {len(final_summary)}")
        return final_summary
        
    except Exception as e:
        logger.error(f"生成每日新闻总结失败: {str(e)}")
        return f"生成每日新闻总结时发生错误: {str(e)}"


# 移除_categorize_news_by_type函数 - 不再需要复杂的新闻分类


# 移除_analyze_market_sentiment函数 - 不再需要复杂的情感分析


# 移除_extract_key_events函数 - 不再需要复杂的关键事件提取


# 移除_format_news_categories函数 - 不再需要


# 移除_format_key_events函数 - 不再需要


# 移除_format_important_news函数 - 已有简化版本


def _format_important_news_simple(news_list):
    """
    格式化重要新闻详情（简化版）
    
    Args:
        news_list: 新闻列表
    
    Returns:
        str: 格式化的新闻详情文本
    """
    try:
        if not news_list:
            return "暂无新闻数据"
        
        # 按重要性分数排序
        important_news = sorted(news_list, key=lambda x: x.get('importance_score', 0), reverse=True)
        
        formatted_text = ""
        for i, news in enumerate(important_news, 1):
            formatted_text += f"""
{i}. {news.get('title', '无标题')}
   来源: {news.get('source', '未知')} | 时间: {news.get('published_at', '未知')}
   摘要: {news.get('content', '')[:150]}{'...' if len(news.get('content', '')) > 150 else ''}

"""
        
        return formatted_text
        
    except Exception as e:
        logger.error(f"格式化重要新闻失败: {str(e)}")
        return "新闻详情格式化失败"


def _generate_technical_indicators_analysis(code: str, market: str) -> str:
    """
    生成全面的技术指标分析，包括MACD、RSI、布林带、KDJ、威廉指标、移动平均线等
    
    Args:
        code: 股票代码
        market: 市场代码
        
    Returns:
        str: 技术指标分析文本
    """
    try:
        import sys
        import os
        import numpy as np
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.exchange import get_exchange
        from chanlun.base import Market
        from chanlun import cl
        from chanlun.backtesting.base import Strategy
        
        # 市场映射
        market_enum_map = {
            'a': Market.A,
            'hk': Market.HK,
            'us': Market.US,
            'fx': Market.FX,
            'futures': Market.FUTURES,
            'currency': Market.CURRENCY
        }
        
        # if market not in market_enum_map:
        #     return "不支持的市场类型"
        
        # # 获取交易所和K线数据
        # exchange = get_exchange(market_enum_map[market])
        # print('code_tec',code,exchange)
        market = market
        ex = get_exchange(market=Market(market))
        klines = ex.klines(code, 'd')  # 获取日线数据
        print('klines',len(klines))
        if klines is None or len(klines) < 50:
            return "K线数据不足，无法进行技术分析"
        
        # 处理缠论数据
        cd = cl.CL(code, 'd', {}).process_klines(klines)
        
        if len(cd.get_klines()) < 50:
            return "处理后的K线数据不足，无法进行技术分析"
        
        analysis_text = ""
        
        # 计算MACD指标
        try:
            macd_data = Strategy.idx_macd(cd, fast=12, slow=26, signal=9)
            if macd_data and 'dif' in macd_data and 'dea' in macd_data and 'hist' in macd_data:
                dif = macd_data['dif']
                dea = macd_data['dea']
                hist = macd_data['hist']
                
                # 获取最新的MACD值（过滤NaN值）
                valid_indices = ~(np.isnan(dif) | np.isnan(dea) | np.isnan(hist))
                if np.any(valid_indices):
                    latest_dif = dif[valid_indices][-1]
                    latest_dea = dea[valid_indices][-1]
                    latest_hist = hist[valid_indices][-1]
                    
                    # MACD分析
                    analysis_text += "### MACD指标分析\n"
                    analysis_text += f"- **DIF值**: {latest_dif:.4f}\n"
                    analysis_text += f"- **DEA值**: {latest_dea:.4f}\n"
                    analysis_text += f"- **MACD柱**: {latest_hist:.4f}\n"
                    
                    # MACD信号判断
                    if latest_dif > latest_dea:
                        if latest_hist > 0:
                            macd_signal = "多头信号强烈，DIF在DEA之上且MACD柱为正值"
                        else:
                            macd_signal = "多头信号，DIF在DEA之上但MACD柱仍为负值，需观察是否转正"
                    else:
                        if latest_hist < 0:
                            macd_signal = "空头信号强烈，DIF在DEA之下且MACD柱为负值"
                        else:
                            macd_signal = "空头信号，DIF在DEA之下但MACD柱仍为正值，需观察是否转负"
                    
                    analysis_text += f"- **信号判断**: {macd_signal}\n"
                    
                    # 趋势分析
                    if len(hist[valid_indices]) >= 5:
                        recent_hist = hist[valid_indices][-5:]
                        if recent_hist[-1] > recent_hist[-2] > recent_hist[-3]:
                            trend = "MACD柱连续上升，动能增强"
                        elif recent_hist[-1] < recent_hist[-2] < recent_hist[-3]:
                            trend = "MACD柱连续下降，动能减弱"
                        else:
                            trend = "MACD柱震荡，动能方向不明确"
                        analysis_text += f"- **动能趋势**: {trend}\n\n"
                else:
                    analysis_text += "### MACD指标分析\n- MACD数据无效，无法进行分析\n\n"
            else:
                analysis_text += "### MACD指标分析\n- MACD计算失败\n\n"
        except Exception as e:
            analysis_text += f"### MACD指标分析\n- MACD计算异常: {str(e)}\n\n"
        
        # 计算RSI指标
        try:
            rsi_data = Strategy.idx_rsi(cd, period=14)
            if rsi_data is not None and len(rsi_data) > 0:
                valid_rsi = rsi_data[~np.isnan(rsi_data)]
                if len(valid_rsi) > 0:
                    latest_rsi = valid_rsi[-1]
                    
                    analysis_text += "### RSI相对强弱指标分析\n"
                    analysis_text += f"- **RSI值**: {latest_rsi:.2f}\n"
                    
                    # RSI信号判断
                    if latest_rsi >= 80:
                        rsi_signal = "严重超买，存在回调风险"
                        rsi_action = "建议减仓或观望"
                    elif latest_rsi >= 70:
                        rsi_signal = "超买区域，谨慎追高"
                        rsi_action = "建议控制仓位"
                    elif latest_rsi <= 20:
                        rsi_signal = "严重超卖，可能存在反弹机会"
                        rsi_action = "可考虑逢低布局"
                    elif latest_rsi <= 30:
                        rsi_signal = "超卖区域，关注反弹信号"
                        rsi_action = "可适度关注"
                    elif 45 <= latest_rsi <= 55:
                        rsi_signal = "中性区域，多空力量均衡"
                        rsi_action = "等待方向明确"
                    elif latest_rsi > 55:
                        rsi_signal = "偏强势，多头占优"
                        rsi_action = "可适度参与"
                    else:
                        rsi_signal = "偏弱势，空头占优"
                        rsi_action = "谨慎操作"
                    
                    analysis_text += f"- **信号判断**: {rsi_signal}\n"
                    analysis_text += f"- **操作建议**: {rsi_action}\n"
                    
                    # RSI背离分析
                    if len(valid_rsi) >= 10:
                        recent_rsi = valid_rsi[-10:]
                        recent_prices = [k.c for k in cd.get_klines()[-10:]]
                        
                        # 简单的背离检测
                        if len(recent_prices) >= 5:
                            price_trend = "上升" if recent_prices[-1] > recent_prices[-5] else "下降"
                            rsi_trend = "上升" if recent_rsi[-1] > recent_rsi[-5] else "下降"
                            
                            if price_trend != rsi_trend:
                                analysis_text += f"- **背离信号**: 价格{price_trend}但RSI{rsi_trend}，存在背离现象\n"
                            else:
                                analysis_text += f"- **趋势一致**: 价格与RSI同步{price_trend}，趋势健康\n"
                    
                    analysis_text += "\n"
                else:
                    analysis_text += "### RSI相对强弱指标分析\n- RSI数据无效\n\n"
            else:
                analysis_text += "### RSI相对强弱指标分析\n- RSI计算失败\n\n"
        except Exception as e:
            analysis_text += f"### RSI相对强弱指标分析\n- RSI计算异常: {str(e)}\n\n"
        
        # 计算布林带指标
        # try:
        #     boll_data = Strategy.idx_boll(cd, period=20)
        #     if boll_data and 'upper' in boll_data and 'middle' in boll_data and 'lower' in boll_data:
        #         upper = boll_data['upper']
        #         middle = boll_data['middle']
        #         lower = boll_data['lower']
                
        #         # 获取最新值
        #         valid_indices = ~(np.isnan(upper) | np.isnan(middle) | np.isnan(lower))
        #         if np.any(valid_indices):
        #             latest_upper = upper[valid_indices][-1]
        #             latest_middle = middle[valid_indices][-1]
        #             latest_lower = lower[valid_indices][-1]
        #             current_price = cd.get_klines()[-1].c
                    
        #             analysis_text += "### 布林带指标分析\n"
        #             analysis_text += f"- **上轨**: {latest_upper:.4f}\n"
        #             analysis_text += f"- **中轨(MA20)**: {latest_middle:.4f}\n"
        #             analysis_text += f"- **下轨**: {latest_lower:.4f}\n"
        #             analysis_text += f"- **当前价格**: {current_price:.4f}\n"
                    
        #             # 布林带位置分析
        #             boll_width = latest_upper - latest_lower
        #             price_position = (current_price - latest_lower) / boll_width if boll_width > 0 else 0.5
                    
        #             analysis_text += f"- **价格位置**: {price_position:.1%}（0%=下轨，100%=上轨）\n"
                    
        #             # 布林带信号判断
        #             if current_price >= latest_upper:
        #                 boll_signal = "价格触及或突破上轨，可能超买"
        #                 boll_action = "注意回调风险"
        #             elif current_price <= latest_lower:
        #                 boll_signal = "价格触及或跌破下轨，可能超卖"
        #                 boll_action = "关注反弹机会"
        #             elif current_price > latest_middle:
        #                 boll_signal = "价格在中轨上方，偏强势"
        #                 boll_action = "可适度看多"
        #             else:
        #                 boll_signal = "价格在中轨下方，偏弱势"
        #                 boll_action = "谨慎看空"
                    
        #             analysis_text += f"- **信号判断**: {boll_signal}\n"
        #             analysis_text += f"- **操作建议**: {boll_action}\n"
                    
        #             # 布林带宽度分析
        #             if len(upper[valid_indices]) >= 20:
        #                 recent_widths = []
        #                 for i in range(-20, 0):
        #                     if abs(i) <= len(upper[valid_indices]):
        #                         width = upper[valid_indices][i] - lower[valid_indices][i]
        #                         recent_widths.append(width)
                        
        #                 if recent_widths:
        #                     avg_width = np.mean(recent_widths)
        #                     width_ratio = boll_width / avg_width if avg_width > 0 else 1
                            
        #                     if width_ratio > 1.5:
        #                         width_analysis = "布林带扩张，波动率增加，趋势可能加强"
        #                     elif width_ratio < 0.7:
        #                         width_analysis = "布林带收缩，波动率降低，可能酝酿突破"
        #                     else:
        #                         width_analysis = "布林带宽度正常，波动率稳定"
                            
        #                     analysis_text += f"- **带宽分析**: {width_analysis}\n"
                    
        #             analysis_text += "\n"
        #         else:
        #             analysis_text += "### 布林带指标分析\n- 布林带数据无效\n\n"
        #     else:
        #         analysis_text += "### 布林带指标分析\n- 布林带计算失败\n\n"
        # except Exception as e:
        #     analysis_text += f"### 布林带指标分析\n- 布林带计算异常: {str(e)}\n\n"
        
        # 计算KDJ指标
        try:
            kdj_data = Strategy.idx_kdj(cd, period=9, M1=3, M2=3)
            if kdj_data and 'k' in kdj_data and 'd' in kdj_data and 'j' in kdj_data:
                k_values = kdj_data['k']
                d_values = kdj_data['d']
                j_values = kdj_data['j']
                
                # 获取最新值
                valid_indices = ~(np.isnan(k_values) | np.isnan(d_values) | np.isnan(j_values))
                if np.any(valid_indices):
                    latest_k = k_values[valid_indices][-1]
                    latest_d = d_values[valid_indices][-1]
                    latest_j = j_values[valid_indices][-1]
                    
                    analysis_text += "### KDJ随机指标分析\n"
                    analysis_text += f"- **K值**: {latest_k:.2f}\n"
                    analysis_text += f"- **D值**: {latest_d:.2f}\n"
                    analysis_text += f"- **J值**: {latest_j:.2f}\n"
                    
                    # KDJ信号判断
                    if latest_k >= 80 and latest_d >= 80:
                        kdj_signal = "KD均在超买区域，回调风险较大"
                        kdj_action = "建议减仓观望"
                    elif latest_k <= 20 and latest_d <= 20:
                        kdj_signal = "KD均在超卖区域，反弹机会较大"
                        kdj_action = "可考虑逢低介入"
                    elif latest_k > latest_d:
                        if latest_k > 50:
                            kdj_signal = "K线上穿D线且在强势区域，多头信号"
                            kdj_action = "可适度看多"
                        else:
                            kdj_signal = "K线上穿D线但仍在弱势区域，谨慎看多"
                            kdj_action = "观察后续走势"
                    else:
                        if latest_k < 50:
                            kdj_signal = "K线下穿D线且在弱势区域，空头信号"
                            kdj_action = "建议谨慎或减仓"
                        else:
                            kdj_signal = "K线下穿D线但仍在强势区域，观察回调"
                            kdj_action = "注意支撑位"
                    
                    analysis_text += f"- **信号判断**: {kdj_signal}\n"
                    analysis_text += f"- **操作建议**: {kdj_action}\n"
                    
                    # J值特殊分析
                    if latest_j > 100:
                        j_analysis = "J值超过100，超买信号强烈，注意回调"
                    elif latest_j < 0:
                        j_analysis = "J值低于0，超卖信号强烈，关注反弹"
                    elif latest_j > latest_k and latest_j > latest_d:
                        j_analysis = "J值领先KD上升，动能较强"
                    elif latest_j < latest_k and latest_j < latest_d:
                        j_analysis = "J值领先KD下降，动能转弱"
                    else:
                        j_analysis = "J值与KD同步，趋势稳定"
                    
                    analysis_text += f"- **J值分析**: {j_analysis}\n\n"
                else:
                    analysis_text += "### KDJ随机指标分析\n- KDJ数据无效\n\n"
            else:
                analysis_text += "### KDJ随机指标分析\n- KDJ计算失败\n\n"
        except Exception as e:
            analysis_text += f"### KDJ随机指标分析\n- KDJ计算异常: {str(e)}\n\n"
        
        # 威廉指标(WR)分析 - 暂时跳过，因为Strategy类中未实现idx_wr方法
        # analysis_text += "### 威廉指标(WR)分析\n- 威廉指标功能暂未实现\n\n"
        
        # 计算移动平均线分析
        try:
            # 计算多个周期的移动平均线
            ma5_data = Strategy.idx_ma(cd, period=5)
            ma10_data = Strategy.idx_ma(cd, period=10)
            ma20_data = Strategy.idx_ma(cd, period=20)
            ma60_data = Strategy.idx_ma(cd, period=60)
            
            current_price = cd.get_klines()[-1].c
            analysis_text += "### 移动平均线分析\n"
            analysis_text += f"- **当前价格**: {current_price:.4f}\n"
            
            ma_values = {}
            ma_signals = []
            
            # 处理各个MA值
            for period, ma_data in [(5, ma5_data), (10, ma10_data), (20, ma20_data), (60, ma60_data)]:
                if ma_data is not None and len(ma_data) > 0:
                    valid_ma = ma_data[~np.isnan(ma_data)]
                    if len(valid_ma) > 0:
                        latest_ma = valid_ma[-1]
                        ma_values[period] = latest_ma
                        
                        # 价格与MA的关系
                        if current_price > latest_ma:
                            position = "上方"
                            strength = ((current_price - latest_ma) / latest_ma) * 100
                        else:
                            position = "下方"
                            strength = ((latest_ma - current_price) / latest_ma) * 100
                        
                        analysis_text += f"- **MA{period}**: {latest_ma:.4f} (价格在{position}，偏离{strength:.2f}%)\n"
                        
                        # 记录信号
                        if current_price > latest_ma:
                            ma_signals.append(f"MA{period}支撑")
                        else:
                            ma_signals.append(f"MA{period}压力")
            
            # 均线排列分析
            if len(ma_values) >= 3:
                ma_list = [(period, value) for period, value in ma_values.items()]
                ma_list.sort(key=lambda x: x[0])  # 按周期排序
                
                # 检查多头排列（短期MA > 长期MA）
                bullish_alignment = True
                bearish_alignment = True
                
                for i in range(len(ma_list) - 1):
                    if ma_list[i][1] <= ma_list[i+1][1]:  # 短期MA不大于长期MA
                        bullish_alignment = False
                    if ma_list[i][1] >= ma_list[i+1][1]:  # 短期MA不小于长期MA
                        bearish_alignment = False
                
                if bullish_alignment:
                    alignment_analysis = "多头排列，趋势向上，支撑较强"
                elif bearish_alignment:
                    alignment_analysis = "空头排列，趋势向下，压力较大"
                else:
                    alignment_analysis = "均线交织，趋势不明确，等待方向选择"
                
                analysis_text += f"- **均线排列**: {alignment_analysis}\n"
            
            # 综合MA信号
            if ma_signals:
                bullish_signals = len([s for s in ma_signals if "支撑" in s])
                bearish_signals = len([s for s in ma_signals if "压力" in s])
                
                if bullish_signals > bearish_signals:
                    ma_overall = f"多头信号占优({bullish_signals}/{len(ma_signals)})，均线支撑较强"
                elif bearish_signals > bullish_signals:
                    ma_overall = f"空头信号占优({bearish_signals}/{len(ma_signals)})，均线压力较大"
                else:
                    ma_overall = "多空信号均衡，均线支撑压力相当"
                
                analysis_text += f"- **综合信号**: {ma_overall}\n\n"
            else:
                analysis_text += "- **综合信号**: 均线数据不足\n\n"
                
        except Exception as e:
            analysis_text += f"### 移动平均线分析\n- 移动平均线计算异常: {str(e)}\n\n"
        
        # 计算历史波动率（标准方法）
        try:
            klines = cd.get_klines()
            if len(klines) >= 30:  # 至少需要30个数据点
                # 获取收盘价序列
                close_prices = [k.c for k in klines]
                
                # 计算对数回报率 ln(今日收盘价 / 昨日收盘价)
                log_returns = []
                for i in range(1, len(close_prices)):
                    if close_prices[i-1] > 0 and close_prices[i] > 0:
                        log_return = np.log(close_prices[i] / close_prices[i-1])
                        log_returns.append(log_return)
                
                if len(log_returns) >= 20:  # 确保有足够的回报率数据
                    # 计算回报率的标准差（日波动率）
                    daily_volatility = np.std(log_returns, ddof=1)  # 使用样本标准差
                    
                    # 年化波动率（使用252个交易日）
                    annualized_volatility = daily_volatility * np.sqrt(252)
                    
                    # 计算历史平均波动率（滚动30期窗口）
                    historical_volatilities = []
                    window_size = min(30, len(log_returns))
                    
                    for i in range(window_size, len(log_returns) + 1):
                        window_returns = log_returns[i-window_size:i]
                        window_vol = np.std(window_returns, ddof=1) * np.sqrt(252)
                        historical_volatilities.append(window_vol)
                    
                    if historical_volatilities:
                        avg_historical_volatility = np.mean(historical_volatilities)
                        volatility_std = np.std(historical_volatilities, ddof=1)
                        current_volatility = historical_volatilities[-1]  # 最新的30期波动率
                        
                        analysis_text += "### 历史波动率分析（标准方法）\n"
                        analysis_text += f"- **当前年化波动率**: {current_volatility:.2f}%\n"
                        analysis_text += f"- **历史平均年化波动率**: {avg_historical_volatility:.2f}%\n"
                        analysis_text += f"- **波动率标准差**: {volatility_std:.2f}%\n"
                        analysis_text += f"- **日波动率**: {daily_volatility:.4f}\n"
                        
                        # 波动率相对水平判断
                        volatility_ratio = current_volatility / avg_historical_volatility if avg_historical_volatility > 0 else 1
                        analysis_text += f"- **波动率倍数**: {volatility_ratio:.2f}倍历史平均水平\n"
                        
                        # 基于历史数据的波动率水平判断
                        if volatility_ratio < 0.7:
                            volatility_level = "低波动率，当前市场异常平静，低于历史平均水平"
                        elif volatility_ratio < 1.3:
                            volatility_level = "正常波动率，接近历史平均水平"
                        elif volatility_ratio < 2.0:
                            volatility_level = "高波动率，明显高于历史平均水平，市场活跃"
                        else:
                            volatility_level = "极高波动率，远超历史平均水平，市场剧烈波动"
                        
                        analysis_text += f"- **波动水平**: {volatility_level}\n"
                        
                        # 基于统计学的波动率异常判断
                        z_score = (current_volatility - avg_historical_volatility) / volatility_std if volatility_std > 0 else 0
                        if abs(z_score) > 2:
                            statistical_level = f"统计异常（Z-score: {z_score:.2f}），波动率处于极端水平"
                        elif abs(z_score) > 1:
                            statistical_level = f"统计偏离（Z-score: {z_score:.2f}），波动率偏离正常范围"
                        else:
                            statistical_level = f"统计正常（Z-score: {z_score:.2f}），波动率在正常范围内"
                        
                        analysis_text += f"- **统计判断**: {statistical_level}\n"
                        
                        # 波动率分位数分析
                        volatility_percentile = (np.sum(np.array(historical_volatilities) <= current_volatility) / len(historical_volatilities)) * 100
                        analysis_text += f"- **历史分位数**: {volatility_percentile:.1f}%（当前波动率在历史数据中的排名）\n"
                    else:
                        analysis_text += "### 历史波动率分析\n- 无法计算历史波动率分布\n"
                else:
                    analysis_text += "### 历史波动率分析\n- 回报率数据不足，无法计算波动率\n"
            else:
                analysis_text += "### 历史波动率分析\n- K线数据不足（少于30期），无法计算历史波动率\n"
            
            # 补充ATR分析作为参考
            try:
                atr_data = Strategy.idx_atr(cd, period=14)
                if atr_data is not None and len(atr_data) > 0:
                    valid_atr = atr_data[~np.isnan(atr_data)]
                    if len(valid_atr) > 0:
                        latest_atr = valid_atr[-1]
                        current_price = cd.get_klines()[-1].c
                        atr_percentage = (latest_atr / current_price) * 100 if current_price > 0 else 0
                        
                        analysis_text += "\n### ATR技术指标（参考）\n"
                        analysis_text += f"- **ATR值**: {latest_atr:.4f}\n"
                        analysis_text += f"- **ATR百分比**: {atr_percentage:.2f}%\n"
                        analysis_text += "- **说明**: ATR反映价格波动幅度，与统计波动率互为补充\n"
            except Exception as e:
                analysis_text += f"\n### ATR技术指标\n- ATR计算异常: {str(e)}\n"
        except Exception as e:
            analysis_text += f"### 历史波动率分析\n- 波动率计算异常: {str(e)}\n\n"
        
        # 综合技术指标评分系统
        analysis_text += "\n## 综合技术指标评分\n"
        
        # 收集各指标信号
        indicator_scores = []
        indicator_signals = []
        
        # MACD评分 (-2到+2)
        if 'macd_signal' in locals():
            if 'MACD金叉' in macd_signal or '多头信号' in macd_signal or '金叉买入' in macd_signal:
                macd_score = 2
            elif 'MACD死叉' in macd_signal or '空头信号' in macd_signal or '死叉卖出' in macd_signal:
                macd_score = -2
            elif '多头趋势' in macd_signal or '上升' in macd_signal:
                macd_score = 1
            elif '空头趋势' in macd_signal or '下降' in macd_signal:
                macd_score = -1
            else:
                macd_score = 0
        else:
            macd_score = 0
        indicator_scores.append(macd_score)
        indicator_signals.append(f"MACD: {macd_score:+d}")
        
        # RSI评分
        try:
            if 'rsi_signal' in locals():
                if '超卖' in rsi_signal and '反弹' in rsi_signal:
                    rsi_score = 2
                elif '超买' in rsi_signal and '回调' in rsi_signal:
                    rsi_score = -2
                elif '中性偏多' in rsi_signal:
                    rsi_score = 1
                elif '中性偏空' in rsi_signal:
                    rsi_score = -1
                else:
                    rsi_score = 0
            else:
                rsi_score = 0
        except:
            rsi_score = 0
        indicator_scores.append(rsi_score)
        indicator_signals.append(f"RSI: {rsi_score:+d}")
        
        # 布林带评分
        try:
            if 'bb_signal' in locals():
                if '下轨支撑' in bb_signal or '超卖反弹' in bb_signal:
                    bb_score = 2
                elif '上轨压力' in bb_signal or '超买回调' in bb_signal:
                    bb_score = -2
                elif '中轨上方' in bb_signal:
                    bb_score = 1
                elif '中轨下方' in bb_signal:
                    bb_score = -1
                else:
                    bb_score = 0
            else:
                bb_score = 0
        except:
            bb_score = 0
        indicator_scores.append(bb_score)
        indicator_signals.append(f"布林带: {bb_score:+d}")
        
        # KDJ评分
        try:
            if 'kdj_signal' in locals():
                if '超卖' in kdj_signal and '反弹' in kdj_signal:
                    kdj_score = 2
                elif '超买' in kdj_signal and '回调' in kdj_signal:
                    kdj_score = -2
                elif '多头信号' in kdj_signal:
                    kdj_score = 1
                elif '空头信号' in kdj_signal:
                    kdj_score = -1
                else:
                    kdj_score = 0
            else:
                kdj_score = 0
        except:
            kdj_score = 0
        indicator_scores.append(kdj_score)
        indicator_signals.append(f"KDJ: {kdj_score:+d}")
        

        
        # 移动平均线评分
        try:
            if 'ma_overall' in locals():
                if '多头信号占优' in ma_overall:
                    if '4/4' in ma_overall or '3/3' in ma_overall:
                        ma_score = 2
                    else:
                        ma_score = 1
                elif '空头信号占优' in ma_overall:
                    if '4/4' in ma_overall or '3/3' in ma_overall:
                        ma_score = -2
                    else:
                        ma_score = -1
                else:
                    ma_score = 0
            else:
                ma_score = 0
        except:
            ma_score = 0
        indicator_scores.append(ma_score)
        indicator_signals.append(f"均线: {ma_score:+d}")
        
        # 计算总分和百分比
        total_score = sum(indicator_scores)
        max_possible_score = len(indicator_scores) * 2
        score_percentage = (total_score + max_possible_score) / (2 * max_possible_score) * 100
        
        analysis_text += f"### 各指标评分详情\n"
        analysis_text += f"- {' | '.join(indicator_signals)}\n"
        analysis_text += f"- **总评分**: {total_score:+d}/{max_possible_score*2:+d} (百分比: {score_percentage:.1f}%)\n\n"
        
        # 综合信号判断
        if total_score >= 6:
            overall_signal = "强烈看多"
            overall_action = "建议积极做多，适当加仓"
            risk_level = "中等"
        elif total_score >= 3:
            overall_signal = "偏多"
            overall_action = "可适度看多，谨慎加仓"
            risk_level = "中等"
        elif total_score >= -2:
            overall_signal = "中性"
            overall_action = "观望为主，等待明确信号"
            risk_level = "较低"
        elif total_score >= -5:
            overall_signal = "偏空"
            overall_action = "可适度看空，考虑减仓"
            risk_level = "中等"
        else:
            overall_signal = "强烈看空"
            overall_action = "建议积极看空，及时减仓"
            risk_level = "较高"
        
        analysis_text += f"### 综合信号判断\n"
        analysis_text += f"- **整体方向**: {overall_signal}\n"
        analysis_text += f"- **操作建议**: {overall_action}\n"
        analysis_text += f"- **风险等级**: {risk_level}\n\n"
        
        # 关键支撑阻力位
        analysis_text += "### 关键价位参考\n"
        try:
            current_price = cd.get_klines()[-1].c
            if 'ma_values' in locals() and ma_values:
                sorted_ma = sorted(ma_values.items(), key=lambda x: abs(x[1] - current_price))
                nearest_ma = sorted_ma[0]
                if current_price > nearest_ma[1]:
                    analysis_text += f"- **最近支撑**: MA{nearest_ma[0]} = {nearest_ma[1]:.4f}\n"
                else:
                    analysis_text += f"- **最近阻力**: MA{nearest_ma[0]} = {nearest_ma[1]:.4f}\n"
            
            # 基于ATR的动态止损
            if 'latest_atr' in locals() and latest_atr > 0:
                dynamic_stop_loss = latest_atr * 2
                analysis_text += f"- **动态止损**: ±{dynamic_stop_loss:.4f} (基于2倍ATR)\n"
        except:
            pass
        analysis_text += "\n"
        
        # 综合交易建议（基于评分系统和波动率）
        analysis_text += "## 综合交易建议\n"
        
        try:
            # 基于综合评分和历史波动率的建议
            if 'current_volatility' in locals():
                # 将年化波动率转换为日波动率用于止损计算
                daily_vol_for_stop = current_volatility / np.sqrt(252) if 'current_volatility' in locals() else 2.0
                stop_loss_pct = daily_vol_for_stop * 100 * 2  # 2倍日波动率作为止损
                
                if total_score >= 6:  # 强烈看多
                    if 'volatility_ratio' in locals() and volatility_ratio < 1.3:
                        analysis_text += f"- **建议**: 技术面强烈看多且波动率正常，建议积极做多\n"
                        analysis_text += f"- **止损建议**: 设置{stop_loss_pct:.1f}%的止损\n"
                    elif 'volatility_ratio' in locals() and volatility_ratio < 2.0:
                        analysis_text += f"- **建议**: 技术面强烈看多但波动率偏高，建议适度做多\n"
                        analysis_text += f"- **止损建议**: 设置{stop_loss_pct * 0.8:.1f}%的紧密止损\n"
                    else:
                        analysis_text += f"- **风险警告**: 技术面看多但波动率极高，建议等待回调\n"
                        
                elif total_score >= 3:  # 偏多
                    analysis_text += f"- **建议**: 技术面偏多，可适度看多，控制仓位\n"
                    analysis_text += f"- **止损建议**: 设置{stop_loss_pct:.1f}%的止损\n"
                    
                elif total_score >= -2:  # 中性
                    analysis_text += f"- **建议**: 技术面中性，建议观望等待明确信号\n"
                    analysis_text += f"- **止损参考**: 如需交易，止损设为{stop_loss_pct:.1f}%\n"
                    
                elif total_score >= -5:  # 偏空
                    analysis_text += f"- **建议**: 技术面偏空，可适度看空或减仓\n"
                    analysis_text += f"- **止损建议**: 设置{stop_loss_pct:.1f}%的止损\n"
                    
                else:  # 强烈看空
                    analysis_text += f"- **建议**: 技术面强烈看空，建议积极看空或止损\n"
                    analysis_text += f"- **止损建议**: 设置{stop_loss_pct * 0.8:.1f}%的紧密止损\n"
                
                # 基于波动率分位数的额外建议
                if 'volatility_percentile' in locals():
                    if volatility_percentile > 90:
                        analysis_text += "- **市场状态**: 波动率处于历史高位（>90%分位），市场情绪激烈，建议降低仓位\n"
                    elif volatility_percentile < 10:
                        analysis_text += "- **市场状态**: 波动率处于历史低位（<10%分位），市场相对平静，可适度增加仓位\n"
                        
            else:
                analysis_text += f"- **建议**: 技术面综合评分{total_score:+d}分，但波动率数据不足，建议谨慎操作\n"
                
        except Exception as e:
            analysis_text += f"- **建议生成异常**: {str(e)}\n"
        
        # 风险提示
        analysis_text += "\n### 风险提示\n"
        analysis_text += "- 技术指标存在滞后性，应结合基本面分析\n"
        analysis_text += "- 市场环境变化可能影响指标有效性\n"
        analysis_text += "- 建议设置合理止损，控制风险\n"
        analysis_text += f"- 当前风险等级: {risk_level}，请据此调整仓位\n"
        analysis_text += f"- 技术面综合评级: {overall_signal} ({score_percentage:.1f}%)\n"
        analysis_text += "- 本分析仅供参考，不构成投资建议\n\n"
        
        return analysis_text if analysis_text else "技术指标分析生成失败"
        
    except ImportError as e:
        logger.error(f"导入技术分析模块失败: {str(e)}")
        return "技术分析模块导入失败，请检查系统配置"
    except Exception as e:
        # 特殊处理tenacity的RetryError
        if 'RetryError' in str(type(e)) or 'RetryError' in str(e):
            logger.error(f"获取K线数据重试失败: {str(e)}")
            return "无法获取K线数据，数据源可能暂时不可用，请稍后重试"
        else:
            logger.error(f"生成技术指标分析时发生错误: {str(e)}")
            return f"技术指标分析生成错误: {str(e)}"



def _generate_chart_snapshot_html(code: str, market: str) -> str:
    """
    生成TradingView图表快照的HTML代码
    
    Args:
        code: 股票代码
        market: 市场类型
    
    Returns:
        str: 图表HTML代码
    """
    try:
        # 构建图表URL
        chart_url = f"/?market={market}&code={code}"
        
        # 获取市场中文名称
        market_names = {
            'a': '沪深A股',
            'hk': '港股', 
            'us': '美股',
            'fx': '外汇',
            'futures': '国内期货',
            'ny_futures': '纽约期货',
            'currency': '数字货币(合约)',
            'currency_spot': '数字货币(现货)'
        }
        market_name = market_names.get(market, market)
        
        # 生成图表链接HTML（适合报告显示）
        chart_html = f"""
📊 **{code} 缠论图表分析**

> 市场：{market_name}  
> 代码：{code}  
> [📈 点击查看实时缠论图表]({chart_url})

*注：图表包含完整的缠论分析，包括分型、笔、线段、中枢等技术要素，建议在新窗口中打开查看详细分析。*
        """.strip()
        
        return chart_html
        
    except Exception as e:
        logger.error(f"生成图表HTML失败: {str(e)}")
        return ""


# LangGraph工作流状态定义
from typing import TypedDict, List, Dict, Optional

class ReportGenerationState(TypedDict):
    """报告生成工作流的共享状态"""
    original_news: List[Dict]   # 原始新闻输入
    economic_data: List[Dict]   # 经济数据输入
    geopolitical_news: List[Dict]  # 地缘政治新闻输入
    current_market: str         # 当前市场
    current_code: str           # 当前代码
    name: str                   # 股票名称
    frequency: str              # 分析周期（如'd'日线, 'w'周线等）
    
    # 各个节点分析后生成的结果
    macro_analysis: Optional[str]
    economic_analysis: Optional[str]  # 经济数据分析结果
    technical_analysis: Optional[str] 
    chanlun_analysis: Optional[str]
    financial_analysis: Optional[str]  # 财务分析结果
    geopolitical_analysis: Optional[str]  # 地缘政治分析结果
    research_context: Optional[str]  # 结构化研究上下文
    scenario_route: Optional[Dict[str, Any]]  # 场景化路由结果
    reflection_memory: Optional[Dict[str, Any]]  # 反思记忆
    quick_research: Optional[Dict[str, Any]]  # 快速研究快照
    deep_research: Optional[Dict[str, Any]]  # 深度研究计划
    bullish_thesis: Optional[str]  # 多头研究结论
    bearish_thesis: Optional[str]  # 空头研究结论
    research_verdict: Optional[str]  # 研究经理裁决
    risk_assessment: Optional[str]  # 风险经理结论
    
    # 最终的报告
    final_report: Optional[str]
    
    # 反思修正相关字段
    needs_revision: bool         # 是否需要修正
    revision_target_node: str   # 需要修正的目标节点
    revision_count: int         # 修正次数计数器


def _format_economic_data_for_analysis(economic_data: List[Dict]) -> str:
    """格式化经济数据供AI分析使用"""
    if not economic_data:
        return "暂无经济数据"
    
    # 按国家分组经济数据
    countries_data = {}
    
    # 定义助记符前缀到国家的映射
    country_mapping = {
        'CH': '中国',
        'US': '美国',
        'EU': '欧盟',
        'EM': '欧洲',  # 欧洲经济数据助记符前缀
        'EK': '欧洲',  # 欧洲经济数据助记符前缀
        'JP': '日本',
        'UK': '英国',
        'CA': '加拿大',
        'AU': '澳大利亚',
        'NZ': '新西兰'
    }
    
    for data in economic_data:
        mnemonic = data.get('ds_mnemonic', '') or ''
        country = '未知国家'
        
        # 首先尝试从助记符前缀识别国家
        if mnemonic:  # 确保mnemonic不为空
            for prefix, country_name in country_mapping.items():
                if mnemonic.startswith(prefix):
                    country = country_name
                    break
        
        # 如果还是未知国家，尝试从indicator_name获取
        if country == '未知国家':
            indicator_name = (data.get('indicator_name', '') or '').lower()
            if indicator_name and ('cny' in indicator_name or '中国' in indicator_name or 'ch' in indicator_name):
                country = '中国'
            elif indicator_name and ('usd' in indicator_name or 'america' in indicator_name or '美国' in indicator_name):
                country = '美国'
            elif indicator_name and ('eur' in indicator_name or 'europe' in indicator_name or '欧盟' in indicator_name):
                country = '欧盟'
            elif indicator_name and ('jpy' in indicator_name or 'japan' in indicator_name or '日本' in indicator_name):
                country = '日本'
            elif indicator_name and ('gbp' in indicator_name or 'uk' in indicator_name or '英国' in indicator_name):
                country = '英国'
            elif indicator_name and ('cad' in indicator_name or 'canada' in indicator_name or '加拿大' in indicator_name):
                country = '加拿大'
            elif indicator_name and ('aud' in indicator_name or 'australia' in indicator_name or '澳大利亚' in indicator_name):
                country = '澳大利亚'
            elif indicator_name and ('nzd' in indicator_name or 'new zealand' in indicator_name or '新西兰' in indicator_name):
                country = '新西兰'
            else:
                country = '其他'
        
        if country not in countries_data:
            countries_data[country] = []
        countries_data[country].append(data)
    
    formatted_text = ""
    for country, data_list in countries_data.items():
        print('country',country)
        formatted_text += f"\n## {country}经济数据:\n"
        formatted_text += "-" * 40 + "\n"
        
        for data in data_list:
            mnemonic = data.get('ds_mnemonic', 'N/A')
            indicator = data.get('indicator_name', 'N/A')
            latest_value = data.get('latest_value', 'N/A')
            previous_value = data.get('previous_value', 'N/A')
            previous_year_value = data.get('previous_year_value', 'N/A')
            yoy_change = data.get('yoy_change_pct', 'N/A')
            units = data.get('units', '')
            year = data.get('year', 'N/A')
            
            # 尝试从助记符推断指标类型
            indicator_type = _get_indicator_type_from_mnemonic(mnemonic)
            display_name = f"{indicator_type}" if indicator_type != mnemonic else mnemonic
            
            formatted_text += f"**{mnemonic}** ({display_name}):\n"
            formatted_text += f"  - 最新值: {latest_value} {units}\n"
            formatted_text += f"  - 前值: {previous_value} {units}\n"
            formatted_text += f"  - 去年同期: {previous_year_value} {units}\n"
            formatted_text += f"  - 同比变化: {yoy_change}%\n"
            formatted_text += f"  - 年份: {year}\n\n"
    
    return formatted_text


def _get_indicator_type_from_mnemonic(mnemonic: str) -> str:
    """从助记符推断指标类型"""
    # 处理空值情况
    if not mnemonic:
        return mnemonic or ''
    
    # 定义常见的经济指标助记符映射
    indicator_mapping = {
        # 中国指标
        'CHBPEXGS': '中国商品出口总额',
        'CHCURBAL': '中国经常账户余额',
        'CHEXNGS': '中国出口总额',
        'CHGOVBALA': '中国政府预算余额',
        'CHIFATOTA': '中国固定资产投资总额',
        'CHVA%NATR': '中国增值税税率',
        'CHPROFTSA': '中国工业企业利润总额',
        'CHIPTOT.H': '中国工业生产总值指数',
        'CHCAR': '中国汽车产量',
        'CHRETUOTA': '中国零售总额',
        
        # 美国指标
        'USGDP': '美国GDP',
        'USCPI': '美国消费者价格指数',
        'USUNEMPLOYMENT': '美国失业率',
        'USPMI': '美国制造业PMI',
        'USNFP': '美国非农就业人数',
        'USRETAIL': '美国零售销售',
        'USINFLATION': '美国通胀率',
        'USFED': '美国联邦基金利率',
        
        # 其他常见指标关键词
        'GDP': 'GDP',
        'CPI': '消费者价格指数',
        'PMI': '制造业PMI',
        'UNEMPLOYMENT': '失业率',
        'INFLATION': '通胀率',
        'RETAIL': '零售销售',
        'EXPORT': '出口',
        'IMPORT': '进口',
        'BALANCE': '余额',
        'INVESTMENT': '投资',
        'PRODUCTION': '生产'
    }
    
    # 首先尝试精确匹配
    if mnemonic in indicator_mapping:
        return indicator_mapping[mnemonic]
    
    # 然后尝试部分匹配
    for key, value in indicator_mapping.items():
        if mnemonic and key in mnemonic.upper():
            return value
    
    # 如果都没有匹配，返回原助记符
    return mnemonic


def _format_news_content(news_list: List[Dict]) -> str:
    """格式化新闻内容，按发布时间排序，最新新闻优先"""
    from datetime import datetime, timedelta
    import dateutil.parser
    
    # 按发布时间排序，最新的排在前面
    def parse_time(news):
        published_at = news.get('published_at', '')
        if not published_at or published_at == '未知时间':
            return datetime.min  # 未知时间的新闻排在最后
        try:
            return dateutil.parser.parse(published_at)
        except:
            return datetime.min
    
    sorted_news = sorted(news_list, key=parse_time, reverse=True)
    
    # 计算时间权重标识
    now = datetime.now()
    news_content = ""
    
    for i, news in enumerate(sorted_news[:10], 1):  # 限制最多10条新闻
        title = news.get('title', '无标题')
        body = news.get('body', news.get('content', '无内容'))
        published_at = news.get('published_at', '未知时间')
        source = news.get('source', '未知来源')
        
        # 添加时间权重标识
        time_weight = ""
        if published_at != '未知时间':
            try:
                pub_time = dateutil.parser.parse(published_at)
                time_diff = now - pub_time
                if time_diff.days == 0:
                    time_weight = "【🔥最新】"  # 当天新闻
                elif time_diff.days == 1:
                    time_weight = "【⚡近期】"  # 昨天新闻
                elif time_diff.days <= 3:
                    time_weight = "【📈重要】"  # 3天内新闻
                else:
                    time_weight = "【📰参考】"  # 较早新闻
            except:
                time_weight = "【📰参考】"
        
        news_content += f"\n{i}. {time_weight}标题: {title}\n"
        news_content += f"   来源: {source}\n"
        news_content += f"   时间: {published_at}\n"
        if body and body != '无内容':
            # 限制每条新闻内容长度
            body_summary = body[:300] + '...' if len(body) > 300 else body
            news_content += f"   内容: {body_summary}\n"
        news_content += "\n"
    return news_content


def _call_ai_and_get_content(ai_client, prompt: str) -> str:
    """调用AI并获取内容的辅助函数"""
    try:
        result = ai_client.req_openrouter_ai_model(prompt)
        if result.get('ok', False):
            return result.get('msg', '').strip()
        else:
            error_msg = result.get('msg', '未知错误')
            logger.error(f"AI调用失败: {error_msg}")
            return f"AI分析失败: {error_msg}"
    except Exception as e:
        logger.error(f"AI调用异常: {str(e)}")
        return f"AI分析异常: {str(e)}"


def _collect_news_evidence_stats(news_list: List[Dict[str, Any]]) -> tuple[Dict[str, int], Dict[str, int], List[str]]:
    evidence_counts = {"direct": 0, "driver": 0, "background": 0}
    direction_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    evidence_lines: List[str] = []

    for news in news_list:
        metadata = news.get("metadata", {}) if isinstance(news.get("metadata", {}), dict) else {}
        evidence_type = news.get("evidence_type", "background")
        impact_direction = news.get("impact_direction", "neutral")
        if evidence_type not in evidence_counts:
            evidence_type = "background"
        if impact_direction not in direction_counts:
            impact_direction = "neutral"

        evidence_counts[evidence_type] += 1
        direction_counts[impact_direction] += 1

    for index, news in enumerate(news_list[:8], 1):
        metadata = news.get("metadata", {}) if isinstance(news.get("metadata", {}), dict) else {}

        title = news.get("title") or metadata.get("title") or "无标题"
        source = news.get("source") or metadata.get("source") or "未知来源"
        published_at = news.get("published_at") or metadata.get("published_at") or "未知时间"
        evidence_type = news.get("evidence_type", "background")
        impact_direction = news.get("impact_direction", "neutral")
        if evidence_type not in evidence_counts:
            evidence_type = "background"
        if impact_direction not in direction_counts:
            impact_direction = "neutral"
        body = news.get("body") or news.get("content") or news.get("document") or ""
        body = re.sub(r"\s+", " ", body).strip()
        snippet = body[:120] + "..." if len(body) > 120 else body
        evidence_lines.append(
            f"{index}. [{impact_direction}][{evidence_type}] {title} | 来源: {source} | 时间: {published_at}\n"
            f"   摘要: {snippet or '无摘要'}"
        )

    return evidence_counts, direction_counts, evidence_lines


def _build_economic_data_highlights(economic_data_list: List[Dict[str, Any]], limit: int = 8) -> List[str]:
    highlights: List[str] = []
    for item in economic_data_list[:limit]:
        mnemonic = item.get("ds_mnemonic", "N/A")
        indicator_name = item.get("indicator_name", item.get("name", mnemonic))
        latest_value = item.get("latest_value", item.get("value", "N/A"))
        previous_value = item.get("previous_value", item.get("pre_value", "N/A"))
        yoy_change = item.get("yoy_change_pct", item.get("yoy", "N/A"))
        units = item.get("units", item.get("unit", ""))
        highlights.append(
            f"- {indicator_name}({mnemonic}): 最新={latest_value}{units} 前值={previous_value}{units} 同比={yoy_change}%"
        )
    return highlights


def _build_market_research_context(
    news_list: List[Dict[str, Any]],
    economic_data_list: List[Dict[str, Any]],
    current_market: str,
    current_code: str,
    name: str,
    geopolitical_news: Optional[List[Dict[str, Any]]] = None,
) -> str:
    evidence_counts, direction_counts, evidence_lines = _collect_news_evidence_stats(news_list)
    economic_highlights = _build_economic_data_highlights(economic_data_list)
    geopolitical_summary = _summarize_geopolitical_asset_impact(
        geopolitical_news or [],
        current_code,
        current_market,
    )
    asset_template = _get_asset_storyline_template(current_code, current_market)
    weighted_storylines = sorted(
        asset_template.get("weights", {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    geopolitical_direction_label = {
        "bullish": "偏利多",
        "bearish": "偏利空",
        "neutral": "中性",
    }.get(geopolitical_summary.get("overall_direction", "neutral"), "中性")

    return f"""
研究对象: {name or current_code or '未知标的'}
市场: {current_market or '未知市场'}
代码: {current_code or '未知代码'}

资产研究模板:
- 研究重点: {asset_template.get('focus', '综合分析')}
- 优先主线: {', '.join(f'{label}({weight:.2f})' for label, weight in weighted_storylines) if weighted_storylines else '综合驱动'}

新闻证据统计:
- 直接相关: {evidence_counts['direct']}
- 驱动相关: {evidence_counts['driver']}
- 背景参考: {evidence_counts['background']}

方向性统计:
- 利多: {direction_counts['bullish']}
- 利空: {direction_counts['bearish']}
- 中性: {direction_counts['neutral']}

关键新闻证据:
{chr(10).join(evidence_lines) if evidence_lines else '- 暂无新闻证据'}

重点经济数据:
{chr(10).join(economic_highlights) if economic_highlights else '- 暂无经济数据'}

地缘政治影响摘要:
- 总体判断: {geopolitical_direction_label}
- 地缘利多线索: {geopolitical_summary.get('direction_counts', {}).get('bullish', 0)}
- 地缘利空线索: {geopolitical_summary.get('direction_counts', {}).get('bearish', 0)}
- 地缘中性线索: {geopolitical_summary.get('direction_counts', {}).get('neutral', 0)}
{chr(10).join(geopolitical_summary.get('detail_lines', [])) if geopolitical_summary.get('detail_lines') else '- 暂无显著地缘政治影响'}
""".strip()


def _build_analyst_report_bundle(state: ReportGenerationState) -> str:
    sections = [
        ("宏观分析师", state.get("macro_analysis", "暂无")),
        ("经济数据分析师", state.get("economic_analysis", "暂无")),
        ("技术指标分析师", state.get("technical_analysis", "暂无")),
        ("缠论结构专家", state.get("chanlun_analysis", "暂无")),
        ("财务分析师", state.get("financial_analysis", "暂无")),
        ("地缘政治分析师", state.get("geopolitical_analysis", "暂无")),
    ]
    return "\n\n".join(f"【{title}】\n{content}" for title, content in sections)


def _get_geopolitical_asset_rules(asset_code: Optional[str], market: str) -> Dict[str, Dict[str, Any]]:
    normalized = _normalize_asset_code(asset_code)
    asset_rules = {
        "XAU": {
            "middle_east": {"direction": "bullish", "weight": 1.4, "reason": "中东升级通常强化避险需求，利多黄金"},
            "russia_ukraine": {"direction": "bullish", "weight": 1.2, "reason": "俄乌冲突升级提升避险偏好，利多黄金"},
            "global_sanctions": {"direction": "bullish", "weight": 1.1, "reason": "制裁与供应链风险通常推升避险资产需求"},
            "us_china": {"direction": "bullish", "weight": 1.0, "reason": "中美摩擦升级会提升全球风险厌恶情绪"},
        },
        "CL": {
            "middle_east": {"direction": "bullish", "weight": 1.5, "reason": "中东冲突可能扰动原油供给，利多油价"},
            "russia_ukraine": {"direction": "bullish", "weight": 1.3, "reason": "俄乌冲突与能源制裁会收紧供给预期"},
            "global_sanctions": {"direction": "bullish", "weight": 1.2, "reason": "能源与运输制裁常抬升原油风险溢价"},
            "us_china": {"direction": "bearish", "weight": 0.8, "reason": "中美摩擦升级可能压制增长与原油需求预期"},
        },
        "USDCNY": {
            "us_china": {"direction": "bullish", "weight": 1.5, "reason": "中美摩擦升级通常利多美元兑人民币"},
            "taiwan_strait": {"direction": "bullish", "weight": 1.4, "reason": "台海紧张会推升人民币风险溢价"},
            "global_sanctions": {"direction": "bullish", "weight": 1.1, "reason": "制裁风险升温通常强化美元与避险需求"},
            "middle_east": {"direction": "bullish", "weight": 0.8, "reason": "全球避险升温通常偏利多美元兑人民币"},
        },
        "EURUSD": {
            "russia_ukraine": {"direction": "bearish", "weight": 1.5, "reason": "俄乌冲突升级往往更伤及欧洲增长与欧元"},
            "global_sanctions": {"direction": "bearish", "weight": 1.2, "reason": "制裁升级通常加剧欧洲能源与增长压力"},
            "us_china": {"direction": "bearish", "weight": 0.9, "reason": "全球风险厌恶上升时美元通常相对受益"},
            "middle_east": {"direction": "bearish", "weight": 0.8, "reason": "中东风险升温通常强化美元避险属性"},
        },
        "USDJPY": {
            "us_china": {"direction": "bearish", "weight": 1.1, "reason": "风险厌恶升温时日元避险属性通常强于美元"},
            "taiwan_strait": {"direction": "bearish", "weight": 1.3, "reason": "亚太地缘紧张常带动日元走强，压制美元兑日元"},
            "korean_peninsula": {"direction": "bearish", "weight": 1.2, "reason": "半岛风险升级通常推升避险型日元"},
            "middle_east": {"direction": "bearish", "weight": 0.8, "reason": "全球风险厌恶升温时日元通常受益"},
        },
    }
    if normalized in asset_rules:
        return asset_rules[normalized]
    if market == "futures":
        return {
            "middle_east": {"direction": "bullish", "weight": 1.0, "reason": "地缘冲突可能抬升商品风险溢价"},
            "global_sanctions": {"direction": "bullish", "weight": 0.8, "reason": "制裁升级可能压缩供给并抬升波动"},
        }
    if market == "fx":
        return {
            "us_china": {"direction": "neutral", "weight": 0.5, "reason": "外汇受地缘事件影响需结合具体币种判断"},
            "global_sanctions": {"direction": "neutral", "weight": 0.5, "reason": "制裁影响方向取决于具体货币的避险属性"},
        }
    return {}


def _summarize_geopolitical_asset_impact(
    geopolitical_news: List[Dict[str, Any]],
    asset_code: Optional[str],
    market: str,
) -> Dict[str, Any]:
    rules = _get_geopolitical_asset_rules(asset_code, market)
    direction_scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    direction_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    detail_lines: List[str] = []

    for news in geopolitical_news[:12]:
        topics = news.get("geopolitical_topics", []) or []
        metadata = news.get("metadata", {}) if isinstance(news.get("metadata", {}), dict) else {}
        matched_terms = news.get("geopolitical_matched_terms", []) or []
        title = metadata.get("title") or news.get("title") or "无标题"
        importance_score = float(metadata.get("importance_score", 0) or 0)
        base_score = float(news.get("geopolitical_score", 0) or 0) + importance_score

        item_direction = "neutral"
        item_score = 0.0
        item_reason = "未建立该资产的明确地缘映射规则"
        for topic in topics:
            rule = rules.get(topic)
            if not rule:
                continue
            weighted_score = base_score * float(rule.get("weight", 1.0))
            direction = rule.get("direction", "neutral")
            if weighted_score >= item_score:
                item_direction = direction
                item_score = weighted_score
                item_reason = rule.get("reason", item_reason)

        direction_scores[item_direction] += item_score
        direction_counts[item_direction] += 1
        detail_lines.append(
            f"- [{item_direction}] {title} | 主题: {', '.join(topics) or '未分类'} | "
            f"命中词: {', '.join(matched_terms[:4]) or '无'} | 原因: {item_reason}"
        )

    if direction_scores["bullish"] > direction_scores["bearish"]:
        overall_direction = "bullish"
    elif direction_scores["bearish"] > direction_scores["bullish"]:
        overall_direction = "bearish"
    else:
        overall_direction = "neutral"

    return {
        "overall_direction": overall_direction,
        "direction_scores": direction_scores,
        "direction_counts": direction_counts,
        "detail_lines": detail_lines[:8],
    }


def _format_financial_data_for_analysis(financial_data,name) -> str:
    """使用大模型对公司财务数据进行深度分析"""
    if not financial_data:
        return "暂无财务数据"
    
    try:
        from chanlun.tools.ai_analyse import AIAnalyse
        
        # 按报告日期和报表类型分组财务数据
        reports_by_date = {}
        for item in financial_data:
            report_date = item.report_date.strftime('%Y-%m-%d') if item.report_date else '未知日期'
            statement_type = item.statement_type or '未知类型'
            
            if report_date not in reports_by_date:
                reports_by_date[report_date] = {}
            
            if statement_type not in reports_by_date[report_date]:
                reports_by_date[report_date][statement_type] = {}
            
            item_name = item.item_name or '未知项目'
            item_value = item.item_value if item.item_value is not None else 0
            reports_by_date[report_date][statement_type][item_name] = item_value
        
        # 按日期排序（最新的在前）
        sorted_dates = sorted(reports_by_date.keys(), reverse=True)
        
        if not sorted_dates:
            return "暂无有效财务数据"
        
        # 构建完整的财务数据供大模型分析
        financial_data_text = "\n=== 公司完整财务报表数据 ===\n\n"
        
        # 添加数据概览
        financial_data_text += f"数据范围: {sorted_dates[-1]} 至 {sorted_dates[0]}\n"
        financial_data_text += f"报告期数: {len(sorted_dates)}个\n"
        financial_data_text += f"数据记录总数: {len(financial_data)}条\n\n"
        
        # 详细展示每个报告期的财务数据
        for i, report_date in enumerate(sorted_dates):
            date_data = reports_by_date[report_date]
            financial_data_text += f"\n📅 **{report_date} 财务数据**\n"
            
            for statement_type, items in date_data.items():
                financial_data_text += f"\n📋 {statement_type}:\n"
                
                # 显示所有财务项目
                for item_name, value in items.items():
                    formatted_value = _format_financial_value(value)
                    financial_data_text += f"  • {item_name}: {formatted_value}\n"
        
        # 构建大模型分析提示词
        ai_prompt = f"""
你是一位资深的财务分析专家，请基于{name}的完整财务报表数据进行深度分析。

**重要说明：以下所有财务数据均为该公司正式披露的历史财务报表信息，全部为已发布的实际数据，不包含任何预测、预期或市场估计数据。请严格基于这些历史已发布数据进行分析，不要在分析中提及任何预测数据或市场预期。**

{financial_data_text}

**分析重点：请特别关注最新财务数据的变动情况和趋势分析**

请从以下维度进行全面深度分析，**重点突出最新数据的变化**：

1. **最新财务表现分析（重点）**
   - **重点分析最新报告期的财务表现变化**
   - 对比最新期与上一期的关键指标变动（同比、环比增长率）
   - 识别最新财务数据中的重要变化和转折点
   - 分析最新期财务表现的驱动因素

2. **最新盈利能力变动分析（重点）**
   - **重点关注最新期营业收入、净利润的变动情况**
   - 分析最新期毛利率、净利率等关键比率的变化趋势
   - 评估最新期盈利质量的改善或恶化情况
   - 识别影响最新期盈利能力的关键因素

3. **最新成长性趋势分析（重点）**
   - **重点评估最新期的收入增长率、利润增长率变化**
   - 分析最新期业务扩张情况和市场竞争力变化
   - 基于最新数据判断成长性的可持续性
   - 识别最新期成长性的新驱动因素或风险点

4. **最新费用结构变化分析**
   - 分析最新期研发费用、员工薪酬等关键费用的变动
   - 评估最新期费用控制效果和运营效率变化
   - 分析最新期费用结构优化情况

5. **最新财务风险变化评估**
   - 基于最新数据评估财务风险的新变化
   - 分析最新期财务稳定性的改善或恶化
   - 识别最新财务数据中的新风险信号或改善迹象

6. **最新竞争力变化分析**
   - 结合最新财务数据分析竞争地位的变化
   - 评估最新期在行业中的相对表现变化

7. **基于最新数据的投资价值评估**
   - **重点基于最新财务数据变化评估投资价值**
   - 提供基于最新数据变动的投资建议和风险提示
   - 识别需要重点关注的最新财务指标变化

**输出要求：**
- 每个分析维度都要突出最新数据的变化情况
- 优先展示最新期与前期的对比分析
- 重点标注关键财务指标的最新变动幅度
- 字数控制在2000字左右，重点突出最新变化
"""
        
        # 调用大模型进行分析
        ai_client = AIAnalyse("a")  # 使用A股市场配置
        analysis_result = _call_ai_and_get_content(ai_client, ai_prompt)
        
        return analysis_result
        
    except Exception as e:
        logger.error(f"财务数据分析异常: {str(e)}")
        return f"财务数据分析异常: {str(e)}"


def _extract_key_financial_items(items: dict) -> dict:
    """提取关键财务指标 - 基于实际数据库财务代码格式
    
    数据库中的item_name格式为："代码 (英文描述)"
    例如："CIAC (Income Available to Com)", "ECOR (Vehicle sales)"
    """
    key_items = {}
    
    # 基于实际数据库中的财务代码格式进行精确匹配
    key_mappings = {
        # 收入相关 - 基于实际数据格式
        'Vehicle Sales': 'ECOR (Vehicle sales)',
        'Other Revenue': 'ECOR (Other sales and services)',
        
        # 利润相关 - 基于实际数据格式
        'Net Income': 'CIAC (Income Available to Com)',
        'Net Income Before Taxes': 'EIBT (Net Income Before Taxes)',
        'Operating Income': 'EONT (Other operating income, net)',
        
        # 费用相关 - 基于实际数据格式
        'Employee Compensation': 'ERAD (Employee compensation)',
        'Employee Compensation SGA': 'ELAR (Employee compensation in SGA)',
        'R&D Expenses': 'ERAD (Research and development)',
        
        # 每股数据 - 基于实际数据格式
        'Basic EPS': 'GBAI (Basic EPS Including ExtraOrd)',
        'Basic EPS Excluding': 'GBBF (Basic EPS Excluding ExtraOrd)',
        'Diluted EPS': 'GDAI (Diluted EPS Including ExtraOrd)',
        'Diluted EPS Excluding': 'GDBF (Diluted EPS Excluding ExtraOrd)',
        'Basic Shares': 'GBAS (Basic Weighted Average Shares)',
        'Diluted Shares': 'GDWS (Diluted Weighted Average Shares)',
        'DPS Class A': 'DDPS1 (DPS-Ordinary Shares Class A)',
        'DPS Class B': 'DDPS2 (DPS-Ordinary Shares Class B)',
        
        # 其他指标 - 基于实际数据格式
        'Minority Interest': 'CMIN (Net income attributable to nonco)',
    }
    
    # 精确匹配财务指标
    for key_name, exact_pattern in key_mappings.items():
        if exact_pattern in items:
            key_items[key_name] = items[exact_pattern]
    
    # 模糊匹配（用于处理可能的格式变化）
    fallback_mappings = {
        'Net Income': ['CIAC', 'NINC', 'GDNI'],
        'Net Income Before Taxes': ['EIBT'],
        'Operating Income': ['EONT'],
        'Employee Compensation': ['ERAD'],
        'Basic EPS': ['GBAI', 'GBBF'],
        'Diluted EPS': ['GDAI', 'GDBF'],
        'Basic Shares': ['GBAS'],
        'Diluted Shares': ['GDWS'],
        'DPS Class A': ['DDPS1'],
        'DPS Class B': ['DDPS2'],
        'Minority Interest': ['CMIN'],
    }
    
    # 对于没有精确匹配的指标，尝试模糊匹配
    for key_name, code_patterns in fallback_mappings.items():
        if key_name in key_items:  # 已经找到，跳过
            continue
            
        for code in code_patterns:
            for item_name, value in items.items():
                if item_name.startswith(code + ' ('):
                    key_items[key_name] = value
                    break
            if key_name in key_items:
                break
    
    # 计算总收入（Vehicle Sales + Other Revenue）
    if 'Vehicle Sales' in key_items and 'Other Revenue' in key_items:
        key_items['Total Revenue'] = key_items['Vehicle Sales'] + key_items['Other Revenue']
    elif 'Vehicle Sales' in key_items:
        key_items['Total Revenue'] = key_items['Vehicle Sales']
    elif 'Other Revenue' in key_items:
        key_items['Total Revenue'] = key_items['Other Revenue']
    
    # 合并员工薪酬数据
    if 'Employee Compensation' in key_items and 'Employee Compensation SGA' in key_items:
        key_items['Total Employee Compensation'] = key_items['Employee Compensation'] + key_items['Employee Compensation SGA']
    
    return key_items


def _format_financial_value(value) -> str:
    """格式化财务数值"""
    if not isinstance(value, (int, float)):
        return str(value)
    
    if abs(value) >= 1e8:  # 亿元
        return f"{value/1e8:.2f}亿"
    elif abs(value) >= 1e4:  # 万元
        return f"{value/1e4:.2f}万"
    else:
        return f"{value:,.0f}"


def _analyze_income_statement(reports_by_date: dict, sorted_dates: list) -> list:
    """详细分析利润表结构 (Income Statement Analysis)"""
    income_analysis = []
    
    if len(sorted_dates) < 1:
        return income_analysis
    
    try:
        # 获取最新期数据
        latest_date = sorted_dates[0]
        latest_data = reports_by_date[latest_date]
        
        # 合并所有报表类型的数据
        combined_data = {}
        for statement_type, items in latest_data.items():
            combined_data.update(items)
        
        key_items = _extract_key_financial_items(combined_data)
        
        income_analysis.append("\n📊 **利润表结构分析**")
        
        # 1. 收入结构分析
        income_analysis.append("\n💰 **收入结构**")
        
        if 'Total Revenue' in key_items:
            total_revenue = key_items['Total Revenue']
            income_analysis.append(f"  • 总收入: {_format_financial_value(total_revenue)}")
            
            # 分析收入构成
            if 'Operating Revenue' in key_items:
                op_revenue = key_items['Operating Revenue']
                op_ratio = (op_revenue / total_revenue) * 100 if total_revenue != 0 else 0
                income_analysis.append(f"  • 营业收入: {_format_financial_value(op_revenue)} ({op_ratio:.1f}%)")
            
            if 'Other Revenue' in key_items:
                other_revenue = key_items['Other Revenue']
                other_ratio = (other_revenue / total_revenue) * 100 if total_revenue != 0 else 0
                income_analysis.append(f"  • 其他收入: {_format_financial_value(other_revenue)} ({other_ratio:.1f}%)")
        
        # 2. 成本费用分析
        income_analysis.append("\n💸 **成本费用结构**")
        
        if 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
            total_revenue = key_items['Total Revenue']
            
                # 费用分析 - 基于实际可用数据
            if 'R&D Expenses' in key_items:
                rd_expense = key_items['R&D Expenses']
                rd_ratio = (rd_expense / total_revenue) * 100
                income_analysis.append(f"  • 研发费用: {_format_financial_value(rd_expense)} ({rd_ratio:.2f}%)")
            
            if 'Employee Compensation' in key_items:
                emp_expense = key_items['Employee Compensation']
                emp_ratio = (emp_expense / total_revenue) * 100
                income_analysis.append(f"  • 员工薪酬: {_format_financial_value(emp_expense)} ({emp_ratio:.2f}%)")
            
            if 'SGA Expenses' in key_items:
                sga_expense = key_items['SGA Expenses']
                sga_ratio = (sga_expense / total_revenue) * 100
                income_analysis.append(f"  • 销售管理费用: {_format_financial_value(sga_expense)} ({sga_ratio:.2f}%)")
            
            if 'Interest Expense' in key_items:
                interest_expense = key_items['Interest Expense']
                interest_ratio = (interest_expense / total_revenue) * 100
                income_analysis.append(f"  • 利息费用: {_format_financial_value(interest_expense)} ({interest_ratio:.2f}%)")
            
            if 'Tax Expense' in key_items:
                tax_expense = key_items['Tax Expense']
                tax_ratio = (tax_expense / total_revenue) * 100
                income_analysis.append(f"  • 税费支出: {_format_financial_value(tax_expense)} ({tax_ratio:.2f}%)")
        
        # 3. 利润层次分析 - 基于实际可用数据
        income_analysis.append("\n📈 **利润层次分析**")
        
        if 'Operating Income' in key_items:
            op_income = key_items['Operating Income']
            income_analysis.append(f"  • 其他营业收入: {_format_financial_value(op_income)}")
            
            if 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                op_margin = (op_income / key_items['Total Revenue']) * 100
                income_analysis.append(f"    占总收入比例: {op_margin:.2f}%")
        
        if 'Net Income Before Taxes' in key_items:
            income_bt = key_items['Net Income Before Taxes']
            income_analysis.append(f"  • 税前净利润: {_format_financial_value(income_bt)}")
            
            if 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                bt_margin = (income_bt / key_items['Total Revenue']) * 100
                income_analysis.append(f"    税前净利润率: {bt_margin:.2f}%")
        
        if 'Net Income' in key_items:
            net_income = key_items['Net Income']
            income_analysis.append(f"  • 净利润: {_format_financial_value(net_income)}")
            
            if 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                net_margin = (net_income / key_items['Total Revenue']) * 100
                income_analysis.append(f"    净利润率: {net_margin:.2f}%")
        
        # 少数股东权益分析
        if 'Minority Interest' in key_items:
            minority = key_items['Minority Interest']
            income_analysis.append(f"  • 少数股东损益: {_format_financial_value(minority)}")
        
        # 4. 每股指标 - 基于实际可用数据
        income_analysis.append("\n📊 **每股指标**")
        
        if 'Basic EPS' in key_items:
            basic_eps = key_items['Basic EPS']
            income_analysis.append(f"  • 基本每股收益: {basic_eps:.4f}元")
        
        if 'Diluted EPS' in key_items:
            diluted_eps = key_items['Diluted EPS']
            income_analysis.append(f"  • 稀释每股收益: {diluted_eps:.4f}元")
        
        if 'Basic Shares' in key_items:
            basic_shares = key_items['Basic Shares']
            income_analysis.append(f"  • 基本加权平均股数: {_format_financial_value(basic_shares)}股")
        
        if 'Diluted Shares' in key_items:
            diluted_shares = key_items['Diluted Shares']
            income_analysis.append(f"  • 稀释加权平均股数: {_format_financial_value(diluted_shares)}股")
        
        if 'DPS Class A' in key_items:
            dps_a = key_items['DPS Class A']
            income_analysis.append(f"  • A类普通股每股股利: {dps_a:.4f}元")
        
        if 'DPS Class B' in key_items:
            dps_b = key_items['DPS Class B']
            income_analysis.append(f"  • B类普通股每股股利: {dps_b:.4f}元")
        
        # 5. 同比分析（如果有多期数据）
        if len(sorted_dates) >= 2:
            income_analysis.append("\n📊 **同比变化分析**")
            
            prev_date = sorted_dates[1]
            prev_data = reports_by_date[prev_date]
            prev_combined = {}
            for statement_type, items in prev_data.items():
                prev_combined.update(items)
            prev_key_items = _extract_key_financial_items(prev_combined)
            
            # 收入增长分析
            if 'Total Revenue' in key_items and 'Total Revenue' in prev_key_items and prev_key_items['Total Revenue'] != 0:
                revenue_growth = ((key_items['Total Revenue'] - prev_key_items['Total Revenue']) / prev_key_items['Total Revenue']) * 100
                income_analysis.append(f"  • 总收入同比增长: {revenue_growth:+.2f}%")
            
            # 利润增长分析
            if 'Net Income' in key_items and 'Net Income' in prev_key_items and prev_key_items['Net Income'] != 0:
                profit_growth = ((key_items['Net Income'] - prev_key_items['Net Income']) / prev_key_items['Net Income']) * 100
                income_analysis.append(f"  • 净利润同比增长: {profit_growth:+.2f}%")
            
            # 毛利率变化
            if ('Gross Profit' in key_items and 'Total Revenue' in key_items and 
                'Gross Profit' in prev_key_items and 'Total Revenue' in prev_key_items and 
                key_items['Total Revenue'] != 0 and prev_key_items['Total Revenue'] != 0):
                current_gross_margin = (key_items['Gross Profit'] / key_items['Total Revenue']) * 100
                prev_gross_margin = (prev_key_items['Gross Profit'] / prev_key_items['Total Revenue']) * 100
                margin_change = current_gross_margin - prev_gross_margin
                income_analysis.append(f"  • 毛利率变化: {margin_change:+.2f}个百分点")
            
            # 净利率变化
            if ('Net Income' in key_items and 'Total Revenue' in key_items and 
                'Net Income' in prev_key_items and 'Total Revenue' in prev_key_items and 
                key_items['Total Revenue'] != 0 and prev_key_items['Total Revenue'] != 0):
                current_net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
                prev_net_margin = (prev_key_items['Net Income'] / prev_key_items['Total Revenue']) * 100
                net_margin_change = current_net_margin - prev_net_margin
                income_analysis.append(f"  • 净利率变化: {net_margin_change:+.2f}个百分点")
    
    except Exception as e:
        income_analysis.append(f"  ❌ 利润表分析异常: {str(e)}")
    
    return income_analysis


def _calculate_financial_ratios(reports_by_date: dict, sorted_dates: list) -> list:
    """计算财务比率"""
    ratios_output = []
    
    if len(sorted_dates) < 1:
        return ratios_output
    
    try:
        # 获取最新期数据
        latest_date = sorted_dates[0]
        latest_data = reports_by_date[latest_date]
        
        # 合并所有报表类型的数据
        combined_data = {}
        for statement_type, items in latest_data.items():
            combined_data.update(items)
        
        key_items = _extract_key_financial_items(combined_data)
        
        # 1. 盈利能力比率 - 基于损益表数据
        ratios_output.append("\n💰 **盈利能力分析**")
        
        # 净利率
        if 'Total Revenue' in key_items and 'Net Income' in key_items and key_items['Total Revenue'] != 0:
            net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 净利率: {net_margin:.2f}%")
        
        # 税前利润率
        if 'Total Revenue' in key_items and 'Net Income Before Taxes' in key_items and key_items['Total Revenue'] != 0:
            pretax_margin = (key_items['Net Income Before Taxes'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 税前利润率: {pretax_margin:.2f}%")
        
        # 研发费用率
        if 'Total Revenue' in key_items and 'R&D Expenses' in key_items and key_items['Total Revenue'] != 0:
            rd_ratio = (key_items['R&D Expenses'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 研发费用率: {rd_ratio:.2f}%")
        
        # 员工薪酬占比
        if 'Total Revenue' in key_items and 'Employee Compensation' in key_items and key_items['Total Revenue'] != 0:
            emp_ratio = (key_items['Employee Compensation'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 员工薪酬占收入比: {emp_ratio:.2f}%")
        
        # 税负率
        if 'Net Income Before Taxes' in key_items and 'Tax Expense' in key_items and key_items['Net Income Before Taxes'] != 0:
            tax_rate = (key_items['Tax Expense'] / key_items['Net Income Before Taxes']) * 100
            ratios_output.append(f"  • 实际税负率: {tax_rate:.2f}%")
        
        # 2. 费用结构分析 - 基于损益表数据
        ratios_output.append("\n📊 **费用结构分析**")
        
        # 利息费用分析
        if 'Interest Expense' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
            interest_ratio = (key_items['Interest Expense'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 利息费用占收入比: {interest_ratio:.2f}%")
        
        # 总运营费用分析
        if 'Total Operating Expense' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
            opex_ratio = (key_items['Total Operating Expense'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 总运营费用率: {opex_ratio:.2f}%")
        
        # 费用效率分析
        total_expenses = 0
        expense_count = 0
        
        if 'R&D Expenses' in key_items:
            total_expenses += key_items['R&D Expenses']
            expense_count += 1
        if 'Employee Compensation' in key_items:
            total_expenses += key_items['Employee Compensation']
            expense_count += 1
        if 'SGA Expenses' in key_items:
            total_expenses += key_items['SGA Expenses']
            expense_count += 1
        
        if total_expenses > 0 and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
            total_expense_ratio = (total_expenses / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 主要费用合计占收入比: {total_expense_ratio:.2f}%")
        
        # 3. 每股指标分析 - 基于损益表数据
        ratios_output.append("\n📈 **每股指标分析**")
        
        # 基本每股收益
        if 'Basic EPS' in key_items:
            ratios_output.append(f"  • 基本每股收益: {key_items['Basic EPS']:.4f}元")
        
        # 稀释每股收益
        if 'Diluted EPS' in key_items:
            ratios_output.append(f"  • 稀释每股收益: {key_items['Diluted EPS']:.4f}元")
        
        # 每股股利分析
        if 'DPS Class A' in key_items and 'DPS Class B' in key_items:
            total_dps = key_items['DPS Class A'] + key_items['DPS Class B']
            ratios_output.append(f"  • 每股股利合计: {total_dps:.4f}元")
        
        # 股利支付率
        if 'DPS Class A' in key_items and 'Basic EPS' in key_items and key_items['Basic EPS'] != 0:
            payout_ratio = (key_items['DPS Class A'] / key_items['Basic EPS']) * 100
            ratios_output.append(f"  • A类股股利支付率: {payout_ratio:.2f}%")
        
        # 股本稀释度
        if 'Basic Shares' in key_items and 'Diluted Shares' in key_items and key_items['Basic Shares'] != 0:
            dilution_rate = ((key_items['Diluted Shares'] - key_items['Basic Shares']) / key_items['Basic Shares']) * 100
            ratios_output.append(f"  • 股本稀释度: {dilution_rate:.2f}%")
        
        # 4. 成长能力分析（需要多期数据）
        if len(sorted_dates) >= 2:
            ratios_output.append("\n📈 **成长能力分析**")
            
            # 获取上期数据
            prev_date = sorted_dates[1]
            prev_data = reports_by_date[prev_date]
            prev_combined = {}
            for statement_type, items in prev_data.items():
                prev_combined.update(items)
            prev_key_items = _extract_key_financial_items(prev_combined)
            
            # 营业收入增长率
            if 'Total Revenue' in key_items and 'Total Revenue' in prev_key_items and prev_key_items['Total Revenue'] != 0:
                revenue_growth = ((key_items['Total Revenue'] - prev_key_items['Total Revenue']) / prev_key_items['Total Revenue']) * 100
                ratios_output.append(f"  • 营业收入增长率: {revenue_growth:.2f}%")
            
            # 净利润增长率
            if 'Net Income' in key_items and 'Net Income' in prev_key_items and prev_key_items['Net Income'] != 0:
                profit_growth = ((key_items['Net Income'] - prev_key_items['Net Income']) / prev_key_items['Net Income']) * 100
                ratios_output.append(f"  • 净利润增长率: {profit_growth:.2f}%")
            
            # 总资产增长率
            if 'Total Assets' in key_items and 'Total Assets' in prev_key_items and prev_key_items['Total Assets'] != 0:
                asset_growth = ((key_items['Total Assets'] - prev_key_items['Total Assets']) / prev_key_items['Total Assets']) * 100
                ratios_output.append(f"  • 总资产增长率: {asset_growth:.2f}%")
            
            # 股东权益增长率
            if 'Total Equity' in key_items and 'Total Equity' in prev_key_items and prev_key_items['Total Equity'] != 0:
                equity_growth = ((key_items['Total Equity'] - prev_key_items['Total Equity']) / prev_key_items['Total Equity']) * 100
                ratios_output.append(f"  • 股东权益增长率: {equity_growth:.2f}%")
        
        # 5. 收入质量分析 - 基于损益表数据
        ratios_output.append("\n💎 **收入质量分析**")
        
        # 收入构成分析
        if 'Vehicle Sales' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
            vehicle_ratio = (key_items['Vehicle Sales'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 汽车销售收入占比: {vehicle_ratio:.2f}%")
        
        if 'Other Revenue' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
            other_ratio = (key_items['Other Revenue'] / key_items['Total Revenue']) * 100
            ratios_output.append(f"  • 其他收入占比: {other_ratio:.2f}%")
        
        # 利润质量分析
        if 'Net Income' in key_items and 'Minority Interest' in key_items:
            parent_income = key_items['Net Income'] - key_items['Minority Interest']
            if key_items['Net Income'] != 0:
                parent_ratio = (parent_income / key_items['Net Income']) * 100
                ratios_output.append(f"  • 归属母公司净利润占比: {parent_ratio:.2f}%")
        
        # 税负合理性分析
        if 'Tax Expense' in key_items and 'Net Income Before Taxes' in key_items:
            if key_items['Net Income Before Taxes'] > 0:
                effective_tax_rate = (key_items['Tax Expense'] / key_items['Net Income Before Taxes']) * 100
                ratios_output.append(f"  • 有效税率: {effective_tax_rate:.2f}%")
            else:
                ratios_output.append(f"  • 税前亏损，实际税负: {_format_financial_value(key_items['Tax Expense'])}")
        
    except Exception as e:
        ratios_output.append(f"  ❌ 财务比率计算异常: {str(e)}")
    
    return ratios_output


def _analyze_financial_trends(reports_by_date: dict, sorted_dates: list) -> list:
    """详细的财务趋势分析和多期数据对比"""
    trend_output = []
    
    if len(sorted_dates) < 2:
        trend_output.append("  ℹ️ 需要至少两期数据进行趋势分析")
        return trend_output
    
    try:
        trend_output.append("\n📈 **财务趋势分析**")
        
        # 分析最近3-4期的数据趋势
        periods_to_analyze = min(4, len(sorted_dates))
        
        # 收集各期关键指标
        period_data = []
        for i in range(periods_to_analyze):
            date = sorted_dates[i]
            combined_data = {}
            for statement_type, items in reports_by_date[date].items():
                combined_data.update(items)
            key_items = _extract_key_financial_items(combined_data)
            period_data.append({
                'date': date,
                'data': key_items
            })
        
        # 1. 收入趋势分析
        trend_output.append("\n💰 **收入趋势**")
        revenue_trend = []
        for period in period_data:
            if 'Total Revenue' in period['data']:
                revenue_trend.append({
                    'date': period['date'],
                    'value': period['data']['Total Revenue']
                })
        
        if len(revenue_trend) >= 2:
            # 计算各期同比增长率
            for i in range(len(revenue_trend) - 1):
                current = revenue_trend[i]
                previous = revenue_trend[i + 1]
                if previous['value'] != 0:
                    growth_rate = ((current['value'] - previous['value']) / previous['value']) * 100
                    trend_direction = "📈" if growth_rate > 0 else "📉" if growth_rate < 0 else "➡️"
                    trend_output.append(f"  {trend_direction} {current['date']}: {_format_financial_value(current['value'])} (同比{growth_rate:+.1f}%)")
        
        # 2. 利润趋势分析
        trend_output.append("\n💎 **利润趋势**")
        profit_trend = []
        for period in period_data:
            if 'Net Income' in period['data']:
                profit_trend.append({
                    'date': period['date'],
                    'value': period['data']['Net Income']
                })
        
        if len(profit_trend) >= 2:
            for i in range(len(profit_trend) - 1):
                current = profit_trend[i]
                previous = profit_trend[i + 1]
                if previous['value'] != 0:
                    growth_rate = ((current['value'] - previous['value']) / previous['value']) * 100
                    trend_direction = "📈" if growth_rate > 0 else "📉" if growth_rate < 0 else "➡️"
                    trend_output.append(f"  {trend_direction} {current['date']}: {_format_financial_value(current['value'])} (同比{growth_rate:+.1f}%)")
        
        # 3. 资产规模趋势
        trend_output.append("\n🏢 **资产规模趋势**")
        asset_trend = []
        for period in period_data:
            if 'Total Assets' in period['data']:
                asset_trend.append({
                    'date': period['date'],
                    'value': period['data']['Total Assets']
                })
        
        if len(asset_trend) >= 2:
            for i in range(len(asset_trend) - 1):
                current = asset_trend[i]
                previous = asset_trend[i + 1]
                if previous['value'] != 0:
                    growth_rate = ((current['value'] - previous['value']) / previous['value']) * 100
                    trend_direction = "📈" if growth_rate > 0 else "📉" if growth_rate < 0 else "➡️"
                    trend_output.append(f"  {trend_direction} {current['date']}: {_format_financial_value(current['value'])} (同比{growth_rate:+.1f}%)")
        
        # 4. 现金流趋势
        trend_output.append("\n💧 **现金流趋势**")
        cashflow_trend = []
        for period in period_data:
            if 'Operating Cash Flow' in period['data']:
                cashflow_trend.append({
                    'date': period['date'],
                    'value': period['data']['Operating Cash Flow']
                })
        
        if len(cashflow_trend) >= 2:
            for i in range(len(cashflow_trend) - 1):
                current = cashflow_trend[i]
                previous = cashflow_trend[i + 1]
                if previous['value'] != 0:
                    growth_rate = ((current['value'] - previous['value']) / previous['value']) * 100
                    trend_direction = "📈" if growth_rate > 0 else "📉" if growth_rate < 0 else "➡️"
                    trend_output.append(f"  {trend_direction} {current['date']}: {_format_financial_value(current['value'])} (同比{growth_rate:+.1f}%)")
        
        # 5. 关键比率趋势
        trend_output.append("\n📊 **关键比率趋势**")
        
        # 净利率趋势
        margin_trend = []
        for period in period_data:
            if 'Total Revenue' in period['data'] and 'Net Income' in period['data']:
                revenue = period['data']['Total Revenue']
                profit = period['data']['Net Income']
                if revenue != 0:
                    margin = (profit / revenue) * 100
                    margin_trend.append({
                        'date': period['date'],
                        'margin': margin
                    })
        
        if len(margin_trend) >= 2:
            trend_output.append("  📈 净利率变化:")
            for i, period in enumerate(margin_trend):
                if i < len(margin_trend) - 1:
                    next_period = margin_trend[i + 1]
                    change = period['margin'] - next_period['margin']
                    trend_direction = "↗️" if change > 0 else "↘️" if change < 0 else "➡️"
                    trend_output.append(f"    {trend_direction} {period['date']}: {period['margin']:.2f}% (变化{change:+.2f}pp)")
        
        # 6. 趋势总结
        trend_output.append("\n🎯 **趋势总结**")
        
        # 基于多个指标给出综合趋势判断
        positive_trends = 0
        negative_trends = 0
        
        # 检查收入趋势
        if len(revenue_trend) >= 2 and revenue_trend[0]['value'] > revenue_trend[1]['value']:
            positive_trends += 1
        elif len(revenue_trend) >= 2 and revenue_trend[0]['value'] < revenue_trend[1]['value']:
            negative_trends += 1
        
        # 检查利润趋势
        if len(profit_trend) >= 2 and profit_trend[0]['value'] > profit_trend[1]['value']:
            positive_trends += 1
        elif len(profit_trend) >= 2 and profit_trend[0]['value'] < profit_trend[1]['value']:
            negative_trends += 1
        
        # 检查现金流趋势
        if len(cashflow_trend) >= 2 and cashflow_trend[0]['value'] > cashflow_trend[1]['value']:
            positive_trends += 1
        elif len(cashflow_trend) >= 2 and cashflow_trend[0]['value'] < cashflow_trend[1]['value']:
            negative_trends += 1
        
        if positive_trends > negative_trends:
            trend_output.append("  🟢 整体趋势: 向好，多项关键指标呈现增长态势")
        elif negative_trends > positive_trends:
            trend_output.append("  🔴 整体趋势: 下滑，需要关注经营状况变化")
        else:
            trend_output.append("  🟡 整体趋势: 平稳，各项指标变化不大")
        
    except Exception as e:
        trend_output.append(f"  ❌ 趋势分析异常: {str(e)}")
    
    return trend_output


def _assess_financial_risks(reports_by_date: dict, sorted_dates: list) -> list:
    """评估财务风险"""
    risk_output = []
    
    if len(sorted_dates) < 1:
        return risk_output
    
    try:
        # 获取最新期数据
        latest_date = sorted_dates[0]
        latest_data = reports_by_date[latest_date]
        
        # 合并所有报表类型的数据
        combined_data = {}
        for statement_type, items in latest_data.items():
            combined_data.update(items)
        
        key_items = _extract_key_financial_items(combined_data)
        
        # 1. 流动性风险评估
        risk_output.append("\n💧 **流动性风险评估**")
        
        if 'Current Assets' in key_items and 'Current Liabilities' in key_items:
            if key_items['Current Liabilities'] != 0:
                current_ratio = key_items['Current Assets'] / key_items['Current Liabilities']
                if current_ratio < 1.0:
                    risk_output.append(f"  🔴 高风险: 流动比率{current_ratio:.2f} < 1.0，短期偿债能力不足")
                elif current_ratio < 1.5:
                    risk_output.append(f"  🟡 中风险: 流动比率{current_ratio:.2f}，流动性偏紧")
                else:
                    risk_output.append(f"  🟢 低风险: 流动比率{current_ratio:.2f}，流动性良好")
        
        # 现金流风险
        if 'Operating Cash Flow' in key_items:
            if key_items['Operating Cash Flow'] < 0:
                risk_output.append(f"  🔴 高风险: 经营现金流为负，现金流紧张")
            elif 'Net Income' in key_items and key_items['Net Income'] > 0:
                cash_quality = key_items['Operating Cash Flow'] / key_items['Net Income']
                if cash_quality < 0.8:
                    risk_output.append(f"  🟡 中风险: 现金流质量{cash_quality:.2f}，盈利质量有待提升")
                else:
                    risk_output.append(f"  🟢 低风险: 现金流质量{cash_quality:.2f}，盈利质量良好")
        
        # 2. 偿债风险评估
        risk_output.append("\n🏦 **偿债风险评估**")
        
        if 'Total Liabilities' in key_items and 'Total Assets' in key_items and key_items['Total Assets'] != 0:
            debt_ratio = (key_items['Total Liabilities'] / key_items['Total Assets']) * 100
            if debt_ratio > 70:
                risk_output.append(f"  🔴 高风险: 资产负债率{debt_ratio:.1f}% > 70%，债务负担重")
            elif debt_ratio > 50:
                risk_output.append(f"  🟡 中风险: 资产负债率{debt_ratio:.1f}%，债务水平偏高")
            else:
                risk_output.append(f"  🟢 低风险: 资产负债率{debt_ratio:.1f}%，债务水平合理")
        
        # 3. 经营风险评估
        risk_output.append("\n📊 **经营风险评估**")
        
        # 盈利能力风险
        if 'Total Revenue' in key_items and 'Net Income' in key_items and key_items['Total Revenue'] != 0:
            net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
            if net_margin < 0:
                risk_output.append(f"  🔴 高风险: 净利率{net_margin:.2f}%，公司亏损")
            elif net_margin < 5:
                risk_output.append(f"  🟡 中风险: 净利率{net_margin:.2f}%，盈利能力偏弱")
            else:
                risk_output.append(f"  🟢 低风险: 净利率{net_margin:.2f}%，盈利能力良好")
        
        # 成长性风险（需要多期数据）
        if len(sorted_dates) >= 2:
            prev_date = sorted_dates[1]
            prev_data = reports_by_date[prev_date]
            prev_combined = {}
            for statement_type, items in prev_data.items():
                prev_combined.update(items)
            prev_key_items = _extract_key_financial_items(prev_combined)
            
            if 'Total Revenue' in key_items and 'Total Revenue' in prev_key_items and prev_key_items['Total Revenue'] != 0:
                revenue_growth = ((key_items['Total Revenue'] - prev_key_items['Total Revenue']) / prev_key_items['Total Revenue']) * 100
                if revenue_growth < -10:
                    risk_output.append(f"  🔴 高风险: 营业收入下降{abs(revenue_growth):.1f}%，业务萎缩")
                elif revenue_growth < 0:
                    risk_output.append(f"  🟡 中风险: 营业收入下降{abs(revenue_growth):.1f}%，增长乏力")
                else:
                    risk_output.append(f"  🟢 低风险: 营业收入增长{revenue_growth:.1f}%，业务发展良好")
        
    except Exception as e:
        risk_output.append(f"  ❌ 风险评估异常: {str(e)}")
    
    return risk_output


def _analyze_financial_prospects(reports_by_date: dict, sorted_dates: list) -> list:
    """分析财务前景"""
    prospect_output = []
    
    if len(sorted_dates) < 2:
        prospect_output.append("  ℹ️ 需要至少两期数据进行前景分析")
        return prospect_output
    
    try:
        # 获取最新两期数据
        latest_date = sorted_dates[0]
        prev_date = sorted_dates[1]
        
        latest_data = reports_by_date[latest_date]
        prev_data = reports_by_date[prev_date]
        
        # 合并数据
        latest_combined = {}
        prev_combined = {}
        
        for statement_type, items in latest_data.items():
            latest_combined.update(items)
        for statement_type, items in prev_data.items():
            prev_combined.update(items)
        
        latest_key = _extract_key_financial_items(latest_combined)
        prev_key = _extract_key_financial_items(prev_combined)
        
        # 1. 收入增长趋势分析
        prospect_output.append("\n📈 **收入增长趋势**")
        
        if 'Total Revenue' in latest_key and 'Total Revenue' in prev_key and prev_key['Total Revenue'] != 0:
            revenue_growth = ((latest_key['Total Revenue'] - prev_key['Total Revenue']) / prev_key['Total Revenue']) * 100
            
            if revenue_growth > 20:
                prospect_output.append(f"  🚀 优秀: 营业收入增长{revenue_growth:.1f}%，高速增长")
                prospect_output.append(f"    预期: 如果保持当前增长势头，未来业绩表现值得期待")
            elif revenue_growth > 10:
                prospect_output.append(f"  📈 良好: 营业收入增长{revenue_growth:.1f}%，稳健增长")
                prospect_output.append(f"    预期: 业务发展稳定，具备持续增长潜力")
            elif revenue_growth > 0:
                prospect_output.append(f"  📊 一般: 营业收入增长{revenue_growth:.1f}%，温和增长")
                prospect_output.append(f"    预期: 增长动力有限，需关注业务拓展情况")
            else:
                prospect_output.append(f"  📉 担忧: 营业收入下降{abs(revenue_growth):.1f}%，业务收缩")
                prospect_output.append(f"    预期: 需要关注业务转型和市场竞争力恢复")
        
        # 2. 盈利能力变化分析
        prospect_output.append("\n💰 **盈利能力变化**")
        
        if 'Net Income' in latest_key and 'Net Income' in prev_key and prev_key['Net Income'] != 0:
            profit_growth = ((latest_key['Net Income'] - prev_key['Net Income']) / prev_key['Net Income']) * 100
            
            # 计算净利率变化
            if 'Total Revenue' in latest_key and 'Total Revenue' in prev_key:
                latest_margin = (latest_key['Net Income'] / latest_key['Total Revenue']) * 100 if latest_key['Total Revenue'] != 0 else 0
                prev_margin = (prev_key['Net Income'] / prev_key['Total Revenue']) * 100 if prev_key['Total Revenue'] != 0 else 0
                margin_change = latest_margin - prev_margin
                
                if profit_growth > 15 and margin_change > 0:
                    prospect_output.append(f"  🌟 优秀: 净利润增长{profit_growth:.1f}%，净利率提升{margin_change:.1f}个百分点")
                    prospect_output.append(f"    预期: 盈利能力显著改善，投资价值提升")
                elif profit_growth > 0:
                    prospect_output.append(f"  📈 良好: 净利润增长{profit_growth:.1f}%，盈利能力稳定")
                    prospect_output.append(f"    预期: 盈利水平保持增长，经营效率良好")
                else:
                    prospect_output.append(f"  📉 担忧: 净利润下降{abs(profit_growth):.1f}%，盈利承压")
                    prospect_output.append(f"    预期: 需要关注成本控制和经营效率改善")
        
        # 3. 现金流健康度分析
        prospect_output.append("\n💧 **现金流健康度**")
        
        if 'Operating Cash Flow' in latest_key and 'Operating Cash Flow' in prev_key:
            if latest_key['Operating Cash Flow'] > 0 and prev_key['Operating Cash Flow'] > 0:
                cashflow_growth = ((latest_key['Operating Cash Flow'] - prev_key['Operating Cash Flow']) / prev_key['Operating Cash Flow']) * 100
                
                if cashflow_growth > 10:
                    prospect_output.append(f"  💪 优秀: 经营现金流增长{cashflow_growth:.1f}%，现金创造能力强")
                    prospect_output.append(f"    预期: 现金流充裕，支撑业务扩张和分红能力")
                elif cashflow_growth > 0:
                    prospect_output.append(f"  👍 良好: 经营现金流增长{cashflow_growth:.1f}%，现金流稳定")
                    prospect_output.append(f"    预期: 现金流状况良好，经营质量可靠")
                else:
                    prospect_output.append(f"  ⚠️ 关注: 经营现金流下降{abs(cashflow_growth):.1f}%，需要关注")
                    prospect_output.append(f"    预期: 现金流压力增加，需要改善回款和库存管理")
            elif latest_key['Operating Cash Flow'] > 0 and prev_key['Operating Cash Flow'] <= 0:
                prospect_output.append(f"  🔄 改善: 经营现金流由负转正，现金流状况改善")
                prospect_output.append(f"    预期: 经营质量提升，现金流健康度恢复")
            elif latest_key['Operating Cash Flow'] <= 0:
                prospect_output.append(f"  🔴 警告: 经营现金流为负，现金流紧张")
                prospect_output.append(f"    预期: 需要密切关注资金链安全和经营改善")
        
        # 4. 综合前景判断
        prospect_output.append("\n🔮 **综合前景判断**")
        
        # 基于多个指标综合评分
        score = 0
        factors = []
        
        # 收入增长评分
        if 'Total Revenue' in latest_key and 'Total Revenue' in prev_key and prev_key['Total Revenue'] != 0:
            revenue_growth = ((latest_key['Total Revenue'] - prev_key['Total Revenue']) / prev_key['Total Revenue']) * 100
            if revenue_growth > 15:
                score += 3
                factors.append("收入高增长")
            elif revenue_growth > 5:
                score += 2
                factors.append("收入稳增长")
            elif revenue_growth > 0:
                score += 1
                factors.append("收入微增长")
            else:
                factors.append("收入下降")
        
        # 盈利能力评分
        if 'Net Income' in latest_key and 'Net Income' in prev_key and prev_key['Net Income'] != 0:
            profit_growth = ((latest_key['Net Income'] - prev_key['Net Income']) / prev_key['Net Income']) * 100
            if profit_growth > 20:
                score += 3
                factors.append("利润高增长")
            elif profit_growth > 10:
                score += 2
                factors.append("利润稳增长")
            elif profit_growth > 0:
                score += 1
                factors.append("利润微增长")
            else:
                factors.append("利润下降")
        
        # 现金流评分
        if 'Operating Cash Flow' in latest_key:
            if latest_key['Operating Cash Flow'] > 0:
                if 'Net Income' in latest_key and latest_key['Net Income'] > 0:
                    cash_quality = latest_key['Operating Cash Flow'] / latest_key['Net Income']
                    if cash_quality > 1.2:
                        score += 3
                        factors.append("现金流优质")
                    elif cash_quality > 0.8:
                        score += 2
                        factors.append("现金流良好")
                    else:
                        score += 1
                        factors.append("现金流一般")
                else:
                    score += 1
                    factors.append("现金流为正")
            else:
                factors.append("现金流为负")
        
        # 综合评价
        if score >= 7:
            prospect_output.append(f"  🌟 前景优秀 (评分: {score}/9)")
            prospect_output.append(f"    关键因素: {', '.join(factors)}")
            prospect_output.append(f"    投资建议: 公司基本面强劲，具备良好的投资价值")
        elif score >= 4:
            prospect_output.append(f"  👍 前景良好 (评分: {score}/9)")
            prospect_output.append(f"    关键因素: {', '.join(factors)}")
            prospect_output.append(f"    投资建议: 公司发展稳健，可考虑适度配置")
        elif score >= 2:
            prospect_output.append(f"  ⚠️ 前景一般 (评分: {score}/9)")
            prospect_output.append(f"    关键因素: {', '.join(factors)}")
            prospect_output.append(f"    投资建议: 公司表现平平，需要谨慎评估")
        else:
            prospect_output.append(f"  📉 前景担忧 (评分: {score}/9)")
            prospect_output.append(f"    关键因素: {', '.join(factors)}")
            prospect_output.append(f"    投资建议: 公司面临挑战，建议规避风险")
        
    except Exception as e:
        prospect_output.append(f"  ❌ 前景分析异常: {str(e)}")
    
    return prospect_output


def _calculate_financial_health_score(reports_by_date: dict, sorted_dates: list) -> list:
    """计算综合财务健康评分"""
    health_output = []
    
    if len(sorted_dates) < 1:
        return health_output
    
    try:
        # 获取最新期数据
        latest_date = sorted_dates[0]
        latest_data = reports_by_date[latest_date]
        
        # 合并所有报表类型的数据
        combined_data = {}
        for statement_type, items in latest_data.items():
            combined_data.update(items)
        
        key_items = _extract_key_financial_items(combined_data)
        
        # 健康评分系统 (总分100分)
        total_score = 0
        max_score = 100
        score_details = []
        
        # 1. 盈利能力评分 (30分)
        profitability_score = 0
        if 'Total Revenue' in key_items and 'Net Income' in key_items and key_items['Total Revenue'] != 0:
            net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
            if net_margin > 15:
                profitability_score = 30
            elif net_margin > 10:
                profitability_score = 25
            elif net_margin > 5:
                profitability_score = 20
            elif net_margin > 0:
                profitability_score = 15
            else:
                profitability_score = 0
            
            score_details.append(f"盈利能力: {profitability_score}/30 (净利率{net_margin:.1f}%)")
        else:
            score_details.append("盈利能力: 0/30 (数据不足)")
        
        total_score += profitability_score
        
        # 2. 偿债能力评分 (25分) - 基于损益表数据的替代评估
        solvency_score = 0
        if 'Total Liabilities' in key_items and 'Total Assets' in key_items and key_items['Total Assets'] != 0:
            debt_ratio = (key_items['Total Liabilities'] / key_items['Total Assets']) * 100
            if debt_ratio < 30:
                solvency_score = 25
            elif debt_ratio < 50:
                solvency_score = 20
            elif debt_ratio < 70:
                solvency_score = 15
            else:
                solvency_score = 5
            
            score_details.append(f"偿债能力: {solvency_score}/25 (资产负债率{debt_ratio:.1f}%)")
        else:
            # 基于盈利能力的替代评估
            if 'Net Income' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
                if net_margin > 15:  # 高盈利能力通常意味着较强的偿债能力
                    solvency_score = 15
                elif net_margin > 10:
                    solvency_score = 12
                elif net_margin > 5:
                    solvency_score = 8
                elif net_margin > 0:
                    solvency_score = 5
                else:
                    solvency_score = 0
                
                score_details.append(f"偿债能力: {solvency_score}/25 (基于净利率{net_margin:.1f}%评估，缺少资产负债表数据)")
            else:
                score_details.append("偿债能力: 0/25 (缺少资产负债表数据，无法评估)")
        
        total_score += solvency_score
        
        # 3. 流动性评分 (20分) - 基于损益表数据的替代评估
        liquidity_score = 0
        if 'Current Assets' in key_items and 'Current Liabilities' in key_items and key_items['Current Liabilities'] != 0:
            current_ratio = key_items['Current Assets'] / key_items['Current Liabilities']
            if current_ratio > 2.0:
                liquidity_score = 20
            elif current_ratio > 1.5:
                liquidity_score = 16
            elif current_ratio > 1.0:
                liquidity_score = 12
            else:
                liquidity_score = 5
            
            score_details.append(f"流动性: {liquidity_score}/20 (流动比率{current_ratio:.2f})")
        else:
            # 基于营业收入规模和盈利稳定性的替代评估
            if 'Total Revenue' in key_items and 'Net Income' in key_items:
                revenue_billion = key_items['Total Revenue'] / 1000000000  # 转换为十亿单位
                if key_items['Net Income'] > 0 and revenue_billion > 10:  # 大规模盈利企业通常流动性较好
                    liquidity_score = 12
                elif key_items['Net Income'] > 0 and revenue_billion > 5:
                    liquidity_score = 10
                elif key_items['Net Income'] > 0 and revenue_billion > 1:
                    liquidity_score = 8
                elif key_items['Net Income'] > 0:
                    liquidity_score = 6
                else:
                    liquidity_score = 2
                
                score_details.append(f"流动性: {liquidity_score}/20 (基于营收规模{revenue_billion:.1f}十亿评估，缺少资产负债表数据)")
            else:
                score_details.append("流动性: 0/20 (缺少资产负债表数据，无法评估)")
        
        total_score += liquidity_score
        
        # 4. 现金流质量评分 (15分) - 基于损益表数据的替代评估
        cashflow_score = 0
        if 'Operating Cash Flow' in key_items and 'Net Income' in key_items:
            if key_items['Operating Cash Flow'] > 0 and key_items['Net Income'] > 0:
                cash_quality = key_items['Operating Cash Flow'] / key_items['Net Income']
                if cash_quality > 1.2:
                    cashflow_score = 15
                elif cash_quality > 1.0:
                    cashflow_score = 12
                elif cash_quality > 0.8:
                    cashflow_score = 10
                else:
                    cashflow_score = 5
                
                score_details.append(f"现金流质量: {cashflow_score}/15 (现金流/净利润={cash_quality:.2f})")
            elif key_items['Operating Cash Flow'] > 0:
                cashflow_score = 8
                score_details.append(f"现金流质量: {cashflow_score}/15 (经营现金流为正)")
            else:
                score_details.append("现金流质量: 0/15 (经营现金流为负)")
        else:
            # 基于盈利质量和业务模式的替代评估
            if 'Net Income' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
                # 高净利率通常意味着较好的现金转换能力
                if net_margin > 15 and key_items['Net Income'] > 0:
                    cashflow_score = 10
                elif net_margin > 10 and key_items['Net Income'] > 0:
                    cashflow_score = 8
                elif net_margin > 5 and key_items['Net Income'] > 0:
                    cashflow_score = 6
                elif key_items['Net Income'] > 0:
                    cashflow_score = 4
                else:
                    cashflow_score = 0
                
                score_details.append(f"现金流质量: {cashflow_score}/15 (基于净利率{net_margin:.1f}%评估，缺少现金流量表数据)")
            else:
                score_details.append("现金流质量: 0/15 (缺少现金流量表数据，无法评估)")
        
        total_score += cashflow_score
        
        # 5. 成长性评分 (10分) - 需要多期数据
        growth_score = 0
        if len(sorted_dates) >= 2:
            prev_date = sorted_dates[1]
            prev_data = reports_by_date[prev_date]
            prev_combined = {}
            for statement_type, items in prev_data.items():
                prev_combined.update(items)
            prev_key_items = _extract_key_financial_items(prev_combined)
            
            if 'Total Revenue' in key_items and 'Total Revenue' in prev_key_items and prev_key_items['Total Revenue'] != 0:
                revenue_growth = ((key_items['Total Revenue'] - prev_key_items['Total Revenue']) / prev_key_items['Total Revenue']) * 100
                if revenue_growth > 20:
                    growth_score = 10
                elif revenue_growth > 10:
                    growth_score = 8
                elif revenue_growth > 5:
                    growth_score = 6
                elif revenue_growth > 0:
                    growth_score = 4
                else:
                    growth_score = 0
                
                score_details.append(f"成长性: {growth_score}/10 (收入增长{revenue_growth:.1f}%)")
            else:
                score_details.append("成长性: 0/10 (数据不足)")
        else:
            score_details.append("成长性: 0/10 (需要多期数据)")
        
        total_score += growth_score
        
        # 输出健康评分结果
        health_output.append(f"\n🏥 **综合健康评分: {total_score}/{max_score}分**")
        
        # 评级判断
        if total_score >= 80:
            rating = "AAA (优秀)"
            emoji = "🌟"
            description = "财务状况非常健康，各项指标表现优异"
        elif total_score >= 70:
            rating = "AA (良好)"
            emoji = "👍"
            description = "财务状况良好，大部分指标表现稳健"
        elif total_score >= 60:
            rating = "A (一般)"
            emoji = "📊"
            description = "财务状况一般，部分指标需要改善"
        elif total_score >= 40:
            rating = "B (关注)"
            emoji = "⚠️"
            description = "财务状况需要关注，存在一定风险"
        else:
            rating = "C (警告)"
            emoji = "🔴"
            description = "财务状况较差，存在较大风险"
        
        health_output.append(f"\n{emoji} **财务健康等级: {rating}**")
        health_output.append(f"  📝 评价: {description}")
        
        health_output.append("\n📋 **评分明细:**")
        for detail in score_details:
            health_output.append(f"  • {detail}")
        
    except Exception as e:
        health_output.append(f"  ❌ 健康评分计算异常: {str(e)}")
    
    return health_output


def _generate_investment_advice(reports_by_date: dict, sorted_dates: list) -> list:
    """生成投资建议"""
    advice_output = []
    
    if len(sorted_dates) < 1:
        return advice_output
    
    try:
        # 获取最新期数据
        latest_date = sorted_dates[0]
        latest_data = reports_by_date[latest_date]
        
        # 合并所有报表类型的数据
        combined_data = {}
        for statement_type, items in latest_data.items():
            combined_data.update(items)
        
        key_items = _extract_key_financial_items(combined_data)
        
        # 投资建议评分系统
        investment_score = 0
        positive_factors = []
        negative_factors = []
        neutral_factors = []
        
        # 1. 盈利能力分析
        if 'Total Revenue' in key_items and 'Net Income' in key_items and key_items['Total Revenue'] != 0:
            net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
            if net_margin > 10:
                investment_score += 2
                positive_factors.append(f"净利率{net_margin:.1f}%，盈利能力强")
            elif net_margin > 5:
                investment_score += 1
                neutral_factors.append(f"净利率{net_margin:.1f}%，盈利能力一般")
            elif net_margin > 0:
                neutral_factors.append(f"净利率{net_margin:.1f}%，盈利微薄")
            else:
                investment_score -= 2
                negative_factors.append(f"净利率{net_margin:.1f}%，公司亏损")
        
        # 2. 财务稳健性分析 - 基于损益表数据的替代评估
        if 'Total Liabilities' in key_items and 'Total Assets' in key_items and key_items['Total Assets'] != 0:
            debt_ratio = (key_items['Total Liabilities'] / key_items['Total Assets']) * 100
            if debt_ratio < 40:
                investment_score += 1
                positive_factors.append(f"资产负债率{debt_ratio:.1f}%，财务稳健")
            elif debt_ratio < 60:
                neutral_factors.append(f"资产负债率{debt_ratio:.1f}%，财务结构合理")
            else:
                investment_score -= 1
                negative_factors.append(f"资产负债率{debt_ratio:.1f}%，债务负担重")
        else:
            # 基于盈利能力评估财务稳健性
            if 'Net Income' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
                if net_margin > 15:
                    investment_score += 1
                    positive_factors.append(f"净利率{net_margin:.1f}%，盈利能力强，财务相对稳健")
                elif net_margin > 5:
                    neutral_factors.append(f"净利率{net_margin:.1f}%，盈利能力一般，财务稳健性待评估")
                elif net_margin <= 0:
                    investment_score -= 1
                    negative_factors.append(f"净利率{net_margin:.1f}%，亏损状态，财务稳健性存疑")
        
        # 3. 流动性分析 - 基于损益表数据的替代评估
        if 'Current Assets' in key_items and 'Current Liabilities' in key_items and key_items['Current Liabilities'] != 0:
            current_ratio = key_items['Current Assets'] / key_items['Current Liabilities']
            if current_ratio > 1.5:
                investment_score += 1
                positive_factors.append(f"流动比率{current_ratio:.2f}，流动性充足")
            elif current_ratio > 1.0:
                neutral_factors.append(f"流动比率{current_ratio:.2f}，流动性一般")
            else:
                investment_score -= 1
                negative_factors.append(f"流动比率{current_ratio:.2f}，流动性不足")
        else:
            # 基于营业收入规模和盈利稳定性评估流动性
            if 'Total Revenue' in key_items and 'Net Income' in key_items:
                revenue_billion = key_items['Total Revenue'] / 1000000000
                if key_items['Net Income'] > 0 and revenue_billion > 10:
                    neutral_factors.append(f"营收规模{revenue_billion:.1f}十亿且盈利，流动性预期较好")
                elif key_items['Net Income'] > 0 and revenue_billion > 1:
                    neutral_factors.append(f"营收规模{revenue_billion:.1f}十亿且盈利，流动性预期一般")
                elif key_items['Net Income'] <= 0:
                    negative_factors.append("公司亏损，流动性可能承压")
        
        # 4. 现金流分析 - 基于损益表数据的替代评估
        if 'Operating Cash Flow' in key_items:
            if key_items['Operating Cash Flow'] > 0:
                if 'Net Income' in key_items and key_items['Net Income'] > 0:
                    cash_quality = key_items['Operating Cash Flow'] / key_items['Net Income']
                    if cash_quality > 1.0:
                        investment_score += 2
                        positive_factors.append(f"现金流质量{cash_quality:.2f}，盈利质量高")
                    else:
                        investment_score += 1
                        positive_factors.append(f"经营现金流为正，现金创造能力良好")
                else:
                    investment_score += 1
                    positive_factors.append("经营现金流为正")
            else:
                investment_score -= 1
                negative_factors.append("经营现金流为负，现金流紧张")
        else:
            # 基于盈利质量评估现金流状况
            if 'Net Income' in key_items and 'Total Revenue' in key_items and key_items['Total Revenue'] != 0:
                net_margin = (key_items['Net Income'] / key_items['Total Revenue']) * 100
                if net_margin > 15 and key_items['Net Income'] > 0:
                    positive_factors.append(f"净利率{net_margin:.1f}%，盈利质量较高，现金转换能力预期良好")
                elif net_margin > 5 and key_items['Net Income'] > 0:
                    neutral_factors.append(f"净利率{net_margin:.1f}%，现金转换能力有待观察")
                elif key_items['Net Income'] <= 0:
                    negative_factors.append("公司亏损，现金流状况堪忧")
        
        # 5. 成长性分析（需要多期数据）
        if len(sorted_dates) >= 2:
            prev_date = sorted_dates[1]
            prev_data = reports_by_date[prev_date]
            prev_combined = {}
            for statement_type, items in prev_data.items():
                prev_combined.update(items)
            prev_key_items = _extract_key_financial_items(prev_combined)
            
            if 'Total Revenue' in key_items and 'Total Revenue' in prev_key_items and prev_key_items['Total Revenue'] != 0:
                revenue_growth = ((key_items['Total Revenue'] - prev_key_items['Total Revenue']) / prev_key_items['Total Revenue']) * 100
                if revenue_growth > 15:
                    investment_score += 2
                    positive_factors.append(f"营业收入增长{revenue_growth:.1f}%，高速成长")
                elif revenue_growth > 5:
                    investment_score += 1
                    positive_factors.append(f"营业收入增长{revenue_growth:.1f}%，稳健成长")
                elif revenue_growth > 0:
                    neutral_factors.append(f"营业收入增长{revenue_growth:.1f}%，温和增长")
                else:
                    investment_score -= 1
                    negative_factors.append(f"营业收入下降{abs(revenue_growth):.1f}%，业务萎缩")
        
        # 生成投资建议
        advice_output.append("\n💡 **投资建议分析**")
        
        # 显示关键因素
        if positive_factors:
            advice_output.append("\n✅ **积极因素:**")
            for factor in positive_factors:
                advice_output.append(f"  • {factor}")
        
        if negative_factors:
            advice_output.append("\n❌ **风险因素:**")
            for factor in negative_factors:
                advice_output.append(f"  • {factor}")
        
        if neutral_factors:
            advice_output.append("\n⚪ **中性因素:**")
            for factor in neutral_factors:
                advice_output.append(f"  • {factor}")
        
        # 综合投资建议
        advice_output.append("\n🎯 **综合投资建议:**")
        
        if investment_score >= 5:
            advice_output.append("  🌟 **强烈推荐 (买入)**")
            advice_output.append("    • 公司基本面优秀，财务指标表现突出")
            advice_output.append("    • 具备良好的盈利能力和成长潜力")
            advice_output.append("    • 适合长期投资和价值投资者")
            advice_output.append("    • 建议逢低买入，长期持有")
        elif investment_score >= 2:
            advice_output.append("  👍 **推荐 (买入)**")
            advice_output.append("    • 公司基本面良好，财务状况稳健")
            advice_output.append("    • 具备一定的投资价值")
            advice_output.append("    • 适合稳健型投资者")
            advice_output.append("    • 可考虑适度配置")
        elif investment_score >= 0:
            advice_output.append("  ⚖️ **中性 (持有)**")
            advice_output.append("    • 公司基本面一般，喜忧参半")
            advice_output.append("    • 投资价值有限")
            advice_output.append("    • 建议观望或小仓位试探")
            advice_output.append("    • 需要密切关注后续发展")
        elif investment_score >= -2:
            advice_output.append("  ⚠️ **谨慎 (减持)**")
            advice_output.append("    • 公司存在一定风险因素")
            advice_output.append("    • 财务指标表现不佳")
            advice_output.append("    • 不建议新增投资")
            advice_output.append("    • 持有者可考虑减持")
        else:
            advice_output.append("  🔴 **回避 (卖出)**")
            advice_output.append("    • 公司基本面较差，风险较大")
            advice_output.append("    • 财务状况堪忧")
            advice_output.append("    • 强烈建议回避投资")
            advice_output.append("    • 持有者应考虑及时止损")
        
        # 风险提示
        advice_output.append("\n⚠️ **风险提示:**")
        advice_output.append("  • 以上分析基于历史财务数据，不构成投资建议")
        advice_output.append("  • 投资有风险，决策需谨慎")
        advice_output.append("  • 建议结合行业分析、市场环境等因素综合判断")
        advice_output.append("  • 请根据自身风险承受能力做出投资决策")
        
    except Exception as e:
        advice_output.append(f"  ❌ 投资建议生成异常: {str(e)}")
    
    return advice_output


def _get_chanlun_analysis(code: str, market: str, frequency: str = 'd') -> str:
    """获取缠论分析
    
    Args:
        code: 股票代码
        market: 市场代码
        frequency: 分析周期，默认为'd'（日线）
    """
    try:
        import sys
        import os
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.tools.ai_analyse import AIAnalyse
        
        ai_analyse = AIAnalyse(market)
        chanlun_result = ai_analyse.analyse(code=code, frequency=frequency)
        
        if chanlun_result.get('ok', False):
            analysis = chanlun_result.get('msg', '').strip()
            return analysis if analysis else "缠论分析返回空内容"
        else:
            error_msg = chanlun_result.get('msg', '未知错误')
            return f"缠论分析失败: {error_msg}"
            
    except Exception as e:
        logger.error(f"缠论分析异常: {str(e)}")
        return f"缠论分析异常: {str(e)}"


def _normalize_factor_query_text(factor: Any) -> str:
    if isinstance(factor, str):
        return factor.strip()
    if isinstance(factor, dict):
        for key in ("query", "factor", "name", "title", "text", "keyword", "content", "event"):
            value = factor.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        joined_values = " ".join(
            value.strip()
            for value in factor.values()
            if isinstance(value, str) and value.strip()
        )
        return joined_values.strip()
    if isinstance(factor, (list, tuple, set)):
        joined_values = " ".join(
            item.strip()
            for item in factor
            if isinstance(item, str) and item.strip()
        )
        return joined_values.strip()
    if factor is None:
        return ""
    return str(factor).strip()


def _extract_factor_context_text(doc: Dict[str, Any]) -> str:
    if not isinstance(doc, dict):
        return ""
    metadata = doc.get("metadata", {}) if isinstance(doc.get("metadata", {}), dict) else {}
    return (
        doc.get("document")
        or doc.get("content")
        or metadata.get("title")
        or ""
    ).strip()


# LangGraph工作流节点定义
def macro_analyst_node(state: ReportGenerationState) -> Dict:
    """宏观分析师节点：基于“双重LLM调用”的因子驱动RAG工作流"""
    logger.info(">> 正在执行：宏观分析师节点（双重LLM调用）")
    
    try:
        import sys
        import os
        import json
        import re
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)

        from chanlun.tools.ai_analyse import AIAnalyse
        # from chanlun.news_vector_db import NewsVectorDB

        current_code = state['current_code']
        news_content = _format_news_content(state['original_news'])
        ai_client = AIAnalyse(state['current_market'] or "a")
        vector_db_instance = get_vector_db(db_path="./chroma_db")

        # --- 第一阶段：因子提取 ---
        logger.info("阶段1：提取驱动因子")
        factor_prompt = f"""
你是一位敏锐的市场分析师。请阅读以下新闻内容，并识别出影响'{current_code}'的3-5个最核心的驱动因子。

**关键分析原则：**
1. **时间敏感性识别**：请特别重视标有【🔥最新】和【⚡近期】标识的新闻，这些是最新发生的事件
2. **事件状态区分**：请明确区分以下两类事件：
   - **已发生事件**：已经公布的经济数据、已经发生的政策决定、已经结束的会议等
   - **预期事件**：即将公布的数据、预期的政策变化、未来的重要事件等
3. **影响权重评估**：已发生的事件对市场的影响更为确定和直接，应给予更高权重

**因子提取要求：**
- 这些因子应该是具体的、可搜索的概念（例如：'美国CPI数据已公布'、'美联储鹰派言论'、'欧元区通胀数据疲软'）
- 在因子描述中明确标注事件状态，例如：
  * "美国12月CPI数据已公布超预期" （已发生）
  * "美联储1月议息会议预期" （预期事件）
- 优先提取已发生的重要事件，特别是经济数据公布、央行决议等

请以JSON列表的格式返回这些因子，例如：["美国CPI数据已公布超预期", "美联储鹰派言论已发表", "欧央行1月议息会议预期"]。

新闻内容:
{news_content}
"""
        factor_response = _call_ai_and_get_content(ai_client, factor_prompt)
        logger.debug(f"Factor extraction response from LLM: {factor_response}")
        try:
            # 从LLM可能返回的markdown代码块中提取纯JSON
            json_str_match = re.search(r'```json\n(.*?)\n```', factor_response, re.DOTALL)
            if json_str_match:
                json_str = json_str_match.group(1)
            else:
                # 如果没有找到markdown块，直接尝试整个响应
                json_str = factor_response.strip()

            factors = json.loads(json_str)
            if not isinstance(factors, list):
                raise ValueError("LLM did not return a list.")
            factors = _deduplicate_terms(
                [
                    _normalize_factor_query_text(factor)
                    for factor in factors
                    if _normalize_factor_query_text(factor)
                ]
            )[:5]
            logger.info(f"Successfully extracted factors: {factors}")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Factor extraction failed. LLM response could not be parsed: {factor_response}. Error: {e}")
            factors = [] # Continue with an empty list if parsing fails

        # --- 第二阶段：历史检索 ---
        logger.info(f"阶段2：并行检索各因子的历史上下文. 因子: {factors}")
        factor_contexts = {}
        from datetime import datetime, timedelta

        end_date2 = datetime.now()
        start_date2 = end_date2 - timedelta(days=90)
        vector_db = get_vector_db(db_path="./chroma_db")
        
        def search_factor(factor):
            factor_query = _normalize_factor_query_text(factor)
            if not factor_query:
                return factor, []
            return factor, vector_db.semantic_search(
                query=factor_query,
                n_results=20,
                start_date=start_date2.isoformat(),
                end_date=end_date2.isoformat()
            )

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_factor = {executor.submit(search_factor, factor): factor for factor in factors}
            for future in as_completed(future_to_factor):
                factor, context = future.result()
                factor_contexts[factor] = context

        historical_context_text = ""
        for factor, docs in factor_contexts.items():
            historical_context_text += f"\n--- 关于因子 '{factor}' 的历史背景 ---\n"
            if docs:
                for doc in docs:
                    historical_context_text += f"- {_extract_factor_context_text(doc)}\n"
            else:
                historical_context_text += "- 未找到相关历史新闻。\n"

        # --- 第三阶段：综合分析与生成 ---
        logger.info("阶段3：进行综合分析并生成报告")
        synthesis_prompt = f"""
你是一位顶级的宏观策略师，请为 {current_code} 撰写一份宏观分析备忘录。

**核心分析原则：**
1. **事实优先原则**：优先分析已经发生的事件（标有【🔥最新】和【⚡近期】标识），这些事件对市场的影响是确定的
2. **时效性权重**：已公布的经济数据、已发生的政策决定比预期事件具有更高的分析权重
3. **状态明确性**：在分析中明确区分"已发生"和"预期"事件，避免将已公布的数据误判为"即将公布"
4. **影响确定性**：基于实际已发生的事件进行市场影响分析，而不是基于不确定的预期"

**输入信息:**

1.  **核心新闻（按时间排序，最新优先）:**
    {news_content}

2.  **识别出的核心驱动因子:**
    {', '.join(factors) if factors else '未能识别出特定因子'}

3.  **各因子的历史新闻背景:**
    {historical_context_text}

**分析任务与要求:**

1.  **事件状态识别与分析 (Event Status Analysis):**
    -   **已发生事件分析**：重点分析标有【🔥最新】和【⚡近期】标识的已发生事件（如已公布的CPI数据、已结束的央行会议等）
    -   **预期事件评估**：对未来可能发生的事件进行概率性分析，但权重低于已发生事件
    -   **明确标注状态**：在分析每个因子时，明确标注是"已发生"还是"预期事件"
    -   **影响确定性评估**：已发生事件的影响是确定的，预期事件的影响是概率性的

2.  **因子影响力分析 (Factor Impact Analysis):**
    -   对于每个已发生的因子，结合最新新闻和历史背景，分析其实际市场影响
    -   对于预期因子，分析其可能的影响方向和概率
    -   特别关注：如果新闻中提到某经济数据"已公布"，绝不能分析为"即将公布"

3.  **综合判断 (Synthesized View):**
    -   **以已发生事件为主导**：将已发生事件作为分析的核心依据
    -   **预期事件为辅助**：预期事件仅作为风险提示和概率性判断
    -   识别当前主导市场的核心矛盾（优先考虑已发生的重大事件）

4.  **后市展望 (Outlook):**
    -   **基于事实的预判**：主要基于已发生事件的确定性影响进行短期走势预判
    -   **风险提示**：对可能影响预判的未来事件进行风险提示
    -   **逻辑依据**：明确说明预判的主要依据，区分确定性因素和不确定性因素

请以清晰、结构化的备忘录形式输出你的分析。
"""
        final_analysis = _call_ai_and_get_content(ai_client, synthesis_prompt)
        return {"macro_analysis": final_analysis}

    except Exception as e:
        logger.error(f"宏观分析师节点（双重LLM）异常: {str(e)}", exc_info=True)
        return {"macro_analysis": f"宏观分析异常: {str(e)}"}


def economic_data_analyst_node(state: ReportGenerationState) -> Dict:
    """经济数据分析师节点：分析两国经济数据指标"""
    logger.info(">> 正在执行：经济数据分析师节点")
    
    try:
        import sys
        import os
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.tools.ai_analyse import AIAnalyse
        
        economic_data = state.get('economic_data', [])
        current_code = state['current_code']
        current_market = state['current_market']
        name = state['name']

        ai_client = AIAnalyse(state['current_market'] or "fx")
        
        if not economic_data:
            return {"economic_analysis": "暂无经济数据可供分析"}
        # print('economic_data',economic_data)
        # 构建经济数据分析提示词
        economic_prompt = f"""
你是一位资深的宏观经济分析师，专注于{name}市场分析。请基于以下两国经济数据，进行深入的经济分析。

**分析标的**: {name}

**经济数据概览**:
{_format_economic_data_for_analysis(economic_data)}

**分析要求**:

1. **两国经济现状对比分析**:
   - 分析两国当前的经济增长状况（GDP、制造业PMI等）
   - 对比通胀水平和央行货币政策立场
   - 评估就业市场和消费者信心
   - 分析贸易平衡和经常账户状况

2. **经济发展趋势判断**:
   - 基于最新值vs前值vs去年同期值，判断各指标的变化趋势
   - 识别经济数据中的领先指标和滞后指标
   - 评估经济复苏/衰退的可能性和时间节点

3. **美林时钟阶段分析**:
   - 基于经济增长和通胀数据，判断两国分别处于美林时钟的哪个阶段
   - 分析阶段转换的可能性和时间窗口
   - 评估不同阶段对资产配置的影响

4. **两国经济实力对比**:
   - 综合评估两国经济基本面强弱
   - 分析相对经济表现对汇率的影响方向
   - 识别关键的经济分化点和汇率驱动因素

5. **对汇率影响的综合判断**:
   - 基于经济数据分析，判断{name}的可能走向
   - 识别关键的经济数据发布时点和市场关注焦点
   - 提供基于经济基本面的{name}交易建议

**输出格式要求**:
- 使用清晰的标题和子标题组织内容
- 每个分析点都要有具体的数据支撑
- 突出关键结论和投资建议
- 控制总长度在1500字以内
"""
        
        # 调用AI进行经济数据分析
        analysis = _call_ai_and_get_content(ai_client, economic_prompt)
        return {"economic_analysis": analysis}
        
    except Exception as e:
        logger.error(f"经济数据分析师节点异常: {str(e)}", exc_info=True)
        return {"economic_analysis": f"经济数据分析异常: {str(e)}"}


def technical_analyst_node(state: ReportGenerationState) -> Dict:
    """技术分析师节点：仅分析常规技术指标"""
    logger.info(">> 正在执行：技术分析师节点")
    
    try:
        # 调用现有的技术指标分析函数
        analysis = _generate_technical_indicators_analysis(
            state['current_code'], state['current_market']
        )
        return {"technical_analysis": analysis}
        
    except Exception as e:
        logger.error(f"技术分析师节点异常: {str(e)}")
        return {"technical_analysis": f"技术分析异常: {str(e)}"}


def chanlun_expert_node(state: ReportGenerationState) -> Dict:
    """缠论专家节点：调用AI进行缠论分析"""
    logger.info(">> 正在执行：缠论专家节点")
    
    try:
        # 从state中获取frequency参数，如果没有则使用默认值'd'
        frequency = state.get('frequency', 'd')
        current_code = state['current_code']
        analysis = _get_chanlun_analysis(
            current_code, 
            state['current_market'],
            frequency
        )
        return {"chanlun_analysis": analysis}
        
    except Exception as e:
        logger.error(f"缠论专家节点异常: {str(e)}")
        return {"chanlun_analysis": f"缠论分析异常: {str(e)}"}


def financial_analyst_node(state: ReportGenerationState) -> Dict:
    """财务分析师节点：分析公司财务报表数据（仅适用于股票市场）"""
    logger.info(">> 正在执行：财务分析师节点")
    
    try:
        import sys
        import os
        from datetime import datetime, timedelta
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.tools.ai_analyse import AIAnalyse
        from chanlun.db import db
        
        current_market = state['current_market']
        current_code = state['current_code']
        name = state['name']
        
        # 判断是否为股票市场
        stock_markets = ['a', 'hk', 'us']
        if current_market not in stock_markets:
            logger.info(f"当前市场 {current_market} 不是股票市场，跳过财务分析")
            return {"financial_analysis": "当前市场不是股票市场，无需进行财务分析"}
        
        # 查询财务数据
        logger.info(f"正在查询 {current_code} 的财务数据")
        
        # 查询最近3年的财务数据
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=1065)  # 3年前
        
        financial_data = db.company_financials_query(
            code=current_code,
            report_date_start=start_date,
            report_date_end=end_date,
            limit=500
        )
        
        if not financial_data:
            logger.info(f"未找到 {current_code} 的财务数据")
            return {"financial_analysis": "暂无财务报表数据，无法进行财务分析"}
        
        logger.info(f"找到 {len(financial_data)} 条财务数据记录")
        
        # 格式化财务数据供AI分析
        formatted_financial_data = _format_financial_data_for_analysis(financial_data,name)
        print('formatted_financial_data',formatted_financial_data)
        # 构建财务分析提示词
        ai_client = AIAnalyse(current_market)
        
        financial_prompt = f"""
你是一位资深的财务分析师，专注于{name}({current_code})的财务报表分析。请基于以下财务数据，进行深入的财务分析。

**分析标的**: {name}({current_code})
**市场**: {current_market.upper()}

**财务数据概览**:
{formatted_financial_data}

**重要分析要求：请特别重点关注最新财务数据的变动情况和趋势分析**

**分析要求（重点突出最新数据变化）**:

1. **最新盈利能力变动分析（核心重点）**:
   - **重点分析最新报告期营业收入、净利润的变动情况**
   - **详细对比最新期与上期的盈利指标变化（同比、环比增长率）**
   - **评估最新期毛利率、净利率等关键比率的变化趋势**
   - **识别最新期盈利能力变化的主要驱动因素**
   - 分析最新期盈利质量的改善或恶化情况

2. **最新财务健康状况变化（核心重点）**:
   - **重点分析最新期资产负债结构的变化**
   - **评估最新期现金流状况和资金周转效率的变动**
   - **识别最新期财务风险和流动性的新变化**
   - 对比最新期与前期的偿债能力指标变化

3. **最新成长性趋势分析（核心重点）**:
   - **重点评估最新期收入和利润成长性的变化**
   - **分析最新期研发投入、资本开支等成长投资的变动**
   - **基于最新数据判断成长性的可持续性变化**
   - 识别最新期成长性的新驱动因素或风险点

4. **基于最新数据的估值判断**:
   - **重点基于最新财务数据评估估值水平的变化**
   - 分析最新期财务指标对估值的影响
   - 识别最新期估值支撑因素的变化

5. **基于最新变动的投资建议（核心重点）**:
   - **重点基于最新财务数据变化给出投资评级建议**
   - **识别需要重点监控的最新财务指标变化**
   - **提供基于最新数据变动的风险提示和关注要点**
   - 明确指出最新财务表现对投资决策的影响

**输出格式要求**:
- 每个分析维度都要突出最新数据的变化情况
- 优先展示最新期与前期的对比分析结果
- 重点标注关键财务指标的最新变动幅度和方向
- 使用清晰的标题和子标题组织内容
- 控制总长度在1500字以内，重点突出最新变化
"""
        
        # 调用AI进行财务分析
        analysis = _call_ai_and_get_content(ai_client, financial_prompt)
        return {"financial_analysis": analysis}
        
    except Exception as e:
        logger.error(f"财务分析师节点异常: {str(e)}", exc_info=True)
        return {"financial_analysis": f"财务分析异常: {str(e)}"}


def enhanced_chief_strategist_node(state: ReportGenerationState) -> Dict:
    """增强版首席策略师节点：支持反思修正的整合分析"""
    logger.info(">> 正在执行：增强版首席策略师节点")
    
    try:
        import sys
        import os
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.tools.ai_analyse import AIAnalyse
        
        # 获取修正次数，防止无限循环
        revision_count = state.get('revision_count', 0)
        max_revisions = 2  # 最多允许2次修正
        
        # 第一步：质量检查和一致性分析
        quality_check_prompt = f"""
你是一位严格的首席投资策略师。请检查你团队专家的分析报告质量和一致性：

1. **【宏观分析师的报告】**:
{state.get('macro_analysis', '暂无')}

2. **【经济数据分析师的报告】**:
{state.get('economic_analysis', '暂无')}

3. **【技术指标分析师的报告】**:
{state.get('technical_analysis', '暂无')}

4. **【缠论结构专家的报告】**:
{state.get('chanlun_analysis', '暂无')}

5. **【财务分析师的报告】**:
{state.get('financial_analysis', '暂无')}

6. **【地缘政治分析师的报告】**:
{state.get('geopolitical_analysis', '暂无')}

**质量检查要求：**
请检查是否存在以下问题：
1. 观点严重冲突（如宏观看多但技术看空且无合理解释）
2. 逻辑不自洽（如分析依据与结论矛盾）
3. 关键信息缺失（如重要分析师报告为空或过于简单）
4. 分析深度不足（如缺乏具体数据支撑）

**输出格式：**
如果发现严重问题，请输出：
```
NEEDS_REVISION: [问题描述]
TARGET_NODE: [需要重新分析的节点名，如macro_analyst/economic_data_analyst/technical_analyst/chanlun_expert/financial_analyst/geopolitical_analyst]
REVISION_REASON: [具体修正要求]
```

如果质量合格，请输出：
```
QUALITY_APPROVED: 分析质量合格，可以进行最终整合
```
"""
        
        ai_client = AIAnalyse(state['current_market'] or "a")
        quality_result = _call_ai_and_get_content(ai_client, quality_check_prompt)
        
        # 解析质量检查结果
        if "NEEDS_REVISION:" in quality_result and revision_count < max_revisions:
            # 提取修正信息
            import re
            target_match = re.search(r'TARGET_NODE: (\w+)', quality_result)
            if target_match:
                target_node = target_match.group(1)
                logger.info(f"质量检查发现问题，要求{target_node}重新分析（第{revision_count + 1}次修正）")
                return {
                    "needs_revision": True,
                    "revision_target_node": target_node,
                    "revision_count": revision_count + 1
                }
        
        # 如果质量合格或已达到最大修正次数，进入 TradingAgents 风格的研究辩论与裁决流程
        logger.info("分析质量合格或已达最大修正次数，开始研究辩论与最终整合")
        ai_client = AIAnalyse(state['current_market'] or "a")
        research_context = state.get('research_context', '暂无结构化研究上下文')
        analyst_bundle = _build_analyst_report_bundle(state)
        scenario_route = state.get("scenario_route") or {}
        reflection_memory = state.get("reflection_memory") or {}
        quick_research = state.get("quick_research") or {}
        deep_research = state.get("deep_research") or {}
        route_text = (
            f"场景路由: {scenario_route.get('label', '均衡观察')}\n"
            f"触发源: {scenario_route.get('trigger', '当前资产')}\n"
            f"路由原因: {scenario_route.get('reason', '暂无')}\n"
            f"快评节点: {'、'.join(_ANALYST_NODE_LABELS.get(node, node) for node in scenario_route.get('quick_nodes', [])) or '暂无'}\n"
            f"深研节点: {'、'.join(_ANALYST_NODE_LABELS.get(node, node) for node in scenario_route.get('deep_nodes', [])) or '暂无'}"
        )
        reflection_text = reflection_memory.get("memory_text", "- 暂无相似反思记忆")
        quick_text = quick_research.get("summary", "暂无盘中快评")
        deep_text = deep_research.get("summary", "暂无深度研究计划")

        bull_prompt = f"""
你是一位 TradingAgents 风格的多头研究员。你的任务不是复述分析师观点，而是基于证据构建一个“最强多头案例”。

研究上下文:
{research_context}

场景化路由:
{route_text}

历史反思记忆:
{reflection_text}

快慢双层研究:
- 快评: {quick_text}
- 深研: {deep_text}

分析师报告:
{analyst_bundle}

请按以下结构输出，要求观点鲜明、证据具体、逻辑闭环：
1. 多头核心结论
2. 最关键的3-5条支撑证据
3. 多头成立的主导逻辑链
4. 未来催化剂
5. 多头最容易被证伪的条件
6. 对空头常见观点的预先反驳
"""
        bullish_thesis = _call_ai_and_get_content(ai_client, bull_prompt)

        bear_prompt = f"""
你是一位 TradingAgents 风格的空头研究员。你的任务不是简单唱空，而是基于证据构建一个“最强空头案例”。

研究上下文:
{research_context}

场景化路由:
{route_text}

历史反思记忆:
{reflection_text}

快慢双层研究:
- 快评: {quick_text}
- 深研: {deep_text}

分析师报告:
{analyst_bundle}

请按以下结构输出，要求观点鲜明、证据具体、逻辑闭环：
1. 空头核心结论
2. 最关键的3-5条反向证据
3. 空头成立的主导逻辑链
4. 未来风险催化剂
5. 空头最容易被证伪的条件
6. 对多头常见观点的预先反驳
"""
        bearish_thesis = _call_ai_and_get_content(ai_client, bear_prompt)

        research_manager_prompt = f"""
你是一位 TradingAgents 风格的研究经理兼裁决者。请比较多头与空头研究员的论证，给出最终裁决，不要模糊化结论。

研究上下文:
{research_context}

场景化路由:
{route_text}

历史反思记忆:
{reflection_text}

分析师报告:
{analyst_bundle}

多头研究员结论:
{bullish_thesis}

空头研究员结论:
{bearish_thesis}

请按以下结构输出：
1. 最终立场: 看多 / 看空 / 中性
2. 裁决理由: 哪一方证据链更扎实，为什么
3. 主导因子排序: 按重要性列出 3-5 个
4. 当前市场所处阶段: 趋势启动 / 趋势延续 / 高位分歧 / 震荡等待 / 风险释放 等
5. 核心交易思路: 顺势、回调、观望、对冲等
6. 需要重点跟踪的失效信号
"""
        research_verdict = _call_ai_and_get_content(ai_client, research_manager_prompt)

        risk_manager_prompt = f"""
你是一位 TradingAgents 风格的风险经理。你的任务不是重复研究经理的结论，而是识别这份判断最脆弱的地方。

研究上下文:
{research_context}

场景化路由:
{route_text}

历史反思记忆:
{reflection_text}

快评与深研计划:
- 快评: {quick_text}
- 深研: {deep_text}

多头研究员结论:
{bullish_thesis}

空头研究员结论:
{bearish_thesis}

研究经理裁决:
{research_verdict}

请按以下结构输出：
1. 风险等级: 高 / 中 / 低
2. 最可能导致判断失效的3个信号
3. 当前最不适合做的动作
4. 还需要等待的确认条件
5. 风险经理结论: 一句话总结
"""
        risk_assessment = _call_ai_and_get_content(ai_client, risk_manager_prompt)

        prompt = f"""
你是一位顶级的首席投资策略师。请基于 TradingAgents 风格的“分析师分工 -> 多空研究 -> 经理裁决”链路，输出一份更具逻辑性的最终研究报告。

研究上下文:
{research_context}

场景化路由:
{route_text}

历史反思记忆:
{reflection_text}

快慢双层研究:
- 快评: {quick_text}
- 深研: {deep_text}

分析师报告:
{analyst_bundle}

多头研究员结论:
{bullish_thesis}

空头研究员结论:
{bearish_thesis}

研究经理裁决:
{research_verdict}

风险经理结论:
{risk_assessment}

最终报告必须严格覆盖以下部分：
1. 盘中快评：基于快评路径先给一句话结论
2. 综合摘要：一句话给出市场主线，一句话给出当前判断
3. 研究结论：明确写出看多/看空/中性以及背后的主导逻辑
4. 逻辑链推演：按照“宏观/政策 -> 资金/情绪 -> 新闻催化 -> 技术结构 -> 交易结论”的顺序展开
5. 多空分歧与裁决：指出多头最强点、空头最强点，以及为什么最终裁决偏向一方
6. 场景分析：基准情景、乐观情景、风险情景
7. 交易计划：触发条件、确认信号、止损/失效条件、目标区间、仓位建议
8. 风险清单：按优先级列出主要风险，并说明风险经理最在意的失效条件

要求：
- 结论要明确，不要泛泛而谈
- 必须解释“为什么现在是这个判断”
- 必须体现证据权重，而不是简单罗列信息
- 必须遵循资产研究模板的优先主线，不要用不适合该资产的框架强行解释
- 用中文输出，结构清晰
"""
        main_report = _call_ai_and_get_content(ai_client, prompt)

        final_report = main_report
        final_report += "\n\n" + "="*80 + "\n"
        final_report += "🧭 **研究辩论与裁决**\n"
        final_report += "="*80 + "\n\n"
        final_report += "## 🟢 多头研究员结论\n"
        final_report += bullish_thesis + "\n\n"
        final_report += "## 🔴 空头研究员结论\n"
        final_report += bearish_thesis + "\n\n"
        final_report += "## ⚖️ 研究经理裁决\n"
        final_report += research_verdict + "\n\n"
        final_report += "## 🛡️ 风险经理结论\n"
        final_report += risk_assessment + "\n\n"
        if quick_text:
            final_report += "## ⚡ 快评快照\n"
            final_report += quick_text + "\n\n"
        if reflection_text:
            final_report += "## 🧠 反思记忆\n"
            final_report += reflection_text + "\n\n"

        # 添加附件部分
        final_report += "\n\n" + "="*80 + "\n"
        final_report += "📎 **附件：专家分析详细报告**\n"
        final_report += "="*80 + "\n\n"
        
        # 附件1：宏观分析师报告
        if state.get('macro_analysis'):
            final_report += "## 📊 附件一：宏观分析师详细报告\n"
            final_report += "-" * 50 + "\n"
            final_report += state['macro_analysis'] + "\n\n"
        
        # 附件2：经济数据分析师报告
        if state.get('economic_analysis'):
            final_report += "## 📈 附件二：经济数据分析师详细报告\n"
            final_report += "-" * 50 + "\n"
            final_report += state['economic_analysis'] + "\n\n"
        
        # 附件3：技术指标分析师报告
        if state.get('technical_analysis'):
            final_report += "## 📉 附件三：技术指标分析师详细报告\n"
            final_report += "-" * 50 + "\n"
            final_report += state['technical_analysis'] + "\n\n"
        
        # 附件4：缠论结构专家报告
        if state.get('chanlun_analysis'):
            final_report += "## 🔍 附件四：缠论结构专家详细报告\n"
            final_report += "-" * 50 + "\n"
            final_report += state['chanlun_analysis'] + "\n\n"
        
        # 附件5：财务分析师报告
        if state.get('financial_analysis'):
            final_report += "## 💰 附件五：财务分析师详细报告\n"
            final_report += "-" * 50 + "\n"
            final_report += state['financial_analysis'] + "\n\n"
        
        # 附件6：地缘政治分析师报告
        if state.get('geopolitical_analysis'):
            final_report += "## 🌍 附件六：地缘政治分析师详细报告\n"
            final_report += "-" * 50 + "\n"
            final_report += state['geopolitical_analysis'] + "\n\n"
        
        final_report += "="*80 + "\n"
        final_report += "*以上附件为各专家的详细分析报告，供参考*\n"
        
        # 重置修正标志，确保流程结束
        return {
            "final_report": final_report,
            "bullish_thesis": bullish_thesis,
            "bearish_thesis": bearish_thesis,
            "research_verdict": research_verdict,
            "risk_assessment": risk_assessment,
            "needs_revision": False,
            "revision_target_node": ""
        }
        
    except Exception as e:
        logger.error(f"增强版首席策略师节点异常: {str(e)}")
        return {
            "final_report": f"最终报告生成异常: {str(e)}",
            "risk_assessment": f"风险经理结论生成异常: {str(e)}",
            "needs_revision": False,
            "revision_target_node": ""
        }


def chief_strategist_node(state: ReportGenerationState) -> Dict:
    """原版首席策略师节点：保持向后兼容"""
    logger.info(">> 正在执行：原版首席策略师节点")
    return enhanced_chief_strategist_node(state)


def _get_economic_data_by_product(product_info: Optional[Dict[str, Any]] = None, product_code: Optional[str] = None, limit: int = 1000) -> List[Dict]:
    """
    根据产品信息获取相关的经济数据
    
    Args:
        product_info: 产品信息字典，包含产品类型等信息
        product_code: 产品代码，如 'EURUSD', 'GBPJPY' 等
        limit: 查询数据条数限制
        
    Returns:
        List[Dict]: 经济数据列表
    """
    from chanlun.db import db
    
    # 外汇货币对到国家/地区的映射
    currency_to_country = {
        'USD': 'usd',
        'EUR': 'eur', 
        'GBP': 'gbp',
        'JPY': 'jpy',
        'CHF': 'chf',
        'CAD': 'cad',
        'AUD': 'aud',
        'NZD': 'nzd',
        'CNY': 'cny',
        'CNH': 'cny',
        'HKD': 'hkd',
        'SGD': 'sgd'
    }
    
    economic_data_list = []
    countries_to_query = set()
    
    # 判断是否为外汇产品
    is_forex = False
    if product_info:
        product_type = product_info.get('type', '').lower()
        is_forex = product_type in ['forex', 'currency', '外汇', '货币']
    print('is_forex:',is_forex)
    print('product_code:',product_code)
    print('currency_to_country:',currency_to_country)

    # 如果是外汇产品，从产品代码中提取货币对
    if is_forex and product_code:
        # 处理常见的外汇对格式，如 EURUSD, GBPJPY 等
        currency_pair = product_code.upper().replace('FE.','')
        if len(currency_pair) >= 6:
            base_currency = currency_pair[:3].upper()
            quote_currency = currency_pair[3:6].upper()
            print('base_currency:',base_currency)
            print('quote_currency:',quote_currency)
            # 添加对应的国家/地区到查询列表
            if base_currency in currency_to_country:
                countries_to_query.add(currency_to_country[base_currency])
            if quote_currency in currency_to_country:
                countries_to_query.add(currency_to_country[quote_currency])
    
    # 如果没有识别到外汇对或者不是外汇产品，使用默认的主要经济体
    if not countries_to_query:
        countries_to_query = {'usd', 'cny'}  # 默认查询美国和中国的经济数据
    
    # 查询每个国家/地区的经济数据
    for country in countries_to_query:
        try:
            print('country_v1:',country)
            country_data = db.economic_data_query(indicator_name=country, limit=limit)
            # 转换为字典格式
            country_data_dict = [item.__dict__ for item in country_data]
            economic_data_list.extend(country_data_dict)
        except Exception as e:
            logger.warning(f"查询 {country} 经济数据时出错: {e}")
            continue
    
    logger.info(f"获取到 {len(economic_data_list)} 条经济数据，涉及国家/地区: {list(countries_to_query)}")
    return economic_data_list


def _generate_ai_market_summary(
    economic_data_list: List[Dict],
    news_list: List[Dict],
    current_market: str = '',
    current_code: str = '',
    name: str = '',
    frequency: str = 'd',
    selected_nodes: List[str] = None,
    scenario_route: Optional[Dict[str, Any]] = None,
    reflection_memory: Optional[Dict[str, Any]] = None,
    quick_research: Optional[Dict[str, Any]] = None,
    deep_research: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    使用优化的LangGraph工作流生成高质量、逻辑性强的研究报告
    
    优化特性:
    1. 并行化初级分析：宏观、经济数据、技术和缠论分析并行执行
    2. 反思修正循环：首席策略师可要求特定分析师重新分析
    3. 工具使用节点：支持外部工具调用（如实时数据获取）
    
    Args:
        economic_data_list: 经济数据列表
        news_list: 新闻列表
        current_market: 当前市场代码 (如: a, hk, us, fx等)
        current_code: 当前标的代码
        name: 标的名称
        frequency: 分析周期
        selected_nodes: 选择的分析节点列表
        
    Returns:
        Dict[str, Any]: 生成的研究报告与元信息
    """
    try:
        from langgraph.graph import StateGraph, END
        from langgraph.prebuilt import ToolNode
        from datetime import datetime
        import sys
        import os
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.zixuan import ZiXuan
        from chanlun.exchange import get_exchange
        from chanlun.base import Market
        
        # 验证必要参数
        if not current_market:
            logger.warning("未提供市场代码，使用默认市场'a'")
            current_market = 'a'
        
        if not current_code:
            logger.warning("未提供标的代码，将生成通用市场分析")
        
        logger.info(f"开始使用优化的LangGraph工作流生成报告，市场: {current_market}, 代码: {current_code}")
        
        # 处理选择的节点，如果没有提供则使用所有节点
        if selected_nodes is None:
            selected_nodes = ['macro_analyst', 'economic_data_analyst', 'technical_analyst', 'chanlun_expert', 'financial_analyst', 'geopolitical_analyst']
        
        # 确保selected_nodes是列表类型
        if not isinstance(selected_nodes, list):
            selected_nodes = list(selected_nodes) if selected_nodes else []
        
        logger.info(f"选择的AI分析节点: {selected_nodes}")
        
        # 1. 创建优化的工作流图
        workflow = StateGraph(ReportGenerationState)
        
        # 根据用户选择添加分析师节点
        available_nodes = {
            'macro_analyst': macro_analyst_node,
            'economic_data_analyst': economic_data_analyst_node,
            'technical_analyst': technical_analyst_node,
            'chanlun_expert': chanlun_expert_node,
            'financial_analyst': financial_analyst_node,
            'geopolitical_analyst': geopolitical_analyst_node
        }
        
        # 只添加用户选择的节点
        active_nodes = []
        for node_name in selected_nodes:
            if node_name in available_nodes:
                try:
                    workflow.add_node(node_name, available_nodes[node_name])
                    active_nodes.append(node_name)
                    logger.info(f"添加分析节点: {node_name}")
                except Exception as e:
                    logger.error(f"添加节点{node_name}失败: {str(e)}")
            else:
                logger.warning(f"未知的分析节点: {node_name}")
        
        if not active_nodes:
            logger.error("没有有效的分析节点被选择")
            return {"summary": "错误：没有选择有效的分析节点。", "risk_assessment": ""}
        
        # 添加首席策略师节点（支持反思修正）
        try:
            workflow.add_node("chief_strategist", enhanced_chief_strategist_node)
        except Exception as e:
            logger.error(f"添加首席策略师节点失败: {str(e)}")
            return {"summary": f"工作流配置错误：{str(e)}", "risk_assessment": ""}
        
        # 定义策略师决策路由器
        def strategist_decision_router(state: ReportGenerationState):
            """首席策略师决策路由：检查是否需要修正或结束流程"""
            try:
                needs_revision = state.get('needs_revision', False)
                revision_target = state.get('revision_target_node', '')
                revision_count = state.get('revision_count', 0)
                
                # 防止无限修正循环：超过最大修正次数后强制结束
                MAX_REVISION_COUNT = 3
                if revision_count >= MAX_REVISION_COUNT:
                    logger.warning(f"已达到最大修正次数({MAX_REVISION_COUNT})，强制结束流程")
                    return END
                
                if needs_revision and revision_target and revision_target in active_nodes:
                    logger.info(f"首席策略师要求{revision_target}重新分析 (第{revision_count + 1}次修正)")
                    return revision_target
                else:
                    logger.info("分析质量合格，流程结束")
                    return END
            except Exception as e:
                logger.error(f"策略师决策路由器异常: {str(e)}")
                return END
        
        # 添加启动节点来触发并行执行
        def start_parallel_analysis(state: ReportGenerationState):
            """启动节点：触发所有初级分析师并行执行"""
            logger.info("启动并行分析：宏观、经济数据、技术、缠论、地缘政治分析师将同时开始工作")
            return state
        
        try:
            workflow.add_node("start_analysis", start_parallel_analysis)
            workflow.set_entry_point("start_analysis")
        except Exception as e:
            logger.error(f"添加启动节点失败: {str(e)}")
            return {"summary": f"工作流配置错误：{str(e)}", "risk_assessment": ""}
        
        # 从启动节点分发到用户选择的分析师（并行执行）
        try:
            for node_name in active_nodes:
                workflow.add_edge("start_analysis", node_name)
                logger.info(f"添加启动边: start_analysis -> {node_name}")
        except Exception as e:
            logger.error(f"添加启动边失败: {str(e)}")
            return {"summary": f"工作流配置错误：{str(e)}", "risk_assessment": ""}
        
        # 所有选择的分析师完成后，汇聚到首席策略师
        try:
            for node_name in active_nodes:
                workflow.add_edge(node_name, "chief_strategist")
                logger.info(f"添加汇聚边: {node_name} -> chief_strategist")
        except Exception as e:
            logger.error(f"添加汇聚边失败: {str(e)}")
            return {"summary": f"工作流配置错误：{str(e)}", "risk_assessment": ""}
        
        # 首席策略师根据分析质量决定下一步
        try:
            decision_map = {node_name: node_name for node_name in active_nodes}
            decision_map[END] = END
            workflow.add_conditional_edges(
                "chief_strategist",
                strategist_decision_router,
                decision_map
            )
        except Exception as e:
            logger.error(f"添加条件边失败: {str(e)}")
            return {"summary": f"工作流配置错误：{str(e)}", "risk_assessment": ""}
        
        # 编译成可执行应用
        try:
            app = workflow.compile()
        except Exception as e:
            logger.error(f"工作流编译失败: {str(e)}")
            return {"summary": f"工作流编译错误：{str(e)}", "risk_assessment": ""}
        
        # 2. 获取地缘政治新闻数据
        geopolitical_news = []
        try:
            vector_db = get_vector_db()
            if vector_db:
                geopolitical_news = _search_geopolitical_news(
                    7,
                    asset_code=current_code,
                    market=current_market,
                )
                logger.info(f"获取到{len(geopolitical_news)}条地缘政治相关新闻")
            else:
                logger.warning("无法获取向量数据库实例，跳过地缘政治新闻搜索")
        except Exception as e:
            logger.error(f"获取地缘政治新闻失败: {str(e)}")
        
        research_context = _build_market_research_context(
            news_list=news_list,
            economic_data_list=economic_data_list,
            current_market=current_market,
            current_code=current_code,
            name=name,
            geopolitical_news=geopolitical_news,
        )

        # 3. 定义初始状态
        initial_state = ReportGenerationState(
            original_news=news_list,
            economic_data=economic_data_list,
            current_market=current_market,
            current_code=current_code,
            name=name,
            frequency=frequency,
            geopolitical_news=geopolitical_news,
            macro_analysis=None,
            economic_analysis=None,
            technical_analysis=None,
            chanlun_analysis=None,
            financial_analysis=None,
            geopolitical_analysis=None,
            research_context=research_context,
            scenario_route=scenario_route or {},
            reflection_memory=reflection_memory or {},
            quick_research=quick_research or {},
            deep_research=deep_research or {},
            bullish_thesis=None,
            bearish_thesis=None,
            research_verdict=None,
            risk_assessment=None,
            final_report=None,
            # 新增反思修正相关字段
            needs_revision=False,
            revision_target_node='',
            revision_count=0
        )
        
        # 3. 运行优化的工作流
        logger.info("开始执行优化的LangGraph并行工作流...")
        final_state = app.invoke(initial_state)
        
        # 4. 获取基础报告
        base_report = final_state.get('final_report', '报告生成失败')
        
        # 5. 添加价格信息和图表
        market_summary = base_report
        
        # 如果有具体标的代码，添加图表和额外的技术分析
        if current_code and current_market and not base_report.startswith("报告生成失败"):
            # 添加缠论图表快照
            try:
                logger.info(f"正在为{current_code}生成缠论图表快照")
                chart_snapshot_html = _generate_chart_snapshot_html(current_code, current_market)
                if chart_snapshot_html:
                    market_summary += f"\n\n## 缠论图表\n{chart_snapshot_html}"
                    logger.info("缠论图表快照添加成功")
                else:
                    logger.warning("缠论图表快照生成失败")
                    market_summary += "\n\n## 缠论图表\n图表加载中，请稍后刷新查看。"
            except Exception as e:
                logger.error(f"缠论图表快照异常: {str(e)}")
                market_summary += f"\n\n## 缠论图表\n图表生成异常: {str(e)}"
        # 获取用户关注产品的价格信息
        price_info = ""
        try:
            # 支持的市场类型
            supported_markets = ['a', 'hk', 'us', 'fx', 'futures', 'currency']
            all_price_data = []
            
            for market_type in supported_markets:
                try:
                    zx = ZiXuan(market_type)
                    # 获取所有自选组的股票
                    all_zx_stocks = zx.query_all_zs_stocks()
                    
                    # 收集所有股票代码
                    market_codes = []
                    for zx_group in all_zx_stocks:
                        for stock in zx_group['stocks']:
                            market_codes.append(stock['code'])
                    
                    if market_codes:
                        # 获取价格数据
                        ex = get_exchange(Market(market_type))
                        ticks = ex.ticks(market_codes)
                        
                        market_names = {
                            'a': 'A股',
                            'hk': '港股', 
                            'us': '美股',
                            'fx': '外汇',
                            'futures': '期货',
                            'currency': '数字货币'
                        }
                        market_name = market_names.get(market_type, market_type)
                        
                        for code, tick in ticks.items():
                            # 查找股票名称
                            stock_name = code
                            for zx_group in all_zx_stocks:
                                for stock in zx_group['stocks']:
                                    if stock['code'] == code:
                                        stock_name = stock['name']
                                        break
                            
                            price_data = {
                                'market': market_name,
                                'code': code,
                                'name': stock_name,
                                'price': getattr(tick, 'last', 0),
                                'rate': getattr(tick, 'rate', 0)
                            }
                            all_price_data.append(price_data)
                            
                except Exception as e:
                    logger.warning(f"获取{market_type}市场价格数据失败: {str(e)}")
                    continue
            
            # 构建价格信息文本
            if all_price_data:
                price_info = "\n\n## 关注产品当前价格\n"
                market_data_groups = {}
                for data in all_price_data:
                    market_name = data['market']
                    if market_name not in market_data_groups:
                        market_data_groups[market_name] = []
                    market_data_groups[market_name].append(data)
                
                for market_name, stocks in market_data_groups.items():
                    price_info += f"\n**{market_name}市场:**\n"
                    for stock in stocks[:10]:  # 限制每个市场最多显示10只股票
                        rate_str = f"{stock['rate']:+.2f}%" if stock['rate'] != 0 else "0.00%"
                        price_info += f"- {stock['name']}({stock['code']}): {stock['price']:.2f} ({rate_str})\n"
                        
        except Exception as e:
            logger.error(f"获取关注产品价格信息失败: {str(e)}")
            price_info = "\n\n## 关注产品价格\n暂时无法获取价格信息，请稍后重试。\n"
        
        # 将价格信息添加到基础报告
        market_summary = market_summary + price_info
        
        
        logger.info("LangGraph工作流执行完成，报告生成成功")
        return {
            "summary": market_summary,
            "risk_assessment": final_state.get("risk_assessment", "") or "",
            "scenario_route": final_state.get("scenario_route", scenario_route or {}),
            "reflection_memory": final_state.get("reflection_memory", reflection_memory or {}),
            "quick_research": final_state.get("quick_research", quick_research or {}),
            "deep_research": final_state.get("deep_research", deep_research or {}),
            "research_verdict": final_state.get("research_verdict", "") or "",
        }
            
    except ImportError as e:
        logger.error(f"导入LangGraph或相关模块失败: {str(e)}")
        return {"summary": "系统配置错误，无法调用LangGraph工作流。请检查依赖安装。", "risk_assessment": ""}
    except Exception as e:
        logger.error(f"LangGraph工作流执行时发生错误: {str(e)}")
        return {"summary": f"生成研究报告时发生错误: {str(e)}", "risk_assessment": ""}


def _analyze_market_impact(vector_db, time_range: Dict, filters: Dict, parameters: Dict) -> Dict:
    """
    市场影响分析
    
    Args:
        vector_db: 向量数据库实例
        time_range: 时间范围
        filters: 过滤条件
        parameters: 分析参数
    
    Returns:
        Dict: 分析结果
    """
    try:
        # 获取市场相关新闻
        min_relevance = filters.get('min_market_relevance', 0.3)
        market_news = vector_db.get_market_relevant_news(min_relevance=min_relevance)
        
        if not market_news:
            return {
                "impact_score": 0.0,
                "relevant_news_count": 0,
                "high_impact_topics": [],
                "recommendation": "数据不足，无法进行市场影响分析"
            }
        
        # 计算影响分数
        total_relevance = sum(news['metadata']['market_relevance'] for news in market_news)
        avg_relevance = total_relevance / len(market_news)
        
        # 提取高影响主题（这里简化处理）
        high_impact_topics = []
        for news in market_news[:10]:  # 取前10条最相关的新闻
            keywords = json.loads(news['metadata'].get('keywords', '[]'))
            high_impact_topics.extend(keywords[:3])  # 每条新闻取前3个关键词
        
        # 去重并统计频次
        topic_counts = {}
        for topic in high_impact_topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        
        # 按频次排序
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "impact_score": avg_relevance,
            "relevant_news_count": len(market_news),
            "high_impact_topics": [topic for topic, count in sorted_topics],
            "topic_frequencies": dict(sorted_topics),
            "recommendation": "高" if avg_relevance > 0.7 else "中" if avg_relevance > 0.4 else "低"
        }
        
    except Exception as e:
        logger.error(f"市场影响分析失败: {str(e)}")
        return {"error": str(e)}


def _analyze_topic_clustering(vector_db, time_range: Dict, filters: Dict, parameters: Dict) -> Dict:
    """
    主题聚类分析
    
    Args:
        vector_db: 向量数据库实例
        time_range: 时间范围
        filters: 过滤条件
        parameters: 分析参数
    
    Returns:
        Dict: 分析结果
    """
    try:
        # 获取市场相关新闻进行聚类
        market_news = vector_db.get_market_relevant_news(min_relevance=0.2, limit=200)
        
        if len(market_news) < 5:
            return {
                "clusters": [],
                "total_news": len(market_news),
                "message": "新闻数量不足，无法进行有效聚类"
            }
        
        # 简化的主题聚类（基于关键词）
        topic_groups = {}
        
        for news in market_news:
            keywords = json.loads(news['metadata'].get('keywords', '[]'))
            if not keywords:
                continue
                
            # 使用第一个关键词作为主题
            main_topic = keywords[0] if keywords else "其他"
            
            if main_topic not in topic_groups:
                topic_groups[main_topic] = []
            
            topic_groups[main_topic].append({
                "news_id": news['id'],
                "title": news['metadata']['title'],
                "relevance": news['metadata']['market_relevance'],
                "sentiment": news['metadata']['sentiment_score']
            })
        
        # 转换为聚类结果格式
        clusters = []
        for topic, news_list in topic_groups.items():
            if len(news_list) >= 2:  # 至少2条新闻才形成聚类
                avg_sentiment = sum(n['sentiment'] for n in news_list) / len(news_list)
                avg_relevance = sum(n['relevance'] for n in news_list) / len(news_list)
                
                clusters.append({
                    "topic": topic,
                    "news_count": len(news_list),
                    "avg_sentiment": avg_sentiment,
                    "avg_relevance": avg_relevance,
                    "sample_news": news_list[:3]  # 返回前3条作为样本
                })
        
        # 按新闻数量排序
        clusters.sort(key=lambda x: x['news_count'], reverse=True)
        
        return {
            "clusters": clusters[:10],  # 返回前10个聚类
            "total_clusters": len(clusters),
            "total_news": len(market_news),
            "coverage_rate": sum(c['news_count'] for c in clusters) / len(market_news) if market_news else 0
        }
        
    except Exception as e:
        logger.error(f"主题聚类分析失败: {str(e)}")
        return {"error": str(e)}


def _search_geopolitical_news(
    days: int = 7,
    asset_code: Optional[str] = None,
    market: str = "",
) -> List[Dict]:
    """
    搜索地缘政治相关新闻
    
    Args:
        days: 搜索天数，默认7天
        
    Returns:
        List[Dict]: 地缘政治相关新闻列表
    """
    try:
        from datetime import datetime, timedelta

        geopolitical_topic_clusters = {
            "middle_east": {
                "query": "中东 以色列 伊朗",
                "keywords": ["中东", "以色列", "伊朗", "巴勒斯坦", "加沙", "红海", "霍尔木兹", "停火"],
            },
            "russia_ukraine": {
                "query": "俄乌 俄罗斯 乌克兰",
                "keywords": ["俄乌", "俄罗斯", "乌克兰", "黑海", "北约", "停火", "军援", "制裁"],
            },
            "us_china": {
                "query": "中美 关税 制裁",
                "keywords": ["中美", "关税", "贸易战", "制裁", "芯片", "出口管制", "科技战", "中国", "美国"],
            },
            "taiwan_strait": {
                "query": "台海 台湾 军演",
                "keywords": ["台海", "台湾", "军演", "两岸", "南海", "舰队", "导弹", "国防"],
            },
            "korean_peninsula": {
                "query": "朝鲜 半岛 导弹",
                "keywords": ["朝鲜", "半岛", "导弹", "韩国", "核试验", "军演", "边境"],
            },
            "global_sanctions": {
                "query": "制裁 能源 供应链",
                "keywords": ["制裁", "能源制裁", "金融制裁", "次级制裁", "供应链", "禁运", "贸易限制"],
            },
        }

        def _get_asset_geopolitical_focus(target_asset_code: Optional[str], target_market: str) -> List[str]:
            normalized = _normalize_asset_code(target_asset_code)
            focus_map = {
                "XAU": ["middle_east", "russia_ukraine", "global_sanctions", "us_china"],
                "CL": ["middle_east", "russia_ukraine", "global_sanctions"],
                "USDCNY": ["us_china", "taiwan_strait", "global_sanctions"],
                "EURUSD": ["russia_ukraine", "global_sanctions", "us_china"],
                "USDJPY": ["us_china", "korean_peninsula", "taiwan_strait"],
            }
            if normalized in focus_map:
                return focus_map[normalized]
            if target_market == "fx":
                return ["us_china", "global_sanctions", "russia_ukraine"]
            if target_market == "futures":
                return ["middle_east", "global_sanctions", "russia_ukraine"]
            return ["us_china", "middle_east", "russia_ukraine"]
        
        # 计算搜索时间范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 获取向量数据库实例
        vector_db = get_vector_db(db_path="./chroma_db")
        
        geopolitical_news_map: Dict[str, Dict[str, Any]] = {}
        topic_order = _get_asset_geopolitical_focus(asset_code, market)
        for topic_name in geopolitical_topic_clusters.keys():
            if topic_name not in topic_order:
                topic_order.append(topic_name)

        # 对每个主题簇进行搜索
        for index, topic_name in enumerate(topic_order):
            try:
                topic = geopolitical_topic_clusters[topic_name]
                topic_query = topic["query"]
                topic_keywords = topic["keywords"][:8]
                focus_bonus = max(0, len(topic_order) - index)
                search_results = vector_db.semantic_search(
                    query=topic_query,
                    n_results=25 if index < 3 else 15,
                    keywords=topic_keywords,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat()
                )

                if not search_results:
                    search_results = _search_news_from_relational_db(
                        query=topic_query,
                        search_terms=topic_keywords,
                        start_date=start_date,
                        end_date=end_date,
                        n_results=25 if index < 3 else 15,
                    )
                
                # 过滤和去重
                for news in search_results:
                    metadata = news.get('metadata', {}) if isinstance(news.get('metadata', {}), dict) else {}
                    news_id = metadata.get('news_id') or news.get('id') or metadata.get('title') or f"topic-{topic_name}"
                    title = metadata.get('title', '').lower()
                    content = news.get('document', '').lower()
                    matched_terms = [kw for kw in topic_keywords if kw.lower() in title or kw.lower() in content]
                    if not matched_terms:
                        continue

                    existing = geopolitical_news_map.get(news_id)
                    topic_score = len(matched_terms) + focus_bonus + float(metadata.get('importance_score', 0) or 0)
                    if existing is None or topic_score > existing.get("geopolitical_score", 0):
                        item = dict(news)
                        item["geopolitical_topics"] = [topic_name]
                        item["geopolitical_matched_terms"] = matched_terms
                        item["geopolitical_score"] = topic_score
                        geopolitical_news_map[news_id] = item
                    else:
                        existing_topics = set(existing.get("geopolitical_topics", []))
                        existing_topics.add(topic_name)
                        existing["geopolitical_topics"] = sorted(existing_topics)
                        existing_terms = set(existing.get("geopolitical_matched_terms", []))
                        existing["geopolitical_matched_terms"] = sorted(existing_terms.union(matched_terms))
                        existing["geopolitical_score"] = max(existing.get("geopolitical_score", 0), topic_score)
                            
            except Exception as e:
                logger.warning(f"搜索地缘主题 '{topic_name}' 时出错: {str(e)}")
                continue

        geopolitical_news = list(geopolitical_news_map.values())
        asset_rules = _get_geopolitical_asset_rules(asset_code, market)
        for item in geopolitical_news:
            topics = item.get("geopolitical_topics", []) or []
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {}
            base_score = float(item.get("geopolitical_score", 0) or 0) + float(metadata.get("importance_score", 0) or 0)
            impact_direction = "neutral"
            impact_reason = "未建立明确资产映射"
            impact_score = 0.0
            for topic_name in topics:
                rule = asset_rules.get(topic_name)
                if not rule:
                    continue
                weighted_score = base_score * float(rule.get("weight", 1.0))
                if weighted_score >= impact_score:
                    impact_score = weighted_score
                    impact_direction = rule.get("direction", "neutral")
                    impact_reason = rule.get("reason", impact_reason)
            item["geopolitical_impact_direction"] = impact_direction
            item["geopolitical_impact_reason"] = impact_reason
            item["geopolitical_impact_score"] = impact_score

        # 按主题相关度、重要性和时间排序
        geopolitical_news.sort(
            key=lambda x: (
                x.get('geopolitical_impact_score', 0),
                x.get('geopolitical_score', 0),
                x.get('metadata', {}).get('importance_score', 0),
                x.get('metadata', {}).get('published_at', '')
            ),
            reverse=True
        )
        
        # 限制返回数量
        result = geopolitical_news[:50]  # 最多返回50条
        
        logger.info(f"搜索到 {len(result)} 条地缘政治相关新闻")
        return result
        
    except Exception as e:
        logger.error(f"搜索地缘政治新闻失败: {str(e)}")
        return []


def geopolitical_analyst_node(state: ReportGenerationState) -> Dict:
    """
    地缘政治分析师节点：专门分析地缘政治事件对市场的影响
    """
    logger.info(">> 正在执行：地缘政治分析师节点")
    
    try:
        geopolitical_news = state.get('geopolitical_news', [])
        current_market = state.get('current_market', '')
        current_code = state.get('current_code', '')
        name = state.get('name', '')
        
        if not geopolitical_news:
            analysis = "当前时期未发现重大地缘政治事件，市场地缘政治风险相对较低。"
        else:
            # 格式化地缘政治新闻
            formatted_news = _format_news_content(geopolitical_news)
            impact_summary = _summarize_geopolitical_asset_impact(
                geopolitical_news,
                current_code,
                current_market,
            )
            structured_context = f"""
地缘政治影响方向统计:
- 总体方向: {impact_summary.get('overall_direction', 'neutral')}
- 利多线索: {impact_summary.get('direction_counts', {}).get('bullish', 0)}
- 利空线索: {impact_summary.get('direction_counts', {}).get('bearish', 0)}
- 中性线索: {impact_summary.get('direction_counts', {}).get('neutral', 0)}

重点影响线索:
{chr(10).join(impact_summary.get('detail_lines', [])) if impact_summary.get('detail_lines') else '- 暂无结构化影响线索'}
""".strip()
            
            # 构建地缘政治分析提示词
            prompt = f"""
你是一位资深的地缘政治风险分析师，专门研究地缘政治事件对金融市场的影响。

请基于以下地缘政治新闻，分析对市场特别是{name}({current_code})的潜在影响：

{structured_context}

原始地缘新闻:
{formatted_news}

请从以下角度进行专业分析：

## 地缘政治风险评估
1. **当前地缘政治态势**：总结主要的地缘政治事件和冲突
2. **风险等级评估**：评估当前地缘政治风险等级（低/中/高）
3. **关键风险因素**：识别最重要的风险驱动因素

## 市场影响分析
1. **全球市场影响**：分析对全球金融市场的整体影响
2. **资产类别影响**：分析对股票、债券、商品、外汇等不同资产的影响
3. **避险情绪**：评估市场避险情绪的变化趋势

## 特定标的影响
1. **直接影响**：分析地缘政治事件对{name}的直接影响
2. **间接影响**：通过供应链、贸易、资金流等渠道的间接影响
3. **行业影响**：分析对相关行业的整体影响

## 风险预警与建议
1. **短期风险**：未来1-3个月需要关注的风险点
2. **中期影响**：未来3-12个月的潜在影响
3. **投资建议**：基于地缘政治风险的投资策略建议

## 关键监控指标
列出需要持续监控的地缘政治指标和事件

请确保分析客观、专业，避免政治立场，重点关注对市场和投资的实际影响。
"""
            
            # 调用AI进行分析
            ai_client = AIAnalyse("a")
            analysis = _call_ai_and_get_content(ai_client, prompt)
            
            if not analysis or "AI分析失败" in analysis:
                analysis = "地缘政治分析暂时不可用，请稍后重试。"
        
        logger.info("地缘政治分析师节点执行完成")
        return {"geopolitical_analysis": analysis}
        
    except Exception as e:
        logger.error(f"地缘政治分析师节点执行失败: {str(e)}")
        return {"geopolitical_analysis": f"地缘政治分析执行异常: {str(e)}"}
