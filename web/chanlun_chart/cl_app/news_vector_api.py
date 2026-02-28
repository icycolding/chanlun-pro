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
from cl_app.enhanced_market_search import EnhancedMarketSearch

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
            query = data.get('query')
            product_code = query['query']
            market = query['market']

            end_date = datetime.now()
            days = data.get('days', 1)
            # days = 7

            start_date = end_date - timedelta(days=days)
            # market = data.get('market', '')  # 接收 market 参数
          
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
            # print('product_code', product_code)
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
            print('news',len(search_results))
            # optimized_query = _create_optimized_search_query(query, product_code, product_info)
            # n_results = data.get('n_results', 50)
            
            # # 计算日期范围
            # from datetime import datetime, timedelta
            # end_date = datetime.now()
            # start_date = end_date - timedelta(days=days)
            
            # # 执行语义搜索
            vector_db = get_vector_db(db_path="./chroma_db")
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
            # filtered_results = sorted(
            #     search_results,
            #     key=lambda x: x.get('metadata', {}).get('published_at', ''), 
            #     reverse=True
            # )
          
            # logger.info(f"搜索完成，返回{len(filtered_results)}条结果")
            # logger.info(f"query: {query}")
            return jsonify({
                "code": 0,
                "msg": "搜索成功",
                "data": {
                    "results": search_results,
                    "total": len(search_results),
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
        
    

    # --- 智能评分辅助函数 ---

    # _calculate_smart_relevance_score函数已移除，直接使用semantic_search返回的score

    # --- 主函数 (重构版) ---

    def get_vector_news(code: str, market: str, days: int = 7, n_results: int = 50) -> List[Dict]:
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
        logger.info(f"开始为 {market}-{code} 检索新闻（优化版本）...")
        
        try:
            # 1. 获取资产基本信息
            ex = get_exchange(Market(market))
            stock_info = ex.stock_info(code)

            if not stock_info:
                logger.error(f"无法获取资产信息: {code}")
                return []

            # 2. 构建智能综合查询
            stock_name = stock_info.get('name', '')
            stock_code = stock_info.get('code', '')
            
            # 构建综合查询字符串
            query_parts = []
            market_terms = []
            
            # 添加清理后的股票名称
            if stock_name:
                clean_name = stock_name.replace('－Ｗ', '').replace('-W', '').strip()
                query_parts.append(clean_name)
            
            # 添加清理后的代码和市场术语
            print('stock_code,stock_name:', stock_code,stock_name)
            if stock_code:
                clean_code = stock_code
                if 'FE.' in clean_code:
                    clean_code = clean_code.replace('FE.', '')
                    query_parts.append(clean_code)
                    market_terms.extend(['外汇', 'forex', 'fx', '汇率', '货币政策', '央行'])
                elif 'KH.' in clean_code:
                    clean_code = clean_code.replace('KH.', '')
                    query_parts.append(clean_code)
                    market_terms.extend(['港股', '香港股市', 'Hong Kong', 'HK stock'])
                elif market == 'a':
                    query_parts.append(clean_code)
                    market_terms.extend(['A股', '沪深', '上交所', '深交所', '中国股市'])
                else:
                    query_parts.append(clean_code)
                    print('clean_code',clean_code)
                    if 'QZ.MAL8' in clean_code:
                        market_terms.extend(['METHAN', 'METHANOL'])
                    if 'CZ' in clean_code:
                        market_terms.extend(['bond', '30y','10y'])

            
            # 构建综合查询字符串
            comprehensive_query = ' '.join(query_parts)
            if market_terms:
                # 添加市场相关术语，提升搜索的语义理解
                comprehensive_query += ' ' + ' '.join(market_terms[:3])  # 限制术语数量避免查询过长
            
            logger.info(f"构建的综合查询: {comprehensive_query}")
            
            # 3. 执行单次综合向量搜索
            vector_db = get_vector_db(db_path="./chroma_db")
            from datetime import datetime, timedelta
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            print('comprehensive_query',comprehensive_query)
            # 使用更大的搜索范围以获得更好的结果多样性
            search_results = vector_db.semantic_search(
                query=comprehensive_query,
                n_results=min(n_results * 3, 150),  # 搜索更多结果用于后续智能筛选
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            if not search_results:
                logger.warning(f"未找到相关新闻: {comprehensive_query}")
                return []
            
            # 4. 去重处理（基于新闻ID）
            unique_results = {}
            for result in search_results:
                news_id = result.get('id', '')
                if news_id and news_id not in unique_results:
                    unique_results[news_id] = result
            
            deduplicated_results = list(unique_results.values())
            logger.info(f"去重后剩余 {len(deduplicated_results)} 条新闻")
            
            # 5. 两阶段排序：先按semantic_search返回的score排序取前n_results，再按时间排序
            relevance_sorted = sorted(
                deduplicated_results,
                key=lambda x: x.get('score', 0),
                reverse=True
            )[:n_results]
            
            # 然后对筛选出的结果按发布时间排序
            time_sorted_results = sorted(
                relevance_sorted,
                key=lambda x: x.get('metadata', {}).get('published_at', ''),
                reverse=True
            )
            
            # 6. 格式化最终结果
            formatted_results = []
            for result in time_sorted_results:
                formatted_result = {
                    'id': result.get('id', ''),
                    'document': result.get('document', ''),
                    'metadata': result.get('metadata', {}),
                    'score': result.get('score', 0),  # 直接使用semantic_search返回的score
                    'distance': result.get('distance', 1.0)
                }
                formatted_results.append(formatted_result)
            # print('formatted_results',formatted_results)
            logger.info(f"为 {code} 检索到 {len(formatted_results)} 条相关新闻")
            return formatted_results
            
        except Exception as e:
            logger.error(f"检索新闻时出错: {e}", exc_info=True)
            return []

    
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
            frequency = data.get('frequency', 'd')  # 获取分析周期参数，默认为日线
            selected_nodes = data.get('selected_nodes', [])  # 获取用户选择的AI分析节点
            n_results = 50
            days = data.get('days', 1)
            # days = 7
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
            
            # # 创建优化的搜索查询
            optimized_query,product_info = _create_optimized_search_query(query, product_code)
            # name = product_info.get('name_en')
            # # query = '美联储或欧洲央行的货币政策、利率决定、通胀和就业数据对欧元兑美元汇率的影响'
            # # 计算日期范围
            # print('name',name)
          
            # from datetime import datetime, timedelta
            # end_date = datetime.now()
            # start_date = end_date - timedelta(days=days)
            # # 执行语义搜索
            vector_db = get_vector_db(db_path="./chroma_db")
            ex = get_exchange(Market(current_market))
            stock_info = ex.stock_info(current_code)
            name = stock_info.get('name')
            # print('optimized_query',query,optimized_query)
            # search_results = vector_db.semantic_search(
            #     query=name,
            #     n_results=n_results,
            #     keywords='',
            #     start_date=start_date.isoformat(),
            #     end_date=end_date.isoformat()
            # )
            
            # # 按发布时间排序，最新的新闻优先
            # news_list = sorted(
            #     search_results,
            #     key=lambda x: x.get('metadata', {}).get('published_at', ''), 
            #     reverse=True
            # )
            # # print('news_list',news_list)
            # logger.info(f"搜索到 {len(news_list)} 条相关新闻")
            # data = request.get_json()
            # query = data.get('query')
            # product_code = query['query']
            # market = query['market']
            # days = 2
            print('current_code',current_code)
            news_list = get_vector_news(current_code, current_market,days)
            print('news_list222',len(news_list))
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
            # # economic_data_list = json.dumps(economic_data_list)
            # market_map = {'SH': 'a', 'SZ': 'a', 'BJ': 'a', 'HK': 'hk', 'US': 'us'}
            # market_prefix = product_code_clean.split('.')[0]
            # market_type = market_map.get(market_prefix, 'futures' if '.' in product_code_clean else 'a')
            # ex = get_exchange(Market(market_type))
            # stock_info = ex.stock_info(current_code)
        

            print('name1111',name)
            # 调用大模型生成研究报告
            print('current_market:', current_market, 'current_code:', current_code)
            print(f'使用向量搜索获取到 {len(formatted_news_list)} 条新闻')
            # if 'QZ.MAL8' in c:
            #     name = '中证1000期货'
            summary = _generate_ai_market_summary(economic_data_list,formatted_news_list, current_market, current_code,name, frequency, selected_nodes)
            
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
            data = request.get_json() or {}
            days = data.get('days', 1)
            
            # 参数验证
            if not isinstance(days, int) or days < 1 or days > 30:
                return jsonify({
                    "code": 400,
                    "msg": "天数参数无效，请选择1-30天",
                    "data": None
                })
            
            logger.info(f"开始生成{days}天的每日新闻总结")
            
            # 获取指定天数内的所有新闻
            vector_db = get_vector_db(db_path="./chroma_db")
            
            # 计算日期范围
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # 获取新闻数据
            all_news = vector_db.get_news_by_date_range(
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                limit=5000
            )
            
            if not all_news:
                return jsonify({
                    "code": 400,
                    "msg": f"未找到{days}天内的新闻数据",
                    "data": None
                })
            
            logger.info(f"获取到{len(all_news)}条新闻，开始分析")
            
            # 分析新闻中提到的重要标的
            analyzed_targets = _analyze_important_targets(all_news)
            
            # 转换新闻格式
            formatted_news_list = []
            for news in all_news:
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
            print('formatted_news_list',formatted_news_list)
            # 生成每日新闻总结
            summary = _generate_daily_news_summary(
                news_list=formatted_news_list,
                analyzed_targets=analyzed_targets,
                days=days
            )
            
            # 保存总结到数据库
            summary_id = None
            try:
                from chanlun.db import db
                summary_data = {
                    'title': f"{days}天每日新闻总结",
                    'content': summary,
                    'market': 'all',
                    'code': 'daily_summary',
                    'summary_type': 'daily_news_summary'
                }
                summary_id = db.market_summary_insert(summary_data)
                logger.info(f"每日新闻总结已保存到数据库，ID: {summary_id}")
            except Exception as db_error:
                logger.error(f"保存每日新闻总结到数据库失败: {str(db_error)}")
            
            return jsonify({
                "code": 0,
                "msg": "生成成功",
                "data": {
                    "summary": summary,
                    "summary_id": summary_id,
                    "analyzed_targets": analyzed_targets,
                    "news_count": len(formatted_news_list)
                }
            })
            
        except Exception as e:
            logger.error(f"生成每日新闻总结失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"生成失败: {str(e)}",
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
请基于以下{days}天的金融市场新闻内容，生成一份全面深入的新闻分析报告。

## 基本信息
- 时间范围：过去{days}天
- 原始新闻总数：{len(news_list)}条
- 筛选后金融新闻：{len(filtered_news)}条
- 报告时间：{current_date}

## 新闻内容
{news_content}

{mentioned_products_info}

## 输出要求
请按以下格式生成全面的分析报告：

# {days}天金融市场新闻深度分析报告

## 执行摘要
[提供整体市场概况和核心要点的简明总结，包括主要趋势、关键事件和市场影响]

## 重大新闻事件深度分析
[详细分析每个重要新闻事件，包括：
- 事件背景和详细描述
- 涉及的关键参与者和机构
- 对相关行业和市场的潜在影响
- 与历史类似事件的对比
- 后续发展的可能方向]

## 行业板块动态分析
[按行业分类深入分析：
- 各行业的主要新闻和发展趋势
- 行业内公司的表现差异
- 政策变化对行业的影响
- 技术创新和商业模式变化
- 竞争格局的变化]

## 宏观经济环境分析
[分析宏观经济因素：
- 货币政策和财政政策变化
- 经济指标的变化趋势
- 国际经济环境的影响
- 地缘政治因素的作用]

## 市场情绪和资金流向
[分析市场情绪变化：
- 投资者情绪的变化趋势
- 资金流向的特点
- 风险偏好的变化
- 市场预期的调整]

## 关注产品专项分析
[如果新闻中提及关注产品，进行专项分析：
- 相关新闻对产品的具体影响
- 价格变动的原因分析
- 基本面变化情况
- 技术面表现特征
- 未来走势的关键因素]

## 风险因素识别
[识别和分析潜在风险：
- 系统性风险因素
- 行业特定风险
- 个股风险点
- 外部环境风险]

## 关键时间节点
[按时间顺序梳理重要事件，并分析其连锁反应和累积效应]

## 市场展望和关注要点
[基于新闻分析，提出未来需要关注的要点：
- 即将到来的重要事件
- 需要跟踪的关键指标
- 可能的市场转折点
- 长期趋势的判断]

## 分析要求：
1. 进行深度分析和专业解读，不仅仅是新闻整理
2. 保持客观专业的分析视角
3. 详细阐述因果关系和影响机制
4. 结合历史数据和趋势进行对比分析
5. 提供多角度的分析视角
6. 重点关注新闻之间的关联性和系统性影响
7. 对关注产品进行重点分析，结合价格变动进行深入解读
8. 识别市场机会和风险点
9. 分析内容要具有前瞻性和指导价值
10. 确保分析的逻辑性和完整性
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
        
        # 如果质量合格或已达到最大修正次数，进行最终整合
        logger.info("分析质量合格或已达最大修正次数，开始最终整合")
        
        # 这是最关键的一步：它的输入是前面所有专家的结论
        prompt = f"""
你是一位顶级的首席投资策略师。你的任务是整合你团队中专家的分析报告，形成一份逻辑连贯、观点明确、包含具体策略的最终研究报告。

**你的输入：**

1. **【宏观分析师的报告】**:
{state.get('macro_analysis', '暂无宏观分析')}

2. **【经济数据分析师的报告】**:
{state.get('economic_analysis', '暂无经济数据分析')}

3. **【技术指标分析师的报告】**:
{state.get('technical_analysis', '暂无技术分析')}

4. **【缠论结构专家的报告】**:
{state.get('chanlun_analysis', '暂无缠论分析')}

5. **【财务分析师的报告】**:
{state.get('financial_analysis', '暂无财务分析')}

6. **【地缘政治分析师的报告】**:
{state.get('geopolitical_analysis', '暂无地缘政治分析')}

**你的任务和输出要求：**

1. **综合摘要 (Executive Summary)**: 用2-3句话总结当前市场的核心矛盾与机会点。
2. **逻辑整合分析**:
   - **识别并分析观点冲突**: 明确指出各份报告中的一致点和矛盾点（例如：宏观偏空但缠论看涨，或财务基本面强劲但技术面疲弱，或地缘政治风险与基本面分析的冲突）。
   - **构建核心逻辑链**: 基于你的专业判断，解释应如何理解这些矛盾。哪个因素是主导？哪个是次要？特别关注地缘政治事件对市场的短期和长期影响。
   - **推导核心观点**: 基于上述逻辑，明确给出对后市走势的最终判断（看涨/看跌/震荡），并考虑地缘政治风险对投资策略的影响。
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
            "needs_revision": False,
            "revision_target_node": ""
        }
        
    except Exception as e:
        logger.error(f"增强版首席策略师节点异常: {str(e)}")
        return {
            "final_report": f"最终报告生成异常: {str(e)}",
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


def _generate_ai_market_summary(economic_data_list: List[Dict],news_list: List[Dict], current_market: str = '', current_code: str = '',name: str = '', frequency: str = 'd', selected_nodes: List[str] = None) -> str:
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
        str: 生成的研究报告
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
            return "错误：没有选择有效的分析节点。"
        
        # 添加首席策略师节点（支持反思修正）
        try:
            workflow.add_node("chief_strategist", enhanced_chief_strategist_node)
        except Exception as e:
            logger.error(f"添加首席策略师节点失败: {str(e)}")
            return f"工作流配置错误：{str(e)}"
        
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
            return f"工作流配置错误：{str(e)}"
        
        # 从启动节点分发到用户选择的分析师（并行执行）
        try:
            for node_name in active_nodes:
                workflow.add_edge("start_analysis", node_name)
                logger.info(f"添加启动边: start_analysis -> {node_name}")
        except Exception as e:
            logger.error(f"添加启动边失败: {str(e)}")
            return f"工作流配置错误：{str(e)}"
        
        # 所有选择的分析师完成后，汇聚到首席策略师
        try:
            for node_name in active_nodes:
                workflow.add_edge(node_name, "chief_strategist")
                logger.info(f"添加汇聚边: {node_name} -> chief_strategist")
        except Exception as e:
            logger.error(f"添加汇聚边失败: {str(e)}")
            return f"工作流配置错误：{str(e)}"
        
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
            return f"工作流配置错误：{str(e)}"
        
        # 编译成可执行应用
        try:
            app = workflow.compile()
        except Exception as e:
            logger.error(f"工作流编译失败: {str(e)}")
            return f"工作流编译错误：{str(e)}"
        
        # 2. 获取地缘政治新闻数据
        geopolitical_news = []
        try:
            vector_db = get_vector_db()
            if vector_db:
                geopolitical_news = _search_geopolitical_news(7)  # 搜索7天内的地缘政治新闻
                logger.info(f"获取到{len(geopolitical_news)}条地缘政治相关新闻")
            else:
                logger.warning("无法获取向量数据库实例，跳过地缘政治新闻搜索")
        except Exception as e:
            logger.error(f"获取地缘政治新闻失败: {str(e)}")
        
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


def _search_geopolitical_news(days: int = 7) -> List[Dict]:
    """
    搜索地缘政治相关新闻
    
    Args:
        days: 搜索天数，默认7天
        
    Returns:
        List[Dict]: 地缘政治相关新闻列表
    """
    try:
        from datetime import datetime, timedelta
        
        # 地缘政治关键词列表
        geopolitical_keywords = [
            "战争", "冲突", "军事", "制裁", "贸易战", "地缘政治",
            "俄乌", "俄罗斯", "乌克兰", "中美", "台海", "朝鲜", 
            "伊朗", "以色列", "巴勒斯坦", "中东", "欧盟制裁",
            "war", "conflict", "military", "sanctions", "trade war", 
            "geopolitical", "russia", "ukraine", "china", "usa", 
            "taiwan", "north korea", "iran", "israel", "palestine"
        ]
        
        # 计算搜索时间范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 获取向量数据库实例
        vector_db = get_vector_db(db_path="./chroma_db")
        
        geopolitical_news = []
        
        # 对每个关键词进行搜索
        for keyword in geopolitical_keywords:
            try:
                search_results = vector_db.semantic_search(
                    query=keyword,
                    n_results=20,  # 每个关键词最多20条
                    keywords='',
                    start_date=start_date.strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d')
                )
                
                # 过滤和去重
                for news in search_results:
                    news_id = news.get('metadata', {}).get('news_id', '')
                    # 检查是否已存在（简单去重）
                    if not any(existing.get('metadata', {}).get('news_id') == news_id for existing in geopolitical_news):
                        # 检查新闻内容是否真的与地缘政治相关
                        title = news.get('metadata', {}).get('title', '').lower()
                        content = news.get('document', '').lower()
                        
                        # 简单的相关性检查
                        if any(kw.lower() in title or kw.lower() in content for kw in geopolitical_keywords):
                            geopolitical_news.append(news)
                            
            except Exception as e:
                logger.warning(f"搜索关键词 '{keyword}' 时出错: {str(e)}")
                continue
        
        # 按重要性和时间排序
        geopolitical_news.sort(
            key=lambda x: (
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
            
            # 构建地缘政治分析提示词
            prompt = f"""
你是一位资深的地缘政治风险分析师，专门研究地缘政治事件对金融市场的影响。

请基于以下地缘政治新闻，分析对市场特别是{name}({current_code})的潜在影响：

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