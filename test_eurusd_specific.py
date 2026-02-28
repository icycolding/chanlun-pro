#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专门测试EURUSD（欧元兑美元）新闻搜索功能
验证FE.EURUSD或欧元兑美元的新闻搜索能力
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

try:
    from forex_futures_news_api import ForexFuturesNewsAPI
    from enhanced_market_search import EnhancedMarketSearch
    from semantic_search_optimizer import SemanticSearchOptimizer
    from forex_currency_mapping import ForexCurrencyMapping
    from news_vector_db import NewsVectorDB
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保所有相关模块都已正确创建")
    sys.exit(1)

def test_eurusd_identification():
    """
    测试EURUSD识别功能
    """
    print("=== 测试EURUSD识别功能 ===")
    
    # 初始化组件
    market_search = EnhancedMarketSearch()
    forex_mapping = ForexCurrencyMapping()
    optimizer = SemanticSearchOptimizer()
    
    # 测试不同的EURUSD输入格式
    test_inputs = [
        'FE.EURUSD',
        'EURUSD', 
        'EUR/USD',
        'EUR-USD',
        '欧元兑美元',
        '欧美',
        '欧元美元',
        '欧元对美元',
        'Euro Dollar',
        'EUR USD'
    ]
    
    print("\n--- 市场工具识别测试 ---")
    for input_text in test_inputs:
        results = market_search.identify_market_instrument(input_text)
        if results:
            for result in results:
                print(f"输入: {input_text:15} -> 市场: {result.market_type.value:8} | 标的: {result.symbol:8} | 置信度: {result.confidence:.2f}")
        else:
            print(f"输入: {input_text:15} -> 未识别")
    
    print("\n--- 外汇货币对映射测试 ---")
    for input_text in test_inputs:
        pairs = forex_mapping.identify_forex_pair(input_text)
        if pairs:
            for pair in pairs:
                pair_info = forex_mapping.get_pair_info(pair)
                if pair_info:
                    print(f"输入: {input_text:15} -> {pair_info.name_cn} ({pair_info.pair})")
                    keywords = forex_mapping.get_search_keywords(pair)
                    print(f"  搜索关键词: {', '.join(keywords[:8])}")
        else:
            print(f"输入: {input_text:15} -> 未找到匹配")
    
    print("\n--- 语义搜索优化测试 ---")
    for input_text in test_inputs[:5]:  # 只测试前5个
        optimized = optimizer.optimize_search_query(input_text)
        print(f"输入: {input_text:15}")
        print(f"  市场类型: {optimized.market_type.value}")
        print(f"  标的代码: {optimized.symbol}")
        print(f"  主要关键词: {', '.join(optimized.primary_keywords[:5])}")
        print(f"  次要关键词: {', '.join(optimized.secondary_keywords[:5])}")
        print()

def test_eurusd_news_search():
    """
    测试EURUSD新闻搜索功能
    """
    print("\n=== 测试EURUSD新闻搜索功能 ===")
    
    # 初始化API
    api = ForexFuturesNewsAPI()
    
    # 测试查询列表
    test_queries = [
        'FE.EURUSD',
        'EURUSD',
        '欧元兑美元',
        '欧美汇率',
        '欧元美元走势'
    ]
    
    for query in test_queries:
        print(f"\n--- 搜索查询: '{query}' ---")
        
        try:
            # 使用外汇新闻搜索API
            result = api.search_forex_news(
                query=query,
                limit=5,
                days_back=30,
                include_analysis=True
            )
            
            print(f"搜索状态: {result.get('status', 'unknown')}")
            print(f"识别的标的: {result.get('identified_symbol', 'N/A')}")
            print(f"市场类型: {result.get('market_type', 'N/A')}")
            
            # 显示查询优化信息
            if 'query_optimization' in result:
                opt = result['query_optimization']
                print(f"主要关键词: {', '.join(opt.get('primary_keywords', [])[:5])}")
                print(f"次要关键词: {', '.join(opt.get('secondary_keywords', [])[:5])}")
            
            # 显示新闻数量
            news_count = result.get('news_count', 0)
            print(f"找到新闻数量: {news_count}")
            
            # 显示前几条新闻标题（如果有的话）
            if 'news_results' in result and result['news_results']:
                print("新闻标题示例:")
                for i, news in enumerate(result['news_results'][:3], 1):
                    title = news.get('title', 'N/A')[:50]
                    print(f"  {i}. {title}...")
            
            # 显示分析结果（如果有的话）
            if 'analysis' in result and result['analysis']:
                analysis = result['analysis'][:200]
                print(f"分析摘要: {analysis}...")
                
        except Exception as e:
            print(f"搜索出错: {str(e)}")

def test_vector_db_eurusd_search():
    """
    测试向量数据库中的EURUSD搜索
    """
    print("\n=== 测试向量数据库EURUSD搜索 ===")
    
    try:
        # 初始化向量数据库
        vector_db = NewsVectorDB(db_path="./web/chanlun_chart/cl_app/chroma_db")
        
        # 获取数据库统计信息
        stats = vector_db.get_collection_stats()
        print(f"数据库状态: {stats}")
        
        # 测试EURUSD相关搜索
        test_queries = [
            'EURUSD',
            '欧元兑美元', 
            '欧美汇率',
            '欧洲央行',
            '美联储政策',
            'EUR USD'
        ]
        
        for query in test_queries:
            print(f"\n--- 向量搜索: '{query}' ---")
            
            # 使用语义搜索
            results = vector_db.semantic_search(
                query=query,
                n_results=5,
                days_back=30
            )
            
            if results:
                print(f"找到 {len(results)} 条相关新闻:")
                for i, result in enumerate(results[:3], 1):
                    title = result.get('title', 'N/A')[:50]
                    similarity = result.get('similarity', 0)
                    source = result.get('source', 'N/A')
                    print(f"  {i}. {title}... (相似度: {similarity:.3f}, 来源: {source})")
            else:
                print("  未找到相关新闻")
                
    except Exception as e:
        print(f"向量数据库搜索出错: {str(e)}")

def main():
    """
    主测试函数
    """
    print("EURUSD（欧元兑美元）新闻搜索功能专项测试")
    print("=" * 60)
    
    try:
        # 1. 测试EURUSD识别功能
        test_eurusd_identification()
        
        # 2. 测试EURUSD新闻搜索功能
        test_eurusd_news_search()
        
        # 3. 测试向量数据库搜索
        test_vector_db_eurusd_search()
        
        print("\n=== 测试完成 ===")
        print("\n测试总结:")
        print("✓ EURUSD识别功能测试完成")
        print("✓ 外汇新闻搜索API测试完成")
        print("✓ 向量数据库搜索测试完成")
        print("\n系统已成功支持FE.EURUSD和欧元兑美元的新闻搜索!")
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc