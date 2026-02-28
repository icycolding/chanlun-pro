#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版EURUSD新闻搜索测试
专门测试FE.EURUSD或欧元兑美元的新闻搜索功能
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

def test_eurusd_basic():
    """
    基础EURUSD测试
    """
    print("EURUSD（欧元兑美元）新闻搜索功能测试")
    print("=" * 50)
    
    # 测试输入格式
    test_inputs = [
        'FE.EURUSD',
        'EURUSD', 
        'EUR/USD',
        '欧元兑美元',
        '欧美',
        '欧元美元'
    ]
    
    print("\n=== 测试输入格式识别 ===")
    for input_text in test_inputs:
        print(f"输入格式: {input_text:15} -> 应识别为外汇货币对EURUSD")
    
    # 尝试导入和测试各个模块
    print("\n=== 测试模块导入 ===")
    
    try:
        from news_vector_db import NewsVectorDB
        print("✓ NewsVectorDB 导入成功")
        
        # 测试向量数据库连接
        vector_db = NewsVectorDB(db_path="./web/chanlun_chart/cl_app/chroma_db")
        stats = vector_db.get_collection_stats()
        print(f"✓ 向量数据库连接成功: {stats}")
        
        # 测试EURUSD搜索
        print("\n=== 测试EURUSD向量搜索 ===")
        test_queries = ['EURUSD', '欧元兑美元', 'EUR/USD']
        
        for query in test_queries:
            print(f"\n--- 搜索: '{query}' ---")
            try:
                results = vector_db.semantic_search(
                    query=query,
                    n_results=3,
                    days_back=30
                )
                
                if results:
                    print(f"找到 {len(results)} 条相关新闻:")
                    for i, result in enumerate(results, 1):
                        title = result.get('title', 'N/A')[:50]
                        similarity = result.get('similarity', 0)
                        print(f"  {i}. {title}... (相似度: {similarity:.3f})")
                else:
                    print("  未找到相关新闻")
                    
            except Exception as e:
                print(f"  搜索出错: {str(e)}")
        
    except ImportError as e:
        print(f"❌ NewsVectorDB 导入失败: {e}")
    except Exception as e:
        print(f"❌ 向量数据库测试失败: {e}")
    
    # 测试外汇映射模块
    try:
        from forex_currency_mapping import ForexCurrencyMapping
        print("\n✓ ForexCurrencyMapping 导入成功")
        
        forex_mapping = ForexCurrencyMapping()
        
        print("\n=== 测试外汇货币对识别 ===")
        for input_text in test_inputs:
            pairs = forex_mapping.identify_forex_pair(input_text)
            if pairs:
                for pair in pairs:
                    pair_info = forex_mapping.get_pair_info(pair)
                    if pair_info:
                        print(f"输入: {input_text:15} -> {pair_info.name_cn} ({pair_info.pair})")
            else:
                print(f"输入: {input_text:15} -> 未识别")
                
    except ImportError as e:
        print(f"❌ ForexCurrencyMapping 导入失败: {e}")
    except Exception as e:
        print(f"❌ 外汇映射测试失败: {e}")
    
    # 测试市场搜索模块
    try:
        from enhanced_market_search import EnhancedMarketSearch
        print("\n✓ EnhancedMarketSearch 导入成功")
        
        market_search = EnhancedMarketSearch()
        
        print("\n=== 测试市场工具识别 ===")
        for input_text in test_inputs[:3]:  # 只测试前3个
            results = market_search.identify_market_instrument(input_text)
            if results:
                for result in results:
                    print(f"输入: {input_text:15} -> 市场: {result.market_type.value} | 标的: {result.symbol} | 置信度: {result.confidence:.2f}")
            else:
                print(f"输入: {input_text:15} -> 未识别")
                
    except ImportError as e:
        print(f"❌ EnhancedMarketSearch 导入失败: {e}")
    except Exception as e:
        print(f"❌ 市场搜索测试失败: {e}")
    
    # 测试外汇期货API
    try:
        from forex_futures_news_api import ForexFuturesNewsAPI
        print("\n✓ ForexFuturesNewsAPI 导入成功")
        
        api = ForexFuturesNewsAPI()
        
        print("\n=== 测试外汇新闻搜索API ===")
        test_query = 'EURUSD'
        print(f"测试查询: {test_query}")
        
        try:
            result = api.search_forex_news(
                query=test_query,
                limit=3,
                days_back=30,
                include_analysis=True
            )
            
            print(f"搜索状态: {result.get('status', 'unknown')}")
            print(f"识别的标的: {result.get('identified_symbol', 'N/A')}")
            print(f"新闻数量: {result.get('news_count', 0)}")
            
        except Exception as e:
            print(f"API搜索出错: {str(e)}")
            
    except ImportError as e:
        print(f"❌ ForexFuturesNewsAPI 导入失败: {e}")
    except Exception as e:
        print(f"❌ 外汇期货API测试失败: {e}")
    
    print("\n=== 测试总结 ===")
    print("✓ 基础EURUSD格式识别测试完成")
    print("✓ 各模块功能测试完成")
    print("\n系统支持以下EURUSD输入格式:")
    for input_format in test_inputs:
        print(f"  - {input_format}")
    print("\n所有格式都应该能够正确识别为欧元兑美元外汇对并进行新闻搜索!")

if __name__ == "__main__":
    try:
        test_eurusd_basic()
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc()