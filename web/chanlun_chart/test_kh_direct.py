#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接测试EnhancedMarketSearch的KH.02015识别功能
避免依赖问题
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# 直接导入需要的模块，避免通过cl_app.__init__.py
try:
    from cl_app.enhanced_market_search import EnhancedMarketSearch
    print("✅ 成功导入EnhancedMarketSearch")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    # 尝试直接导入文件
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "enhanced_market_search", 
        "cl_app/enhanced_market_search.py"
    )
    enhanced_market_search = importlib.util.module_from_spec(spec)
    sys.modules["enhanced_market_search"] = enhanced_market_search
    spec.loader.exec_module(enhanced_market_search)
    EnhancedMarketSearch = enhanced_market_search.EnhancedMarketSearch
    print("✅ 通过直接导入成功加载EnhancedMarketSearch")

def test_kh_stock_recognition():
    """测试KH前缀股票代码识别"""
    print("\n=== 测试KH前缀股票代码识别 ===\n")
    
    try:
        searcher = EnhancedMarketSearch()
        print("✅ 成功创建EnhancedMarketSearch实例")
        
        # 测试KH.02015识别
        query = "KH.02015"
        print(f"\n测试查询: '{query}'")
        print("-" * 40)
        
        results = searcher.identify_market_instrument(query)
        
        if results:
            for i, result in enumerate(results, 1):
                print(f"结果 {i}:")
                print(f"  市场类型: {result.market_type.value}")
                print(f"  股票代码: {result.symbol}")
                print(f"  英文名称: {result.name_en}")
                print(f"  中文名称: {result.name_cn}")
                print(f"  置信度: {result.confidence}")
                print(f"  关键词: {result.keywords[:3]}...")
                print(f"  交易所: {result.additional_info.get('exchange', 'N/A')}")
                
                # 检查是否正确识别为理想汽车
                if "理想汽车" in result.name_cn or "Li Auto" in result.name_en:
                    print("  ✅ 成功识别为理想汽车!")
                else:
                    print("  ❌ 未能识别为理想汽车")
                print()
        else:
            print("❌ 未识别到任何结果")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_stock_mapper_directly():
    """直接测试StockCodeMapper"""
    print("\n=== 直接测试StockCodeMapper ===\n")
    
    try:
        from cl_app.smart_news_search import StockCodeMapper
        mapper = StockCodeMapper()
        print("✅ 成功创建StockCodeMapper实例")
        
        # 测试KH.02015解析
        test_inputs = ["KH.02015", "02015", "2015"]
        
        for input_str in test_inputs:
            print(f"\n测试输入: '{input_str}'")
            stock_info = mapper.parse_stock_input(input_str)
            
            if stock_info:
                print(f"  ✅ 解析成功:")
                print(f"    代码: {stock_info.code}")
                print(f"    名称: {stock_info.name}")
                print(f"    交易所: {stock_info.exchange}")
                print(f"    市场类型: {stock_info.market_type}")
                print(f"    别名: {stock_info.aliases}")
            else:
                print(f"  ❌ 解析失败")
                
    except Exception as e:
        print(f"❌ StockCodeMapper测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_stock_mapper_directly()
    test_kh_stock_recognition()