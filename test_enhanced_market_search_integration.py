#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EnhancedMarketSearch集成StockCodeMapper后的功能
验证KH.02015是否能正确识别为理想汽车
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'web/chanlun_chart'))

from cl_app.enhanced_market_search import EnhancedMarketSearch

def test_kh_stock_integration():
    """测试KH前缀股票代码集成StockCodeMapper后的识别效果"""
    print("=== 测试EnhancedMarketSearch集成StockCodeMapper ===\n")
    
    searcher = EnhancedMarketSearch()
    
    test_cases = [
        "KH.02015",
        "查询KH.02015的新闻",
        "理想汽车KH.02015最新消息",
        "KH.02015理想汽车股价"
    ]
    
    for i, query in enumerate(test_cases, 1):
        print(f"测试用例 {i}: '{query}'")
        print("-" * 50)
        
        try:
            # 识别市场工具
            results = searcher.identify_market_instrument(query)
            
            if results:
                for j, result in enumerate(results):
                    print(f"  结果 {j+1}:")
                    print(f"    市场类型: {result.market_type.value}")
                    print(f"    股票代码: {result.symbol}")
                    print(f"    英文名称: {result.name_en}")
                    print(f"    中文名称: {result.name_cn}")
                    print(f"    置信度: {result.confidence}")
                    print(f"    关键词: {result.keywords[:5]}...")  # 只显示前5个关键词
                    print(f"    交易所: {result.additional_info.get('exchange', 'N/A')}")
                    print(f"    别名: {result.additional_info.get('aliases', [])}")
                    print()
            else:
                print("  ❌ 未识别到任何股票代码")
                
        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
        
        print("=" * 60)
        print()

def test_news_search_query_generation():
    """测试新闻搜索查询生成"""
    print("=== 测试新闻搜索查询生成 ===\n")
    
    searcher = EnhancedMarketSearch()
    
    # 先识别股票
    results = searcher.identify_market_instrument("KH.02015")
    
    if results:
        print("识别到的股票信息:")
        for result in results:
            print(f"  - {result.name_cn} ({result.symbol})")
        
        print("\n生成新闻搜索查询:")
        queries = searcher.generate_news_search_query(results)
        
        for i, query in enumerate(queries, 1):
            print(f"\n查询 {i}:")
            print(f"  主要关键词: {query.primary_keywords}")
            print(f"  次要关键词: {query.secondary_keywords}")
            print(f"  排除关键词: {query.exclude_keywords}")
            print(f"  市场类型: {query.market_type.value}")
            print(f"  股票代码: {query.symbol}")
    else:
        print("❌ 未能识别股票信息")

if __name__ == "__main__":
    test_kh_stock_integration()
    test_news_search_query_generation()