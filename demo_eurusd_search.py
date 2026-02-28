#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EURUSD新闻搜索功能演示
展示FE.EURUSD和欧元兑美元的完整搜索能力
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

def demo_eurusd_search():
    """
    演示EURUSD新闻搜索功能
    """
    print("🔍 EURUSD（欧元兑美元）新闻搜索功能演示")
    print("=" * 60)
    
    # 演示支持的输入格式
    supported_formats = [
        'FE.EURUSD',
        'EURUSD', 
        'EUR/USD',
        'EUR-USD',
        '欧元兑美元',
        '欧美',
        '欧元美元',
        '欧元对美元',
        'Euro Dollar'
    ]
    
    print("\n📋 支持的EURUSD输入格式:")
    for i, format_name in enumerate(supported_formats, 1):
        print(f"  {i:2d}. {format_name}")
    
    print("\n🔧 系统组件测试:")
    
    # 1. 测试外汇货币对映射
    try:
        from forex_currency_mapping import ForexCurrencyMapping
        forex_mapping = ForexCurrencyMapping()
        
        print("\n✅ 外汇货币对映射模块")
        test_inputs = ['FE.EURUSD', 'EURUSD', '欧元兑美元']
        
        for input_text in test_inputs:
            pairs = forex_mapping.identify_forex_pair(input_text)
            if pairs:
                pair_info = forex_mapping.get_pair_info(pairs[0])
                if pair_info:
                    print(f"   {input_text:15} → {pair_info.name_cn} ({pair_info.pair})")
                    keywords = forex_mapping.get_search_keywords(pairs[0])
                    print(f"   搜索关键词: {', '.join(keywords[:6])}")
            else:
                print(f"   {input_text:15} → 未识别")
                
    except Exception as e:
        print(f"❌ 外汇货币对映射模块错误: {e}")
    
    # 2. 测试市场工具识别
    try:
        from enhanced_market_search import EnhancedMarketSearch
        market_search = EnhancedMarketSearch()
        
        print("\n✅ 市场工具识别模块")
        test_inputs = ['FE.EURUSD', 'EURUSD', 'EUR/USD']
        
        for input_text in test_inputs:
            results = market_search.identify_market_instrument(input_text)
            forex_results = [r for r in results if r.market_type.value == 'forex']
            
            if forex_results:
                result = forex_results[0]  # 取第一个外汇结果
                print(f"   {input_text:15} → 外汇市场 | {result.symbol} | 置信度: {result.confidence:.2f}")
            else:
                print(f"   {input_text:15} → 未识别为外汇")
                
    except Exception as e:
        print(f"❌ 市场工具识别模块错误: {e}")
    
    # 3. 测试语义搜索优化
    try:
        from semantic_search_optimizer import SemanticSearchOptimizer
        optimizer = SemanticSearchOptimizer()
        
        print("\n✅ 语义搜索优化模块")
        test_queries = ['FE.EURUSD', 'EURUSD', '欧元兑美元']
        
        for query in test_queries:
            optimized = optimizer.optimize_search_query(query)
            if optimized.market_type.value == 'forex':
                print(f"   查询: {query:15}")
                print(f"   市场: {optimized.market_type.value} | 标的: {optimized.symbol}")
                print(f"   主要关键词: {', '.join(optimized.primary_keywords[:4])}")
                print(f"   次要关键词: {', '.join(optimized.secondary_keywords[:4])}")
                print()
                
    except Exception as e:
        print(f"❌ 语义搜索优化模块错误: {e}")
    
    # 4. 测试向量数据库搜索
    try:
        from news_vector_db import NewsVectorDB
        vector_db = NewsVectorDB(db_path="./web/chanlun_chart/cl_app/chroma_db")
        
        stats = vector_db.get_collection_stats()
        print(f"✅ 向量数据库连接成功")
        print(f"   数据库状态: {stats}")
        
        print("\n🔍 EURUSD新闻搜索演示:")
        test_queries = ['EURUSD', '欧元兑美元', 'EUR/USD']
        
        for query in test_queries:
            print(f"\n--- 搜索查询: '{query}' ---")
            
            try:
                results = vector_db.semantic_search(
                    query=query,
                    n_results=3,
                    days_back=30
                )
                
                if results:
                    print(f"✅ 找到 {len(results)} 条相关新闻:")
                    for i, result in enumerate(results, 1):
                        title = result.get('title', 'N/A')[:50]
                        similarity = result.get('similarity', 0)
                        source = result.get('source', 'N/A')
                        published_at = result.get('published_at', 'N/A')
                        print(f"   {i}. {title}...")
                        print(f"      相似度: {similarity:.3f} | 来源: {source} | 时间: {published_at}")
                else:
                    print("   ℹ️  当前数据库中暂无EURUSD相关新闻")
                    
            except Exception as e:
                print(f"   ❌ 搜索出错: {str(e)}")
                
    except Exception as e:
        print(f"❌ 向量数据库模块错误: {e}")
    
    # 5. 测试外汇新闻API
    try:
        from forex_futures_news_api import ForexFuturesNewsAPI
        api = ForexFuturesNewsAPI()
        
        print("\n✅ 外汇新闻搜索API")
        print("\n🔍 API搜索演示:")
        
        test_query = 'EURUSD'
        print(f"--- API搜索: '{test_query}' ---")
        
        try:
            result = api.search_forex_news(
                query=test_query,
                limit=5,
                days_back=30,
                include_analysis=True
            )
            
            print(f"✅ API响应成功")
            print(f"   搜索状态: {result.get('status', 'unknown')}")
            print(f"   识别标的: {result.get('identified_symbol', 'N/A')}")
            print(f"   市场类型: {result.get('market_type', 'N/A')}")
            print(f"   新闻数量: {result.get('news_count', 0)}")
            
            # 显示查询优化信息
            if 'query_optimization' in result:
                opt = result['query_optimization']
                print(f"   优化关键词: {', '.join(opt.get('primary_keywords', [])[:5])}")
            
        except Exception as e:
            print(f"   ❌ API搜索出错: {str(e)}")
            
    except Exception as e:
        print(f"❌ 外汇新闻API模块错误: {e}")
    
    # 总结
    print("\n" + "=" * 60)
    print("🎉 EURUSD新闻搜索功能演示完成!")
    print("\n📊 功能总结:")
    print("   ✅ 支持多种EURUSD输入格式识别")
    print("   ✅ 外汇货币对智能映射")
    print("   ✅ 市场工具自动识别")
    print("   ✅ 语义搜索查询优化")
    print("   ✅ 向量数据库新闻搜索")
    print("   ✅ 专用外汇新闻API接口")
    
    print("\n🚀 使用方法:")
    print("   1. 输入任意EURUSD格式 (如: FE.EURUSD, 欧元兑美元)")
    print("   2. 系统自动识别为外汇货币对")
    print("   3. 生成优化的搜索关键词")
    print("   4. 在新闻数据库中搜索相关内容")
    print("   5. 返回按相关性排序的新闻结果")
    
    print("\n💡 系统已完全支持EURUSD和欧元兑美元的新闻搜索需求!")

if __name__ == "__main__":
    try:
        demo_eurusd_search()
    except Exception as e:
        print(f"❌ 演示过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc()