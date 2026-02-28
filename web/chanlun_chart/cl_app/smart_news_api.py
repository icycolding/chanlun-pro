#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能新闻搜索API接口

提供RESTful API接口，支持:
1. 根据股票代码或公司名称搜索相关新闻
2. 股票代码解析和映射
3. 搜索结果统计和分析
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

try:
    from .news_vector_db import NewsVectorDB
    from .smart_news_search import SmartNewsSearcher, StockCodeMapper, search_stock_news
except ImportError:
    from news_vector_db import NewsVectorDB
    from smart_news_search import SmartNewsSearcher, StockCodeMapper, search_stock_news

logger = logging.getLogger(__name__)

# 创建蓝图
smart_news_bp = Blueprint('smart_news', __name__, url_prefix='/api/smart_news')

# 全局变量
_vector_db = None
_smart_searcher = None
_stock_mapper = None

def get_vector_db():
    """获取向量数据库实例 (单例模式)"""
    global _vector_db
    if _vector_db is None:
        _vector_db = NewsVectorDB()
    return _vector_db

def get_smart_searcher():
    """获取智能搜索器实例 (单例模式)"""
    global _smart_searcher
    if _smart_searcher is None:
        vector_db = get_vector_db()
        _smart_searcher = SmartNewsSearcher(vector_db)
    return _smart_searcher

def get_stock_mapper():
    """获取股票映射器实例 (单例模式)"""
    global _stock_mapper
    if _stock_mapper is None:
        _stock_mapper = StockCodeMapper()
    return _stock_mapper

