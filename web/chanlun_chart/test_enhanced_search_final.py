#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EnhancedMarketSearch类的KH.02015识别功能
"""

import sys
import os
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_enhanced_market_search():
    """测试EnhancedMarketSearch的KH.02015识别功能"""
    print("=== 测试EnhancedMarketSearch类 ===\n")
    
    try:
        # 导入必要的模块
        from cl_app.enhanced_market_search import EnhancedMarketSearch, MarketType
        
        # 创建搜索引擎实例
        search_engine = EnhancedMarketSearch()
        print("✅ 成功创建EnhancedMarketSearch实例\n")
        
        # 测试不同的查询
        test_queries = [
            "KH.02015",
            "查询KH.02015的新闻", 
            "理想汽车KH.02015最新消息",
            "KH.02015股价分析",
            "理想汽车财报"
        ]
        
        for i, query in enumerate(test_queries, 1):
            print(f"测试 {i}: '{query}'")
            print("-" * 50)
            
            # 识别市场工具
            search_results = search_engine.identify_market_instrument(query)
            
            if search_results:
                for j, result in enumerate(search_results):
                    print(f"  结果 {j+1}:")
                    print(f"    市场类型: {result.market_type.value}")
                    print(f"    股票代码: {result.symbol}")
                    print(f"    中文名称: {result.name_cn}")
                    print(f"    英文名称: {result.name_en}")
                    print(f"    置信度: {result.confidence:.2f}")
                    print(f"    关键词: {result.keywords[:8]}")
                    print(f"    交易所: {result.additional_info.get('exchange', 'N/A')}")
                    print(f"    别名: {result.additional_info.get('aliases', [])}")
                    
                    # 检查是否正确识别为理想汽车
                    if result.market_type == MarketType.STOCK and "理想汽车" in result.name_cn:
                        print(f"    🎯 成功识别为理想汽车!")
                        
                        # 测试新闻搜索查询生成
                        news_queries = search_engine.generate_news_search_query([result])
                        if news_queries:
                            news_query = news_queries[0]
                            print(f"    📰 新闻搜索查询:")
                            print(f"      主要关键词: {news_query.primary_keywords}")
                            print(f"      次要关键词: {news_query.secondary_keywords[:5]}")
                            print(f"      排除关键词: {news_query.exclude_keywords}")
                    
                    print()
            else:
                print(f"  ❌ 未能识别任何市场工具")
            
            print("\n")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_search_news_integration():
    """测试search_news方法的完整流程"""
    print("=== 测试search_news方法 ===\n")
    
    try:
        from cl_app.enhanced_market_search import EnhancedMarketSearch
        
        search_engine = EnhancedMarketSearch()
        
        # 模拟向量数据库
        class MockVectorDB:
            def semantic_search(self, query, n_results=50, start_date=None, end_date=None):
                # 返回模拟的搜索结果
                return [
                    {
                        'title': '理想汽车Q3财报超预期',
                        'content': '理想汽车第三季度营收同比增长39.2%',
                        'published_at': '2024-01-15T10:00:00Z',
                        'metadata': {'content_hash': 'hash1'}
                    },
                    {
                        'title': 'Li Auto股价上涨',
                        'content': 'Li Auto港股02015今日上涨5%',
                        'published_at': '2024-01-14T15:30:00Z',
                        'metadata': {'content_hash': 'hash2'}
                    }
                ]
        
        mock_db = MockVectorDB()
        
        # 测试搜索新闻
        query = "KH.02015最新消息"
        days = 30
        
        print(f"搜索查询: '{query}'")
        print(f"时间范围: {days} 天")
        print("-" * 40)
        
        result = search_engine.search_news(query, days, mock_db)
        
        if result['success']:
            print("✅ 搜索成功!")
            print(f"识别的工具数量: {len(result['identified_instruments'])}")
            
            for instrument in result['identified_instruments']:
                print(f"  - {instrument['market_type']}: {instrument['symbol']} ({instrument['name']}) - 置信度: {instrument['confidence']:.2f}")
            
            print(f"\n找到新闻数量: {result['news_count']}")
            
            for i, news in enumerate(result['news_results'][:3], 1):
                print(f"  新闻 {i}: {news.get('title', 'N/A')}")
                print(f"    内容: {news.get('content', 'N/A')[:50]}...")
                print(f"    相关性评分: {news.get('relevance_score', 0)}")
                print()
        else:
            print(f"❌ 搜索失败: {result['message']}")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_enhanced_market_search()
    print("=" * 60)
    test_search_news_integration()