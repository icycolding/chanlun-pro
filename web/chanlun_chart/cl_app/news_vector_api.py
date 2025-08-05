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
from flask import request, jsonify
from flask_login import login_required
import logging

from .news_vector_db import get_vector_db

# 配置日志
logger = logging.getLogger(__name__)


def _optimize_currency_search(query: str) -> str:
    """
    根据资产类型优化搜索查询
    - 外汇(如EURUSD, FE.EURUSD): 搜索汇率、央行、货币政策相关新闻
    - 贵金属商品(如黄金): 搜索商品、贵金属、避险、通胀相关新闻  
    - 股票指数: 搜索股市、行业、公司相关新闻
    
    Args:
        query: 原始搜索查询
        
    Returns:
        str: 优化后的搜索查询
    """
    import re
    
    query_clean = query.strip()
    query_upper = query_clean.upper()
    
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
            '券商', '基金', '机构', '散户'
        ]
        
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
            
            if not query:
                return jsonify({
                    "code": 400,
                    "msg": "缺少查询参数 'query'",
                    "data": None
                })
            
            # 优化搜索查询
            query = _optimize_currency_search(query)
            n_results = data.get('n_results', 50)
            days = data.get('days', 1)
            
            # 计算日期范围
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # 执行语义搜索
            vector_db = get_vector_db()
            logger.info(f'搜索查询: {query}, 日期范围: {start_date.strftime("%Y-%m-%d")} 到 {end_date.strftime("%Y-%m-%d")}')
            
            # 使用向量数据库的时间过滤功能
            print('query_new', query,n_results)
            query = 'EUR'
            search_results = vector_db.semantic_search(
                query=query,
                n_results=n_results,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            # 按发布时间排序，最新的新闻优先（降序排列）
            filtered_results = sorted(
                search_results,
                key=lambda x: x.get('metadata', {}).get('published_at', ''), 
                reverse=True
            )
            
            logger.info(f"搜索完成，返回{len(filtered_results)}条结果")
            
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
    

    @app.route("/api/news/semantic_search_advanced", methods=["POST"])
    @login_required
    def semantic_search_news_advanced():
        """
        高级语义搜索新闻API - 两阶段筛选
        
        请求参数:
        {
            "query": "搜索查询文本",
            "initial_results": 200,  # 第一阶段获取的新闻数量，默认200
            "final_results": 50,     # 第二阶段筛选的新闻数量，默认50
            "days": 7,               # 可选，搜索最近几天的新闻，默认7天
            "relevance_threshold": 0.7,  # 相关性阈值，默认0.7
            "filters": {             # 可选，过滤条件
                "source": "新浪财经",
                "category": "股票",
                "market_relevance": {"$gte": 0.5}
            }
        }
        
        返回:
        {
            "code": 0,
            "msg": "搜索成功",
            "data": {
                "results": [...],
                "total": 50,
                "initial_count": 200,
                "final_count": 50,
                "query": "搜索查询文本",
                "relevance_stats": {
                    "min_distance": 0.1,
                    "max_distance": 0.9,
                    "avg_distance": 0.5
                },
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
            
            if not query:
                return jsonify({
                    "code": 400,
                    "msg": "缺少查询参数 'query'",
                    "data": None
                })
            
            # 优化货币对搜索逻辑
            query = _optimize_currency_search(query)
            print('query_advanced',query)
            # 获取参数
            initial_results = data.get('initial_results', 200)
            final_results = data.get('final_results', 50)
            days = data.get('days', 7)
            relevance_threshold = data.get('relevance_threshold', 0.7)
            filters = data.get('filters', {})
            
            # 参数验证
            if initial_results < final_results:
                return jsonify({
                    "code": 400,
                    "msg": "初始结果数量不能小于最终结果数量",
                    "data": None
                })
            
            # 添加日期过滤条件
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # ChromaDB的where条件格式要求
            # 由于ChromaDB不支持复杂的多字段查询，我们先获取所有结果，然后在Python中过滤
            chroma_filters = None
            
            # 如果用户提供了简单的过滤条件，尝试使用
            if filters and len(filters) == 1:
                # 只有一个过滤条件时，可以直接传递给ChromaDB
                for key, value in filters.items():
                    if isinstance(value, dict) and len(value) == 1:
                        # 简单的比较操作
                        chroma_filters = {key: value}
                        break
            
            # 第一阶段：获取大量候选新闻
            vector_db = get_vector_db()
            print(f'第一阶段搜索: 查询="{query}", 获取{initial_results}条新闻')
            print(f'搜索日期范围: {start_date.strftime("%Y-%m-%d")} 到 {end_date.strftime("%Y-%m-%d")}')
            
            # 获取更多结果以便后续过滤
            search_limit = max(initial_results * 2, 500)  # 获取更多结果用于过滤
            
            initial_search_results = vector_db.semantic_search(
                query=query,
                n_results=search_limit,
                filters=chroma_filters,  # 使用简化的过滤条件
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            if not initial_search_results:
                return jsonify({
                    "code": 404,
                    "msg": "未找到相关新闻",
                    "data": {
                        "results": [],
                        "total": 0,
                        "initial_count": 0,
                        "final_count": 0,
                        "query": query
                    }
                })
            
            # Python级别的过滤：应用日期和其他过滤条件
            print(f'应用Python级别过滤: 从{len(initial_search_results)}条结果开始过滤')
            
            # 应用日期过滤
            date_filtered_results = []
            for result in initial_search_results:
                metadata = result.get('metadata', {})
                published_at = metadata.get('published_at')
                
                if published_at:
                    try:
                        # 解析发布时间
                        if isinstance(published_at, str):
                            pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                        else:
                            pub_date = published_at
                        
                        # 检查是否在日期范围内
                        if start_date.date() <= pub_date.date() <= end_date.date():
                            date_filtered_results.append(result)
                    except (ValueError, TypeError) as e:
                        # 如果日期解析失败，保留结果
                        print(f'日期解析失败: {published_at}, 错误: {e}')
                        date_filtered_results.append(result)
                else:
                    # 如果没有发布时间，保留结果
                    date_filtered_results.append(result)
            
            # 应用其他过滤条件
            python_filtered_results = []
            for result in date_filtered_results:
                metadata = result.get('metadata', {})
                should_include = True
                
                # 应用用户提供的过滤条件
                for filter_key, filter_value in filters.items():
                    if filter_key == 'published_at':
                        continue  # 日期过滤已经处理过了
                    
                    metadata_value = metadata.get(filter_key)
                    
                    if isinstance(filter_value, dict):
                        # 处理比较操作符
                        for op, op_value in filter_value.items():
                            if op == '$gte' and metadata_value is not None:
                                if float(metadata_value) < float(op_value):
                                    should_include = False
                                    break
                            elif op == '$lte' and metadata_value is not None:
                                if float(metadata_value) > float(op_value):
                                    should_include = False
                                    break
                            elif op == '$gt' and metadata_value is not None:
                                if float(metadata_value) <= float(op_value):
                                    should_include = False
                                    break
                            elif op == '$lt' and metadata_value is not None:
                                if float(metadata_value) >= float(op_value):
                                    should_include = False
                                    break
                    else:
                        # 直接值比较
                        if metadata_value != filter_value:
                            should_include = False
                            break
                    
                    if not should_include:
                        break
                
                if should_include:
                    python_filtered_results.append(result)
            
            # 限制到初始结果数量
            initial_search_results = python_filtered_results[:initial_results]
            
            print(f'过滤完成: 日期过滤后{len(date_filtered_results)}条 -> 条件过滤后{len(python_filtered_results)}条 -> 截取{len(initial_search_results)}条')
            
            if not initial_search_results:
                return jsonify({
                    "code": 404,
                    "msg": "未找到符合条件的相关新闻",
                    "data": {
                        "results": [],
                        "total": 0,
                        "initial_count": 0,
                        "final_count": 0,
                        "query": query,
                        "date_range": f"最近{days}天",
                        "search_period": {
                            "start_date": start_date.strftime('%Y-%m-%d'),
                            "end_date": end_date.strftime('%Y-%m-%d')
                        }
                    }
                })
            
            # 第二阶段：基于相关性筛选最相关的新闻
            print(f'第二阶段筛选: 从{len(initial_search_results)}条新闻中筛选{final_results}条最相关的')
            
            # 按相关性排序（distance越小越相关）
            filtered_results = []
            for result in initial_search_results:
                if result.get('distance') is not None:
                    # 计算相关性分数（1 - distance，使得分数越高越相关）
                    relevance_score = 1 - result['distance']
                    result['relevance_score'] = relevance_score
                    
                    # 应用相关性阈值
                    if relevance_score >= relevance_threshold:
                        filtered_results.append(result)
                else:
                    # 如果没有distance信息，保留结果但设置默认相关性
                    result['relevance_score'] = 0.5
                    filtered_results.append(result)
            
            # 按相关性分数排序（降序）
            filtered_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
            
            # 取前N条最相关的新闻
            final_results_list = filtered_results[:final_results]
            
            # 按时间排序（保持相关性排序的同时，相同相关性的按时间排序）
            final_results_list.sort(key=lambda x: (
                -x.get('relevance_score', 0),  # 相关性降序
                -int(datetime.fromisoformat(x.get('metadata', {}).get('published_at', '1970-01-01')).timestamp())  # 时间降序
            ))
            
            # 计算相关性统计信息
            distances = [r.get('distance', 0) for r in final_results_list if r.get('distance') is not None]
            relevance_scores = [r.get('relevance_score', 0) for r in final_results_list]
            
            relevance_stats = {
                "min_distance": min(distances) if distances else 0,
                "max_distance": max(distances) if distances else 0,
                "avg_distance": sum(distances) / len(distances) if distances else 0,
                "min_relevance": min(relevance_scores) if relevance_scores else 0,
                "max_relevance": max(relevance_scores) if relevance_scores else 0,
                "avg_relevance": sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
            }
            
            print(f'筛选完成: 初始{len(initial_search_results)}条 -> 过滤后{len(filtered_results)}条 -> 最终{len(final_results_list)}条')
            print(f'相关性统计: 平均相关性={relevance_stats["avg_relevance"]:.3f}, 最高={relevance_stats["max_relevance"]:.3f}')
            
            return jsonify({
                "code": 0,
                "msg": "高级搜索成功",
                "data": {
                    "results": final_results_list,
                    "total": len(final_results_list),
                    "initial_count": len(initial_search_results),
                    "filtered_count": len(filtered_results),
                    "final_count": len(final_results_list),
                    "query": query,
                    "relevance_stats": relevance_stats,
                    "filters": filters,
                    "date_range": f"最近{days}天",
                    "search_period": {
                        "start_date": start_date.strftime('%Y-%m-%d'),
                        "end_date": end_date.strftime('%Y-%m-%d')
                    },
                    "parameters": {
                        "initial_results": initial_results,
                        "final_results": final_results,
                        "relevance_threshold": relevance_threshold
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"高级语义搜索失败: {str(e)}")
            return jsonify({
                "code": 500,
                "msg": f"搜索失败: {str(e)}",
                "data": None
            })

    @app.route("/api/news/market_summary", methods=["POST"])
    @login_required
    def generate_market_summary():
        """
        生成研究报告API
        
        请求体:
        {
            "news_list": [新闻列表]
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
            if not data or 'news_list' not in data:
                return jsonify({
                    "code": 400,
                    "msg": "缺少必要参数 news_list",
                    "data": None
                })
            
            news_list = data['news_list']
            if not news_list or len(news_list) == 0:
                return jsonify({
                    "code": 400,
                    "msg": "新闻列表不能为空",
                    "data": None
                })
            
            # 获取当前标的信息
            current_market = data.get('current_market', '')
            current_code = data.get('current_code', '')
            
            # 调用大模型生成研究报告
            # print('news_list',news_list)
            print('current_market:', current_market, 'current_code:', current_code)
            summary = _generate_ai_market_summary(news_list, current_market, current_code)
            
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
    生成MACD和波动率技术指标分析
    
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
        klines = exchange.klines(code, 'd')  # 获取日线数据
        
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
        
        # 综合交易建议（基于MACD和历史波动率）
        analysis_text += "\n## 综合交易建议\n"
        
        try:
            # 基于MACD和历史波动率的综合建议
            if 'macd_signal' in locals() and 'current_volatility' in locals():
                # 将年化波动率转换为日波动率用于止损计算
                daily_vol_for_stop = current_volatility / np.sqrt(252) if 'current_volatility' in locals() else 2.0
                
                if macd_signal == "金叉买入":
                    if 'volatility_ratio' in locals() and volatility_ratio < 1.3:  # 正常或低波动率
                        analysis_text += "- **建议**: 考虑买入，MACD金叉且波动率正常，风险可控\n"
                        analysis_text += f"- **止损建议**: 设置{daily_vol_for_stop * 2:.1f}%的止损（基于2倍日波动率）\n"
                    elif 'volatility_ratio' in locals() and volatility_ratio < 2.0:  # 高波动率
                        analysis_text += "- **建议**: 谨慎买入，MACD金叉但波动率偏高，建议减少仓位\n"
                        analysis_text += f"- **止损建议**: 设置{daily_vol_for_stop * 1.5:.1f}%的紧密止损\n"
                    else:  # 极高波动率或无波动率数据
                        analysis_text += "- **风险警告**: MACD金叉但波动率极高或数据不足，建议观望\n"
                        
                elif macd_signal == "死叉卖出":
                    if 'volatility_ratio' in locals() and volatility_ratio < 1.3:
                        analysis_text += "- **建议**: 考虑卖出，MACD死叉且波动率正常，趋势明确\n"
                    elif 'volatility_ratio' in locals() and volatility_ratio < 2.0:
                        analysis_text += "- **建议**: 积极卖出，MACD死叉且波动率偏高，下跌风险加大\n"
                    else:
                        analysis_text += "- **建议**: 立即止损，MACD死叉且波动率极高，风险极大\n"
                        
                else:  # 震荡或其他信号
                    if 'volatility_ratio' in locals() and volatility_ratio > 2.0:
                        analysis_text += "- **风险警告**: 当前波动率极高，建议观望或减少仓位\n"
                        analysis_text += f"- **风险控制**: 如需交易，严格控制仓位，止损设为{daily_vol_for_stop * 1.5:.1f}%\n"
                    elif 'volatility_ratio' in locals() and volatility_ratio > 1.5:
                        analysis_text += "- **建议**: 波动率偏高，建议等待MACD信号更加明确\n"
                        analysis_text += f"- **止损参考**: 建议止损幅度{daily_vol_for_stop * 2:.1f}%\n"
                    else:
                        analysis_text += "- **建议**: 综合MACD信号和波动率水平，可适度参与\n"
                        analysis_text += f"- **止损参考**: 建议止损幅度{daily_vol_for_stop * 2.5:.1f}%\n"
                        
                # 基于波动率分位数的额外建议
                if 'volatility_percentile' in locals():
                    if volatility_percentile > 90:
                        analysis_text += "- **市场状态**: 波动率处于历史高位（>90%分位），市场情绪激烈\n"
                    elif volatility_percentile < 10:
                        analysis_text += "- **市场状态**: 波动率处于历史低位（<10%分位），市场相对平静\n"
                        
            else:
                analysis_text += "- **建议**: 技术指标数据不足，建议等待更多信号确认\n"
                
        except Exception as e:
            analysis_text += f"- **建议生成异常**: {str(e)}\n"
        
        return analysis_text if analysis_text else "技术指标分析生成失败"
        
    except ImportError as e:
        logger.error(f"导入技术分析模块失败: {str(e)}")
        return "技术分析模块导入失败，请检查系统配置"
    except Exception as e:
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


def _generate_ai_market_summary(news_list: List[Dict], current_market: str = '', current_code: str = '') -> str:
    """
    使用大模型生成研究报告
    
    Args:
        news_list: 新闻列表
        current_market: 当前市场代码 (如: a, hk, us, fx等)
        current_code: 当前标的代码
        
    Returns:
        str: 生成的研究报告
    """
    try:
        from datetime import datetime
        import sys
        import os
        
        # 添加项目路径到sys.path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)
        
        from chanlun.tools.ai_analyse import AIAnalyse
        from chanlun.zixuan import ZiXuan
        from chanlun.exchange import get_exchange
        from chanlun.base import Market
        
        # 准备新闻内容
        news_content = ""
        current_date = datetime.now().strftime("%Y-%m-%d")
        
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
        
        # 构建市场和标的信息
        market_info = ""
        price_info = ""
        
        # 获取用户关注产品的价格信息
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
        
        if current_market and current_code:
            market_names = {
                'a': 'A股市场',
                'hk': '港股市场', 
                'us': '美股市场',
                'fx': '外汇市场',
                'futures': '期货市场',
                'currency': '数字货币市场'
            }
            market_name = market_names.get(current_market, f'{current_market}市场')
            
            # 获取current_code对应的名称
            code_name = current_code
            try:
                market_enum_map = {
                    'a': Market.A,
                    'hk': Market.HK,
                    'us': Market.US,
                    'fx': Market.FX,
                    'futures': Market.FUTURES,
                    'currency': Market.CURRENCY
                }
                if current_market in market_enum_map:
                    exchange = get_exchange(market_enum_map[current_market])
                    stock_info = exchange.stock_info(current_code)
                    if stock_info and 'name' in stock_info:
                        code_name = stock_info['name']
            except Exception as e:
                logger.warning(f"获取股票名称失败: {str(e)}")
                
            market_info = f"\n\n当前关注标的: {code_name} ({current_code}) - {market_name}\n请特别关注与该标的相关的新闻和市场影响。"
        
        # 构建提示词
        prompt = f"""请基于以下{current_date}的新闻信息，生成一份专业的研究报告。{market_info}

新闻内容:
{news_content}

请按以下要求生成研究报告:
1. 分析当日主要市场事件和趋势
2. 识别对金融市场可能产生的影响
3. 重点关注外汇、股市、债市等相关信息
4. 如果有当前关注标的，请特别分析相关影响
5. 提供简洁明了的投资观点和风险提示
6. 总结长度控制在500-800字
7. 使用专业但易懂的语言

请直接输出研究报告内容，不需要额外的格式说明。"""
        
        logger.info(f"正在调用大模型生成研究报告，新闻数量: {len(news_list)}")
        
        # 使用AIAnalyse类调用大模型
        ai_analyse = AIAnalyse(current_market if current_market else "a")  # 使用当前市场参数
        result = ai_analyse.req_openrouter_ai_model(prompt)
        # result=''
        # market_summary = "test"
        if result.get('ok', False):
            summary = result.get('msg', '').strip()
            if summary:
                # 将价格信息添加到研究报告的开头
                market_summary = summary + price_info
                logger.info("研究报告生成成功")
            else:
                logger.warning("大模型返回空内容")
                market_summary = "抱歉，暂时无法生成研究报告，请稍后重试。" + price_info
        else:
            error_msg = result.get('msg', '未知错误')
            logger.error(f"调用大模型失败: {error_msg}")
            market_summary = f"抱歉，大模型服务调用失败: {error_msg}" + price_info
        
        # 如果有具体标的代码，添加主页截屏图片和缠论技术分析
        if current_code and current_market and market_summary and not market_summary.startswith("抱歉"):
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
            
            # # 添加MACD和波动率技术分析
            # try:
            #     logger.info(f"正在为{current_code}生成MACD和波动率分析")
            #     technical_analysis = _generate_technical_indicators_analysis(current_code, current_market)
            #     if technical_analysis:
            #         market_summary += f"\n\n## 技术指标分析\n{technical_analysis}"
            #         logger.info("MACD和波动率分析添加成功")
            #     else:
            #         logger.warning("技术指标分析生成失败")
            #         market_summary += "\n\n## 技术指标分析\n暂时无法生成技术指标分析，请稍后重试。"
            # except Exception as e:
            #     logger.error(f"技术指标分析异常: {str(e)}")
            #     market_summary += f"\n\n## 技术指标分析\n技术指标分析异常: {str(e)}"
            
            # 添加缠论技术分析
            try:
                logger.info(f"正在为{current_code}生成缠论技术分析")
                chanlun_result = ai_analyse.analyse(code=current_code, frequency='d')
                # chanlun_result =''
                if chanlun_result.get('ok', False):
                    chanlun_analysis = chanlun_result.get('msg', '').strip()
                    if chanlun_analysis:
                        market_summary += f"\n\n## 缠论技术分析\n{chanlun_analysis}"
                        logger.info("缠论技术分析添加成功")
                    else:
                        logger.warning("缠论分析返回空内容")
                        market_summary += "\n\n## 缠论技术分析\n暂时无法生成技术分析，请稍后重试。"
                else:
                    error_msg = chanlun_result.get('msg', '未知错误')
                    logger.warning(f"缠论分析失败: {error_msg}")
                    market_summary += f"\n\n## 缠论技术分析\n技术分析生成失败: {error_msg}"
                    
            except Exception as e:
                logger.error(f"缠论技术分析异常: {str(e)}")
                market_summary += f"\n\n## 缠论技术分析\n技术分析异常: {str(e)}"
        
        return market_summary
            
    except ImportError as e:
        logger.error(f"导入AIAnalyse模块失败: {str(e)}")
        return "系统配置错误，无法调用AI服务。"
    except Exception as e:
        logger.error(f"生成研究报告时发生错误: {str(e)}")
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