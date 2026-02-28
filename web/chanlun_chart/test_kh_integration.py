#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EnhancedMarketSearch集成StockCodeMapper后的功能
验证KH.02015是否能正确识别为理想汽车
"""

from cl_app.enhanced_market_search import EnhancedMarketSearch

def test_kh_stock_integration():
    """测试KH前缀股票代码集成StockCodeMapper后的识别效果"""
    print("=== 测试EnhancedMarketSearch集成StockCodeMapper ===\n")
    
    searcher = EnhancedMarketSearch()
    
    test_cases = [
        "KH.02015",
        "查询KH.02015的新闻",
        "理想汽车KH.02015最新消息"
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
                    print(f"    关键词前5个: {result.keywords[:5]}")
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

if __name__ == "__main__":
    test_kh_stock_integration()