#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻向量数据库API模块
提供向量数据库相关的API接口，包括语义搜索、相似新闻查找、情感分析等功能
"""

import datetime
import json
import os
import time
import base64
from typing import Dict, List, Optional, Any
# from fix_chroma_timezone import response
from flask import request, jsonify
from flask_login import login_required
import logging
# from chanlun.tools.ai_analyze import req_llm_ai_model # 移到函数内部，按需导入
from chanlun.tools.ai_analyse import AIAnalyse  # 原始AI分析类
from .news_vector_db import get_vector_db
from chanlun.exchange import get_exchange, Market
from datetime import datetime, timedelta

# 配置日志
logger = logging.getLogger(__name__)


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


def _get_product_info(product_code: str) -> Dict[str, Any]:
    """
    根据产品代码获取产品信息，包括中英文名称、类型等。
    现在增加了从交易所动态获取信息的功能。
    
    Args:
        product_code: 产品代码，如EURUSD, FE.EURUSD, GOLD等
        
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
    print('product_code_clean',product_code_clean)
    if product_code_clean in product_mapping:
        info = product_mapping[product_code_clean].copy()
        info['is_futures'] = '.' in product_code_clean
        info['original_code'] = product_code_clean
        return info

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
                return info
    
    # 尝试从交易所动态获取信息 (借鉴 zixuan.py)
    try:
        # 简单的市场类型推断
        market_map = {'SH': 'a', 'SZ': 'a', 'BJ': 'a', 'HK': 'hk', 'US': 'us'}
        market_prefix = product_code_clean.split('.')[0]
        market_type = market_map.get(market_prefix, 'futures' if '.' in product_code_clean else 'a')

        ex = get_exchange(Market(market_type))
        stock_info = ex.stock_info(product_code_clean)
        if stock_info and stock_info.get('name'):
            return {
                'name_cn': stock_info.get('name'),
                'name_en': '', # 交易所信息通常不含英文名
                'type': market_type,
                'symbol': stock_info.get('code'),
                'description': f"{stock_info.get('name')} ({stock_info.get('code')})",
                'keywords': [stock_info.get('name'), stock_info.get('code')],
                'is_futures': market_type == 'futures',
                'original_code': product_code_clean
            }
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

        return {
            'name_cn': f'{base_cn}{quote_cn}',
            'name_en': f'{base_en} {quote_en}',
            'type': 'forex',
            'base_currency': base_curr,
            'quote_currency': quote_curr,
            'description': f'{base_cn}兑{quote_cn}汇率',
            'keywords': [base_cn, quote_cn, f'{base_cn}{quote_cn}', product_code_clean],
            'is_futures': False,
            'original_code': product_code_clean
        }

    # 如果都找不到，返回一个基于输入代码的默认字典
    return {
        'name_cn': product_code_clean,
        'name_en': product_code_clean,
        'type': 'unknown',
        'description': f'未知产品: {product_code_clean}',
        'keywords': [product_code_clean],
        'is_futures': False,
        'original_code': product_code_clean
    }
    
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