@smart_news_bp.route('/search', methods=['POST'])
def search_news():
    """
    智能新闻搜索API
    
    请求体:
    {
        "stock_input": "R:2015.HK",  // 股票代码或公司名称
        "n_results": 20,             // 返回结果数量 (可选，默认20)
        "days_back": 30,             // 搜索最近多少天 (可选，默认30)
        "include_related": true      // 是否包含相关搜索 (可选，默认true)
    }
    
    响应:
    {
        "success": true,
        "data": {
            "stock_info": {...},
            "results": [...],
            "stats": {...},
            "total_found": 10
        },
        "message": "搜索成功",
        "timestamp": "2024-01-20T10:30:00"
    }
    """
    try:
        # 解析请求参数
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请求体不能为空',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        stock_input = data.get('stock_input')
        if not stock_input:
            return jsonify({
                'success': False,
                'error': '股票代码或公司名称不能为空',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        n_results = data.get('n_results', 20)
        days_back = data.get('days_back', 30)
        include_related = data.get('include_related', True)
        
        # 参数验证
        if not isinstance(n_results, int) or n_results < 1 or n_results > 100:
            return jsonify({
                'success': False,
                'error': '结果数量必须是1-100之间的整数',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        if not isinstance(days_back, int) or days_back < 1 or days_back > 365:
            return jsonify({
                'success': False,
                'error': '搜索天数必须是1-365之间的整数',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # 执行搜索
        searcher = get_smart_searcher()
        result = searcher.search_news_by_stock(
            stock_input=stock_input,
            n_results=n_results,
            days_back=days_back,
            include_related=include_related
        )
        
        if result['success']:
            # 转换StockInfo对象为字典
            stock_info = result['stock_info']
            result['stock_info'] = {
                'code': stock_info.code,
                'name': stock_info.name,
                'exchange': stock_info.exchange,
                'market_type': stock_info.market_type,
                'original_input': stock_info.original_input,
                'aliases': stock_info.aliases
            }
            
            return jsonify({
                'success': True,
                'data': result,
                'message': f'搜索成功，找到 {result["total_found"]} 条相关新闻',
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '搜索失败'),
                'timestamp': datetime.now().isoformat()
            }), 400
    
    except Exception as e:
        logger.error(f"智能新闻搜索API异常: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'服务器内部错误: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

@smart_news_bp.route('/parse_stock', methods=['POST'])
def parse_stock():
    """
    股票代码解析API
    
    请求体:
    {
        "stock_input": "R:2015.HK"  // 股票代码或公司名称
    }
    
    响应:
    {
        "success": true,
        "data": {
            "code": "02015",
            "name": "理想汽车",
            "exchange": "HKEX",
            "market_type": "HK",
            "original_input": "R:2015.HK",
            "aliases": [...]
        },
        "message": "解析成功",
        "timestamp": "2024-01-20T10:30:00"
    }
    """
    try:
        # 解析请求参数
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请求体不能为空',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        stock_input = data.get('stock_input')
        if not stock_input:
            return jsonify({
                'success': False,
                'error': '股票代码或公司名称不能为空',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # 执行解析
        mapper = get_stock_mapper()
        stock_info = mapper.parse_stock_input(stock_input)
        
        if stock_info:
            return jsonify({
                'success': True,
                'data': {
                    'code': stock_info.code,
                    'name': stock_info.name,
                    'exchange': stock_info.exchange,
                    'market_type': stock_info.market_type,
                    'original_input': stock_info.original_input,
                    'aliases': stock_info.aliases
                },
                'message': '解析成功',
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': f'无法识别股票代码或公司名称: {stock_input}',
                'timestamp': datetime.now().isoformat()
            }), 400
    
    except Exception as e:
        logger.error(f"股票代码解析API异常: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'服务器内部错误: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

@smart_news_bp.route('/quick_search/<stock_input>', methods=['GET'])
def quick_search(stock_input: str):
    """
    快速搜索API (GET请求)
    
    URL参数:
    - stock_input: 股票代码或公司名称
    
    查询参数:
    - n_results: 返回结果数量 (可选，默认10)
    - days_back: 搜索最近多少天 (可选，默认15)
    
    响应格式同 /search 接口
    """
    try:
        # 解析查询参数
        n_results = request.args.get('n_results', 10, type=int)
        days_back = request.args.get('days_back', 15, type=int)
        
        # 参数验证
        if n_results < 1 or n_results > 50:
            return jsonify({
                'success': False,
                'error': '快速搜索结果数量必须是1-50之间的整数',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        if days_back < 1 or days_back > 90:
            return jsonify({
                'success': False,
                'error': '快速搜索天数必须是1-90之间的整数',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # 执行搜索
        vector_db = get_vector_db()
        result = search_stock_news(
            stock_input=stock_input,
            vector_db=vector_db,
            n_results=n_results,
            days_back=days_back
        )
        
        if result['success']:
            # 转换StockInfo对象为字典
            stock_info = result['stock_info']
            result['stock_info'] = {
                'code': stock_info.code,
                'name': stock_info.name,
                'exchange': stock_info.exchange,
                'market_type': stock_info.market_type,
                'original_input': stock_info.original_input,
                'aliases': stock_info.aliases
            }
            
            return jsonify({
                'success': True,
                'data': result,
                'message': f'快速搜索成功，找到 {result["total_found"]} 条相关新闻',
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '搜索失败'),
                'timestamp': datetime.now().isoformat()
            }), 400
    
    except Exception as e:
        logger.error(f"快速搜索API异常: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'服务器内部错误: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

@smart_news_bp.route('/stats', methods=['GET'])
def get_stats():
    """
    获取系统统计信息API
    
    响应:
    {
        "success": true,
        "data": {
            "total_news": 19019,
            "supported_stocks": 37,
            "supported_markets": ["HK", "US", "CN"],
            "last_updated": "2024-01-20T10:30:00"
        },
        "message": "统计信息获取成功",
        "timestamp": "2024-01-20T10:30:00"
    }
    """
    try:
        # 获取向量数据库统计
        vector_db = get_vector_db()
        total_news = 0
        if vector_db.collection:
            try:
                total_news = vector_db.collection.count()
            except:
                total_news = 0
        
        # 获取股票映射统计
        mapper = get_stock_mapper()
        supported_stocks = len(mapper.predefined_mappings)
        
        # 统计支持的市场
        supported_markets = set()
        for stock_info in mapper.predefined_mappings.values():
            supported_markets.add(stock_info.market_type)
        
        return jsonify({
            'success': True,
            'data': {
                'total_news': total_news,
                'supported_stocks': supported_stocks,
                'supported_markets': sorted(list(supported_markets)),
                'supported_exchanges': list(mapper.exchange_info.keys()) if mapper.exchange_info else [],
                'last_updated': datetime.now().isoformat()
            },
            'message': '统计信息获取成功',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"统计信息API异常: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'服务器内部错误: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

@smart_news_bp.route('/health', methods=['GET'])
def health_check():
    """
    健康检查API
    
    响应:
    {
        "success": true,
        "data": {
            "status": "healthy",
            "vector_db_status": "connected",
            "stock_mapper_status": "loaded"
        },
        "message": "服务正常",
        "timestamp": "2024-01-20T10:30:00"
    }
    """
    try:
        # 检查向量数据库状态
        vector_db_status = "disconnected"
        try:
            vector_db = get_vector_db()
            if vector_db.collection:
                vector_db_status = "connected"
        except:
            pass
        
        # 检查股票映射器状态
        stock_mapper_status = "not_loaded"
        try:
            mapper = get_stock_mapper()
            if mapper.predefined_mappings:
                stock_mapper_status = "loaded"
        except:
            pass
        
        # 判断整体状态
        overall_status = "healthy" if (vector_db_status == "connected" and stock_mapper_status == "loaded") else "degraded"
        
        return jsonify({
            'success': True,
            'data': {
                'status': overall_status,
                'vector_db_status': vector_db_status,
                'stock_mapper_status': stock_mapper_status,
                'uptime': datetime.now().isoformat()
            },
            'message': '服务正常' if overall_status == 'healthy' else '服务部分功能异常',
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"健康检查API异常: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'健康检查失败: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

# 错误处理
@smart_news_bp.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': '接口不存在',
        'timestamp': datetime.now().isoformat()
    }), 404

@smart_news_bp.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        'success': False,
        'error': '请求方法不允许',
        'timestamp': datetime.now().isoformat()
    }), 405

@smart_news_bp.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': '服务器内部错误',
        'timestamp': datetime.now().isoformat()
    }), 500

# 便捷函数
def register_smart_news_api(app):
    """注册智能新闻搜索API到Flask应用"""
    app.register_blueprint(smart_news_bp)
    logger.info("✅ 智能新闻搜索API已注册")

if __name__ == '__main__':
    # 用于测试的简单Flask应用
    from flask import Flask
    
    app = Flask(__name__)
    register_smart_news_api(app)
    
    print("🚀 智能新闻搜索API测试服务器启动")
    print("📍 API端点:")
    print("  POST /api/smart_news/search - 智能新闻搜索")
    print("  POST /api/smart_news/parse_stock - 股票代码解析")
    print("  GET  /api/smart_news/quick_search/<stock_input> - 快速搜索")
    print("  GET  /api/smart_news/stats - 系统统计")
    print("  GET  /api/smart_news/health - 健康检查")
    
    app.run(debug=True, host='0.0.0.0', port=5001)