def register_vector_api_routes(app):
    """
    注册向量数据库相关的API路由
    
    Args:
        app: Flask应用实例
    """
    
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
            
            # 查询数据
            summary_list = db.market_summary_query(
                limit=limit,
                offset=offset,
                market=market,
                code=code,
                start_date=start_date,
                end_date=end_date
            )
            
            # 统计总数
            total_count = db.market_summary_count(
                market=market,
                code=code,
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
            klines = ex.klines(code, frequency)
            
            if klines is None or len(klines) == 0:
                return jsonify({
                    'error': '无法获取K线数据'
                })
            
            # 获取缠论配置
            cl_config = query_cl_chart_config(market, code)
            
            # 获取缠论数据
            cd_list = web_batch_get_cl_datas(market, code, {frequency: klines}, cl_config)
            print(f"获取到缠论数据列表长度: {len(cd_list)}")
            
            if not cd_list or len(cd_list) == 0:
                return jsonify({
                    'error': '无法获取缠论数据'
                })
                
            cd = cd_list[0]
            print(f"缠论数据对象类型: {type(cd)}")
            print(f"缠论数据对象: {cd}")
            
            if not cd:
                return jsonify({
                    'error': '缠论数据对象为空'
                })
            
            # 获取K线数据用于时间戳转换
            cd_klines = cd.get_klines()
            print(f"获取到缠论K线数据数量: {len(cd_klines) if cd_klines else 0}")
            
            if not cd_klines:
                return jsonify({
                    'error': '无法获取缠论K线数据'
                })
            
            # 创建时间戳到索引的映射
            time_to_index = {}
            for i, kline in enumerate(cd_klines):
                time_to_index[kline.date] = i
            print(f"时间索引映射创建完成，共 {len(time_to_index)} 个时间点")
            
            def convert_to_chart_points(elements, element_type='fx'):
                """将缠论元素转换为图表坐标点"""
                chart_elements = []
                
                if not elements:
                    return chart_elements
                
                for element in elements:
                    try:
                        # 检查元素类型
                        if isinstance(element, str):
                            print(f"警告: {element_type}元素是字符串类型: {element}")
                            continue
                            
                        if element_type == 'fx':
                            # 分型处理 - 检查新格式(k.date)或旧格式(dt)
                            element_time = None
                            if hasattr(element, 'k') and hasattr(element.k, 'date'):
                                element_time = element.k.date
                            elif hasattr(element, 'dt'):
                                element_time = element.dt
                            else:
                                print(f"警告: FX元素缺少时间属性(k.date或dt): {element}")
                                continue
                                
                            if not hasattr(element, 'val'):
                                print(f"警告: FX元素缺少val属性: {element}")
                                continue
                                
                            time_idx = time_to_index.get(element_time)
                            if time_idx is not None:
                                chart_elements.append({
                                    'points': [{
                                        'time': time_idx,
                                        'price': element.val
                                    }],
                                    'text': getattr(element, 'fx', 'FX')
                                })
                        
                        elif element_type in ['bi', 'xd']:
                            # 笔和线段处理
                            if not hasattr(element, 'start') or not hasattr(element, 'end'):
                                print(f"警告: {element_type}元素缺少start/end属性: {element}")
                                continue
                                
                            # BI/XD对象的start和end是FX（分型）对象，时间通过start.k.date访问
                            start_time = None
                            start_val = None
                            end_time = None
                            end_val = None
                            
                            # 获取start时间和价格
                            if hasattr(element.start, 'k') and hasattr(element.start.k, 'date'):
                                start_time = element.start.k.date
                            elif hasattr(element.start, 'dt'):
                                start_time = element.start.dt
                            else:
                                print(f"警告: {element_type}.start缺少时间属性: index: {getattr(element.start, 'index', 'N/A')} type: {getattr(element.start, 'fx', 'N/A')} date : {getattr(element.start, 'k', {}).get('date', 'N/A')} val: {getattr(element.start, 'val', 'N/A')} done: {getattr(element.start, 'done', 'N/A')}")
                                continue
                                
                            if hasattr(element.start, 'val'):
                                start_val = element.start.val
                            else:
                                print(f"警告: {element_type}.start缺少val属性: {element.start}")
                                continue
                                
                            # 获取end时间和价格
                            if hasattr(element.end, 'k') and hasattr(element.end.k, 'date'):
                                end_time = element.end.k.date
                            elif hasattr(element.end, 'dt'):
                                end_time = element.end.dt
                            else:
                                print(f"警告: {element_type}.end缺少时间属性: {element.end}")
                                continue
                                
                            if hasattr(element.end, 'val'):
                                end_val = element.end.val
                            else:
                                print(f"警告: {element_type}.end缺少val属性: {element.end}")
                                continue
                                
                            start_idx = time_to_index.get(start_time)
                            end_idx = time_to_index.get(end_time)
                            
                            if start_idx is not None and end_idx is not None:
                                chart_elements.append({
                                    'points': [
                                        {'time': start_idx, 'price': start_val},
                                        {'time': end_idx, 'price': end_val}
                                    ],
                                    'linestyle': 0
                                })
                        
                        elif element_type == 'zs':
                            # 中枢处理
                            if not hasattr(element, 'start') or not hasattr(element, 'end'):
                                print(f"警告: ZS元素缺少start/end属性: {element}")
                                continue
                                
                            # ZS对象的start和end是FX（分型）对象，时间通过start.k.date访问
                            start_time = None
                            end_time = None
                            
                            if hasattr(element.start, 'k') and hasattr(element.start.k, 'date'):
                                start_time = element.start.k.date
                            elif hasattr(element.start, 'dt'):
                                start_time = element.start.dt
                            else:
                                print(f"警告: ZS元素start缺少时间属性: {element.start}")
                                continue
                                
                            if hasattr(element.end, 'k') and hasattr(element.end.k, 'date'):
                                end_time = element.end.k.date
                            elif hasattr(element.end, 'dt'):
                                end_time = element.end.dt
                            else:
                                print(f"警告: ZS元素end缺少时间属性: {element.end}")
                                continue
                                
                            if not hasattr(element, 'zg') or not hasattr(element, 'zd'):
                                print(f"警告: ZS元素缺少zg/zd属性: {element}")
                                continue
                                
                            start_idx = time_to_index.get(start_time)
                            end_idx = time_to_index.get(end_time)
                            
                            if start_idx is not None and end_idx is not None:
                                chart_elements.append({
                                    'points': [
                                        {'time': start_idx, 'price': element.zg},
                                        {'time': end_idx, 'price': element.zd}
                                    ]
                                })
                        
                        elif element_type == 'mmd':
                            # 买卖点处理 - 现在element是字典格式
                            if isinstance(element, dict):
                                if 'dt' not in element or 'line' not in element:
                                    print(f"警告: MMD元素缺少dt/line属性: {element}")
                                    continue
                                    
                                time_idx = time_to_index.get(element['dt'])
                                if time_idx is not None:
                                    # 从line对象获取价格信息
                                    line = element['line']
                                    price = line.end.val if hasattr(line.end, 'val') else (line.high if line.type == 'up' else line.low)
                                    chart_elements.append({
                                        'points': [{
                                            'time': time_idx,
                                            'price': price
                                        }],
                                        'text': element.get('name', 'MMD')
                                    })
                            else:
                                # 兼容原有格式
                                if not hasattr(element, 'dt') or not hasattr(element, 'val'):
                                    print(f"警告: MMD元素缺少dt/val属性: {element}")
                                    continue
                                    
                                time_idx = time_to_index.get(element.dt)
                                if time_idx is not None:
                                    chart_elements.append({
                                        'points': [{
                                            'time': time_idx,
                                            'price': element.val
                                        }],
                                        'text': getattr(element, 'name', 'MMD')
                                    })
                        
                        elif element_type == 'bc':
                            # 背驰处理 - 现在element是字典格式
                            if isinstance(element, dict):
                                if 'dt' not in element or 'line' not in element:
                                    print(f"警告: BC元素缺少dt/line属性: {element}")
                                    continue
                                    
                                time_idx = time_to_index.get(element['dt'])
                                if time_idx is not None:
                                    # 从line对象获取价格信息
                                    line = element['line']
                                    price = line.end.val if hasattr(line.end, 'val') else (line.high if line.type == 'up' else line.low)
                                    chart_elements.append({
                                        'points': [{
                                            'time': time_idx,
                                            'price': price
                                        }],
                                        'text': f"{element.get('name', 'BC')}背驰"
                                    })
                            else:
                                # 兼容原有格式
                                if not hasattr(element, 'dt') or not hasattr(element, 'val'):
                                    print(f"警告: BC元素缺少dt/val属性: {element}")
                                    continue
                                    
                                time_idx = time_to_index.get(element.dt)
                                if time_idx is not None:
                                    chart_elements.append({
                                        'points': [{
                                            'time': time_idx,
                                            'price': element.val
                                        }],
                                        'text': f"{getattr(element, 'type', 'BC')}背驰"
                                    })
                                
                    except Exception as e:
                        print(f"转换{element_type}元素时出错: {e}")
                        continue
                
                return chart_elements
            
            # 获取各种缠论元素
            result = {}
            
            # 分型
            try:
                fxs = cd.get_fxs()
                print(f"获取到 {len(fxs) if fxs else 0} 个分型")
                if fxs and len(fxs) > 0:
                    print(f"第一个分型类型: {type(fxs[0])}, 内容: {fxs[0]}")
                result['fxs'] = convert_to_chart_points(fxs, 'fx')
            except Exception as e:
                print(f"获取分型数据错误: {e}")
                result['fxs'] = []
            
            # 笔
            try:
                bis = cd.get_bis()
                print(f"获取到 {len(bis) if bis else 0} 个笔")
                if bis and len(bis) > 0:
                    print(f"第一个笔类型: {type(bis[0])}, 内容: {bis[0]}")
                result['bis'] = convert_to_chart_points(bis, 'bi')
            except Exception as e:
                print(f"获取笔数据错误: {e}")
                result['bis'] = []
            
            # 线段
            try:
                xds = cd.get_xds()
                print(f"获取到 {len(xds) if xds else 0} 个线段")
                if xds and len(xds) > 0:
                    print(f"第一个线段类型: {type(xds[0])}, 内容: {xds[0]}")
                result['xds'] = convert_to_chart_points(xds, 'xd')
            except Exception as e:
                print(f"获取线段数据错误: {e}")
                result['xds'] = []
            
            # 笔中枢
            try:
                bi_zss = cd.get_bi_zss()
                print(f"获取到 {len(bi_zss) if bi_zss else 0} 个笔中枢")
                result['bi_zss'] = convert_to_chart_points(bi_zss, 'zs')
            except Exception as e:
                print(f"获取笔中枢数据错误: {e}")
                result['bi_zss'] = []
            
            # 线段中枢
            try:
                xd_zss = cd.get_xd_zss()
                print(f"获取到 {len(xd_zss) if xd_zss else 0} 个线段中枢")
                result['xd_zss'] = convert_to_chart_points(xd_zss, 'zs')
            except Exception as e:
                print(f"获取线段中枢数据错误: {e}")
                result['xd_zss'] = []
            
            # 买卖点 - 从笔和线段中获取
            try:
                mmds = []
                # 从笔中获取买卖点
                bis = cd.get_bis()
                for bi in bis:
                    if hasattr(bi, 'line_mmds'):
                        bi_mmds = bi.line_mmds()
                        for mmd_name in bi_mmds:
                            mmds.append({
                                'dt': bi.end.k.date,
                                'name': mmd_name,
                                'type': 'bi',
                                'line': bi
                            })
                
                # 从线段中获取买卖点
                xds = cd.get_xds()
                for xd in xds:
                    if hasattr(xd, 'line_mmds'):
                        xd_mmds = xd.line_mmds()
                        for mmd_name in xd_mmds:
                            mmds.append({
                                'dt': xd.end.k.date,
                                'name': mmd_name,
                                'type': 'xd',
                                'line': xd
                            })
                
                print(f"获取到 {len(mmds)} 个买卖点")
                result['mmds'] = convert_to_chart_points(mmds, 'mmd')
            except Exception as e:
                print(f"获取买卖点数据错误: {e}")
                result['mmds'] = []
            
            # 背驰 - 从笔和线段中获取
            try:
                bcs = []
                # 从笔中获取背驰
                bis = cd.get_bis()
                for bi in bis:
                    if hasattr(bi, 'line_bcs'):
                        bi_bcs = bi.line_bcs()
                        for bc_name in bi_bcs:
                            bcs.append({
                                'dt': bi.end.k.date,
                                'name': bc_name,
                                'type': 'bi',
                                'line': bi
                            })
                
                # 从线段中获取背驰
                xds = cd.get_xds()
                for xd in xds:
                    if hasattr(xd, 'line_bcs'):
                        xd_bcs = xd.line_bcs()
                        for bc_name in xd_bcs:
                            bcs.append({
                                'dt': xd.end.k.date,
                                'name': bc_name,
                                'type': 'xd',
                                'line': xd
                            })
                
                print(f"获取到 {len(bcs)} 个背驰")
                result['bcs'] = convert_to_chart_points(bcs, 'bc')
            except Exception as e:
                print(f"获取背驰数据错误: {e}")
                result['bcs'] = []
            
            return jsonify(result)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"获取缠论数据失败详细错误: {error_details}")
            return jsonify({
                'error': f'获取缠论数据失败: {str(e)}',
                'details': error_details
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
            query = data.get('query')
            product_code = query['query']
            market = query['market']

            end_date = datetime.now()
            days = data.get('days', 1)
            days = 7

            start_date = end_date - timedelta(days=days)
            # market = data.get('market', '')  # 接收 market 参数
            print('market', market)
            print('product_code', product_code)
            print('query', query)
            if not query:
                return jsonify({
                    "code": 400,
                    "msg": "缺少查询参数 'query'",
                    "data": None
                })

            market_types = {
                "a": "stock",
                "hk": "stock",
                "fx": "stock",
                "us": "stock",
                "futures": "futures",
                "ny_futures": "futures",
                "currency": "crypto",
                "currency_spot": "crypto",
            }
            market_type = market_types.get(market, 'a')  # 默认为 stock

            product_info = {}
            print('product_code', product_code)
            # if product_code:
            #     # try:

            #     ex = get_exchange(Market(market))
            #     stock_info = ex.stock_info(product_code)
            #     if stock_info:
            #         product_info = {
            #             'name': stock_info.get('name'),
            #             'code': stock_info.get('code'),
            #             'market': market_type
            #         }
            #     # except Exception as e:
            #     #     logger.warning(f"通过交易所获取 {product_code} 信息失败: {e}")
            #     #     # 如果交易所查询失败，回退到静态信息获取
            #     #     product_info = _get_product_info(product_code or query)
                
            # product_info = _get_product_info(product_code)
            # print('product_info',product_info)
            # # 创建优化的搜索查询

            search_results = get_vector_news(product_code, market,days)
            # print('news',len(news))
            # optimized_query = _create_optimized_search_query(query, product_code, product_info)
            # n_results = data.get('n_results', 50)
            
            # # 计算日期范围
            # from datetime import datetime, timedelta
            # end_date = datetime.now()
            # start_date = end_date - timedelta(days=days)
            
            # # 执行语义搜索
            # vector_db = get_vector_db()
            # logger.info(f'搜索查询: {optimized_query}, 日期范围: {start_date.strftime("%Y-%m-%d")} 到 {end_date.strftime("%Y-%m-%d")}')
            
            # # 使用向量数据库的时间过滤功能
            # print('query_new', optimized_query,n_results)
            # # query = 'EUR'
            # search_results = vector_db.semantic_search(
            #     query=optimized_query,
            #     n_results=n_results,
            #     start_date=start_date.isoformat(),
            #     end_date=end_date.isoformat()
            # )
            
            # 按发布时间排序，最新的新闻优先（降序排列）
            filtered_results = sorted(
                search_results,
                key=lambda x: x.get('metadata', {}).get('published_at', ''), 
                reverse=True
            )
          
            logger.info(f"搜索完成，返回{len(filtered_results)}条结果")
            logger.info(f"query: {query}")
            return jsonify({
                "code": 0,
                "msg": "搜索成功",
                "data": {
                    "results": filtered_results,
                    "total": len(filtered_results),
                    "query": query,
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
    from typing import Dict, Any, Union

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
        
    

    # --- 辅助函数 2: 混合搜索执行器 ---

    def _execute_hybrid_search(
        query: str,
        vector_db: Any,
        search_plan,
        days_ago: int = 7,
        n_results: int = 50
    ) -> List[Dict]:
        """
        使用AI生成的搜索计划，执行高级的混合搜索。
        这是之前设计的 `semantic_search_reimagined` 函数的内部版本。
        """
        from datetime import datetime, timedelta

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_ago)
        
        # 【修正点3】合并中英文关键词用于过滤
        # all_keywords = list(set(search_plan.get('keywords_zh', []) + search_plan.get('keywords_en', [])))
        
        # logger.info(f"执行混合搜索: 查询='{search_plan['primary_semantic_query']}', 关键词={all_keywords}")
        # print('all_keywords', all_keywords)
        # 【修正点4】调用你之前重构好的、支持混合搜索的 `semantic_search` 方法
        # 我们假设它现在接收 `keywords` 参数
        search_results = vector_db.semantic_search(
            query=query,
            n_results=n_results,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            keywords=search_plan,
        )
        
        return search_results


    # --- 主函数 (重构版) ---

    def get_vector_news(code: str, market: str, days: int = 7, n_results: int = 50) -> List[Dict]:
        """
        【已升级】根据资产代码，智能地获取相关向量数据库新闻。

        流程:
        1. 获取资产基本信息。
        2. 调用LLM生成最优化的搜索计划（语义查询+关键词）。
        3. 使用该计划执行混合搜索，获取最相关的新闻。

        Args:
            code (str): 资产代码 (e.g., "FE.EURUSD").
            market (str): 市场代码 (e.g., "fx").
            days (int): 检索最近N天的新闻。
            n_results (int): 返回的新闻数量。

        Returns:
            List[Dict]: 搜索到的新闻结果列表。
        """
        logger.info(f"开始为 {market}-{code} 智能检索新闻...")
        
        # --- 步骤1: 准备资产信息 ---
        try:
            market_types = {
                "a": "A股", "hk": "港股", "fx": "外汇", "us": "美股",
                "futures": "期货", "ny_futures": "期货",
                "currency": "数字货币", "currency_spot": "数字货币",
            }
            market_type = market_types.get(market, '股票')  # 使用更具描述性的类别

            # 假设这些函数存在且能正常工作
            ex = get_exchange(Market(market))
            stock_info = ex.stock_info(code)

            if not stock_info:
                logger.error(f"无法获取资产信息: {code}")
                return []

            product_info = {
                'name': stock_info.get('name'),
                'code': stock_info.get('code'),
                'category': market_type # 使用描述性类别
            }
        except Exception as e:
            logger.error(f"准备资产信息时出错: {e}")
            return []

        # --- 步骤2: AI生成搜索计划 ---
        # search_plan = generate_search_keywords_with_llm(product_info, market)
        # print('search_plan', search_plan)
        optimized_query = ''
        # for key in search_plan:
        #     optimized_query += f' OR ({key})'
        # --- 步骤3: 执行搜索 ---
        # query = 'eur'
        # query =  stock_info.get('name')
        optimized_query = ''
        vector_db = get_vector_db()
        search_results = _execute_hybrid_search(
            query=stock_info.get('name'),
            vector_db=vector_db,
            search_plan=optimized_query,
            days_ago=days,
            n_results=n_results
        )
        print('search_results', search_results)
        logger.info(f"为 {code} 检索到 {len(search_results)} 条相关新闻。")
        return search_results


    @app.route("/api/news/market_summary", methods=["POST"])
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
            data = request.get_json()
            if not data:
                return jsonify({
                    "code": 400,
                    "msg": "请求体不能为空",
                    "data": None
                })
            
            # 获取搜索参数
            query = data.get('query', '')
            current_market = data.get('current_market', '')
            current_code = data.get('current_code', '')
            product_code = data.get('product_code', '')
            n_results = 50
            days = data.get('days', 1)
            days = 7
            # 如果没有提供查询，尝试使用产品代码或标的代码构建查询
            if not query:
                if product_code:
                    query = product_code
                elif current_code:
                    query = current_code
                else:
                    return jsonify({
                        "code": 400,
                        "msg": "缺少必要参数：query、product_code、或current_code至少需要提供一个",
                        "data": None
                    })
            
            # 使用向量数据库搜索相关新闻
            logger.info(f"开始搜索新闻，查询: {query}, 产品代码:{current_market} {product_code}, 结果数量: {n_results}, 天数: {days}")
            
            # 创建优化的搜索查询
            optimized_query,product_info = _create_optimized_search_query(query, product_code)
            name = product_info.get('name_en')
            # query = '美联储或欧洲央行的货币政策、利率决定、通胀和就业数据对欧元兑美元汇率的影响'
            # 计算日期范围
            query = 'eur'
            required_keywords = [
                "EUR/USD", "EURUSD", "欧元美元", "欧美", 
                "美联储", "Fed", "欧央行", "ECB", 
                "欧元", "美元","EUR","USD"
            ]
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            print('query',query)
            # 执行语义搜索
            vector_db = get_vector_db()
            print('optimized_query',query,optimized_query)
            search_results = vector_db.semantic_search(
                query=optimized_query,
                n_results=n_results,
                keywords='',
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            # 按发布时间排序，最新的新闻优先
            news_list = sorted(
                search_results,
                key=lambda x: x.get('metadata', {}).get('published_at', ''), 
                reverse=True
            )
            # print('news_list',news_list)
            logger.info(f"搜索到 {len(news_list)} 条相关新闻")
            
            if not news_list:
                return jsonify({
                    "code": 400,
                    "msg": "未找到相关新闻，请尝试调整搜索条件",
                    "data": None
                })
            
            # 转换新闻格式以适配现有的报告生成函数
            formatted_news_list = []
            for news in news_list:
                metadata = news.get('metadata', {})
                formatted_news = {
                    'title': metadata.get('title', ''),
                    'body': news.get('document', ''),
                    'content': news.get('document', ''),
                    'published_at': metadata.get('published_at', ''),
                    'source': metadata.get('source', ''),
                    'category': metadata.get('category', ''),
                    'sentiment_score': metadata.get('sentiment_score', 0),
                    'importance_score': metadata.get('importance_score', 0),
                    'news_id': metadata.get('news_id', '')
                }
                formatted_news_list.append(formatted_news)
            # 使用新的函数获取经济数据，支持外汇对智能识别
            economic_data_list = _get_economic_data_by_product(
                product_info=product_info, 
                product_code=product_code, 
                limit=1000
            )
            print('economic_data_list',len(economic_data_list))
            # economic_data_list = json.dumps(economic_data_list)

            # 调用大模型生成研究报告
            print('current_market:', current_market, 'current_code:', current_code)
            print(f'使用向量搜索获取到 {len(formatted_news_list)} 条新闻')
            summary = _generate_ai_market_summary(economic_data_list,formatted_news_list, current_market, current_code)
            
            # 保存研究报告到数据库
            summary_id = None
            try:
                from chanlun.db import db
                summary_data = {
                    'title': f"{current_market}-{current_code} 研究报告" if current_market and current_code else "研究报告",
                    'content': summary,
                    'market': current_market,
                    'code': current_code,
                    'summary_type': 'market_analysis'
                }
                summary_id = db.market_summary_insert(summary_data)
                logger.info(f"研究报告已保存到数据库，ID: {summary_id}")
            except Exception as db_error:
                logger.error(f"保存研究报告到数据库失败: {str(db_error)}")
            
            return jsonify({
                "code": 0,
                "msg": "生成成功",
                "data": {
                    "summary": summary,
                    "summary_id": summary_id
                }
            })
            
        except Exception as e:
            logger.error(f"生成研究报告失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"生成失败: {str(e)}",
                "data": None
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
            vector_db = get_vector_db()
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
            vector_db = get_vector_db()
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
            vector_db = get_vector_db()
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
            vector_db = get_vector_db()
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
            vector_db = get_vector_db()
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
            vector_db = get_vector_db()
            
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
        
        if market not in market_enum_map:
            return "不支持的市场类型"
        
        # 获取交易所和K线数据
        exchange = get_exchange(market_enum_map[market])
        print('code_tec',code,exchange)
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
    current_market: str         # 当前市场
    current_code: str           # 当前代码
    
    # 各个节点分析后生成的结果
    macro_analysis: Optional[str]
    economic_analysis: Optional[str]  # 经济数据分析结果
    technical_analysis: Optional[str] 
    chanlun_analysis: Optional[str]
    
    # 最终的报告
    final_report: Optional[str]


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
    """格式化新闻内容"""
    news_content = ""
    for i, news in enumerate(news_list[:10], 1):  # 限制最多10条新闻
        title = news.get('title', '无标题')
        body = news.get('body', news.get('content', '无内容'))
        published_at = news.get('published_at', '未知时间')
        source = news.get('source', '未知来源')
        
        news_content += f"\n{i}. 标题: {title}\n"
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


def _get_chanlun_analysis(code: str, market: str) -> str:
    """获取缠论分析"""
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
        chanlun_result = ai_analyse.analyse(code=code, frequency='d')
        
        if chanlun_result.get('ok', False):
            analysis = chanlun_result.get('msg', '').strip()
            return analysis if analysis else "缠论分析返回空内容"
        else:
            error_msg = chanlun_result.get('msg', '未知错误')
            return f"缠论分析失败: {error_msg}"
            
    except Exception as e:
        logger.error(f"缠论分析异常: {str(e)}")
        return f"缠论分析异常: {str(e)}"


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
        vector_db_instance = get_vector_db()

        # --- 第一阶段：因子提取 ---
        logger.info("阶段1：提取驱动因子")
        factor_prompt = f"""
你是一位敏锐的市场分析师。请阅读以下今日新闻，并识别出影响‘{current_code}’的3-5个最核心的驱动因子。
这些因子应该是具体的、可搜索的概念（例如：‘美联储利率预期’、‘欧元区通胀数据’、‘地缘政治风险’）。
请以JSON列表的格式返回这些因子，例如：["美联储鹰派言论", "德国PMI数据疲软", "俄乌局势紧张"]。

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
        vector_db = get_vector_db()
        
        def search_factor(factor):
            return factor, vector_db.semantic_search(
                query=factor,   
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
                    historical_context_text += f"- {doc.get('content', '')}\n"
            else:
                historical_context_text += "- 未找到相关历史新闻。\n"

        # --- 第三阶段：综合分析与生成 ---
        logger.info("阶段3：进行综合分析并生成报告")
        synthesis_prompt = f"""
你是一位顶级的宏观策略师，请为 {current_code} 撰写一份宏观分析备忘录。

**输入信息:**

1.  **今日核心新闻:**
    {news_content}

2.  **识别出的核心驱动因子:**
    {', '.join(factors) if factors else '未能识别出特定因子'}

3.  **各因子的历史新闻背景:**
    {historical_context_text}

**分析任务与要求:**

1.  **因子分析 (Factor-by-Factor Analysis):**
    -   对于每个识别出的因子，结合今日新闻和历史背景，分析其当前的影响力与历史有何不同？（例如：市场对'美联储鹰派言论'的反应是否比过去更敏感/迟钝？）
    -   这个因子目前是利好、利空还是中性？

2.  **综合判断 (Synthesized View):**
    -   将所有因子的分析整合起来，当前哪个因子是主导市场的核心矛盾？
    -   这些因子共同作用下，市场的整体宏观情绪是偏向乐观、悲观还是谨慎？

3.  **后市展望 (Outlook):**
    -   基于以上分析，对 {current_code} 的短期（1-3天）走势做出预判（看涨/看跌/震荡）。
    -   简要说明你的主要逻辑依据。

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
        ai_client = AIAnalyse(state['current_market'] or "fx")
        
        if not economic_data:
            return {"economic_analysis": "暂无经济数据可供分析"}
        print('economic_data',economic_data)
        # 构建经济数据分析提示词
        economic_prompt = f"""
你是一位资深的宏观经济分析师，专注于外汇市场分析。请基于以下两国经济数据，进行深入的经济分析。

**分析标的**: {current_code}

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
   - 基于经济数据分析，判断汇率的可能走向
   - 识别关键的经济数据发布时点和市场关注焦点
   - 提供基于经济基本面的汇率交易建议

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
        analysis = _get_chanlun_analysis(
            state['current_code'], state['current_market']
        )
        return {"chanlun_analysis": analysis}
        
    except Exception as e:
        logger.error(f"缠论专家节点异常: {str(e)}")
        return {"chanlun_analysis": f"缠论分析异常: {str(e)}"}


def chief_strategist_node(state: ReportGenerationState) -> Dict:
    """首席策略师节点：整合所有分析，形成最终报告"""
    logger.info(">> 正在执行：首席策略师节点")
    
    try:
        import sys
        import os
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.tools.ai_analyse import AIAnalyse
        
        # 这是最关键的一步：它的输入是前面所有专家的结论
        prompt = f"""
你是一位顶级的首席投资策略师。你的任务是整合你团队中四位专家的分析报告，形成一份逻辑连贯、观点明确、包含具体策略的最终研究报告。

**你的输入：**

1. **【宏观分析师的报告】**:
{state['macro_analysis']}

2. **【经济数据分析师的报告】**:
{state.get('economic_analysis', '暂无经济数据分析')}

3. **【技术指标分析师的报告】**:
{state['technical_analysis']}

4. **【缠论结构专家的报告】**:
{state['chanlun_analysis']}

**你的任务和输出要求：**

1. **综合摘要 (Executive Summary)**: 用2-3句话总结当前市场的核心矛盾与机会点。
2. **逻辑整合分析**:
   - **识别并分析观点冲突**: 明确指出三份报告中的一致点和矛盾点（例如：宏观偏空但缠论看涨）。
   - **构建核心逻辑链**: 基于你的专业判断，解释应如何理解这些矛盾。哪个因素是主导？哪个是次要？（例如：认为短期宏观利空是噪音，长期缠论结构才是主导趋势）。
   - **推导核心观点**: 基于上述逻辑，明确给出对后市走势的最终判断（看涨/看跌/震荡）。
3. **具体交易策略 (Actionable Strategy)**:
   - **入场条件**: 应该在什么情况下考虑入场？（例如：等待价格回调至xxx区域）
   - **止损位**: 策略失效的关键价位在哪里？
   - **目标位**: 主要的盈利目标区间在哪里？
4. **风险提示**: 明确指出该策略面临的最大风险是什么。

请确保你的报告行文流畅、逻辑严密，直接输出这份最终的研究报告。
"""
        
        ai_client = AIAnalyse(state['current_market'] or "a")
        main_report = _call_ai_and_get_content(ai_client, prompt)
        
        # 构建最终报告：主报告 + 附件
        final_report = main_report
        
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
        
        final_report += "="*80 + "\n"
        final_report += "*以上附件为各专家的详细分析报告，供参考*\n"
        
        return {"final_report": final_report}
        
    except Exception as e:
        logger.error(f"首席策略师节点异常: {str(e)}")
        return {"final_report": f"最终报告生成异常: {str(e)}"}


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


def _generate_ai_market_summary(economic_data_list: List[Dict],news_list: List[Dict], current_market: str = '', current_code: str = '') -> str:
    """
    使用LangGraph工作流生成高质量、逻辑性强的研究报告
    
    Args:
        news_list: 新闻列表
        current_market: 当前市场代码 (如: a, hk, us, fx等)
        current_code: 当前标的代码
        
    Returns:
        str: 生成的研究报告
    """
    try:
        from langgraph.graph import StateGraph, END
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
        
        if not (current_market and current_code):
            return "错误：生成高质量报告需要提供具体的市场和代码。"
        
        logger.info(f"开始使用LangGraph工作流生成报告，市场: {current_market}, 代码: {current_code}")
        
        # 1. 创建工作流图
        workflow = StateGraph(ReportGenerationState)
        
        # 添加节点
        workflow.add_node("macro_analyst", macro_analyst_node)
        workflow.add_node("economic_data_analyst", economic_data_analyst_node)
        workflow.add_node("technical_analyst", technical_analyst_node)
        workflow.add_node("chanlun_expert", chanlun_expert_node)
        workflow.add_node("chief_strategist", chief_strategist_node)
        
        # 定义边的连接关系 (工作流程)
        workflow.set_entry_point("macro_analyst")
        workflow.add_edge("macro_analyst", "economic_data_analyst")
        workflow.add_edge("economic_data_analyst", "technical_analyst")
        workflow.add_edge("technical_analyst", "chanlun_expert")
        workflow.add_edge("chanlun_expert", "chief_strategist")
        workflow.add_edge("chief_strategist", END)  # 策略师完成后，流程结束
        
        # 编译成可执行应用
        app = workflow.compile()
        
        # 2. 定义初始状态
        initial_state = ReportGenerationState(
            original_news=news_list,
            economic_data=economic_data_list,
            current_market=current_market,
            current_code=current_code,
            macro_analysis=None,
            economic_analysis=None,
            technical_analysis=None,
            chanlun_analysis=None,
            final_report=None
        )
        
        # 3. 运行工作流
        logger.info("开始执行LangGraph工作流...")
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
            
            for market in supported_markets:
                try:
                    zx = ZiXuan(market)
                    # 获取所有自选组的股票
                    all_zx_stocks = zx.query_all_zs_stocks()
                    
                    # 收集所有股票代码
                    market_codes = []
                    for zx_group in all_zx_stocks:
                        for stock in zx_group['stocks']:
                            market_codes.append(stock['code'])
                    
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
        
        # 将价格信息添加到基础报告
        market_summary = base_report + price_info
        
        
        logger.info("LangGraph工作流执行完成，报告生成成功")
        return market_summary
            
    except ImportError as e:
        logger.error(f"导入LangGraph或相关模块失败: {str(e)}")
        return "系统配置错误，无法调用LangGraph工作流。请检查依赖安装。"
    except Exception as e:
        logger.error(f"LangGraph工作流执行时发生错误: {str(e)}")
        return f"生成研究报告时发生错误: {str(e)}"


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