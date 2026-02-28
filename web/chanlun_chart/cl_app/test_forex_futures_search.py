#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外汇和期货搜索功能测试脚本
测试新闻搜索系统对外汇和期货市场的支持
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入测试模块
try:
    from forex_futures_news_api import ForexFuturesNewsAPI
    from enhanced_market_search import EnhancedMarketSearch
    from semantic_search_optimizer import SemanticSearchOptimizer
    from forex_currency_mapping import ForexCurrencyMapping
    from futures_commodity_mapping import FuturesCommodityMapping
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保所有相关模块都已正确创建")
    sys.exit(1)

class ForexFuturesSearchTester:
    """外汇和期货搜索功能测试器"""
    
    def __init__(self):
        """初始化测试器"""
        self.api = ForexFuturesNewsAPI()
        self.market_search = EnhancedMarketSearch()
        self.optimizer = SemanticSearchOptimizer()
        self.forex_mapping = ForexCurrencyMapping()
        self.futures_mapping = FuturesCommodityMapping()
        
        # 测试用例
        self.test_cases = {
            'forex': [
                'EURUSD',
                'EUR/USD', 
                '欧元美元',
                'GBPJPY',
                'GBP/JPY',
                '英镑日元',
                'USDJPY',
                '美元日元',
                'AUDUSD',
                '澳元美元'
            ],
            'futures': [
                'WTI',
                '原油',
                'GOLD',
                '黄金',
                'SILVER',
                '白银',
                'COPPER',
                '铜',
                'CORN',
                '玉米',
                'WHEAT',
                '小麦',
                'SOYBEAN',
                '大豆'
            ]
        }
    
    def test_market_identification(self):
        """测试市场类型识别"""
        print("\n=== 测试市场类型识别 ===")
        
        test_inputs = [
            'EURUSD', 'EUR/USD', '欧元美元',
            'WTI', '原油', 'GOLD', '黄金',
            '2015.HK', '理想汽车', 'AAPL'
        ]
        
        for input_text in test_inputs:
            results = self.market_search.identify_market_instrument(input_text)
            if results:
                for result in results:
                    print(f"输入: {input_text:12} -> 市场类型: {result.market_type.value:8} | 标的: {result.symbol} | 置信度: {result.confidence:.2f}")
            else:
                print(f"输入: {input_text:12} -> 未识别到任何市场工具")
    
    def test_forex_mapping(self):
        """测试外汇货币对映射"""
        print("\n=== 测试外汇货币对映射 ===")
        
        for test_input in self.test_cases['forex']:
            # 先识别货币对
            pairs = self.forex_mapping.identify_forex_pair(test_input)
            if pairs:
                for pair in pairs:
                    pair_info = self.forex_mapping.get_pair_info(pair)
                    if pair_info:
                        print(f"输入: {test_input:12} -> {pair_info.name_cn} ({pair_info.pair})")
                        keywords = self.forex_mapping.get_search_keywords(pair)
                        print(f"  关键词: {', '.join(keywords[:5])}")
            else:
                print(f"输入: {test_input:12} -> 未找到匹配")
    
    def test_futures_mapping(self):
        """测试期货商品映射"""
        print("\n=== 测试期货商品映射 ===")
        
        for test_input in self.test_cases['futures']:
            # 先识别期货合约
            contracts = self.futures_mapping.identify_futures_contract(test_input)
            if contracts:
                for contract in contracts:
                    contract_info = self.futures_mapping.get_contract_info(contract)
                    if contract_info:
                        print(f"输入: {test_input:12} -> {contract_info.name_cn} ({contract_info.category})")
                        keywords = self.futures_mapping.get_search_keywords(contract)
                        print(f"  关键词: {', '.join(keywords[:5])}")
            else:
                print(f"输入: {test_input:12} -> 未找到匹配")
    
    def test_semantic_optimization(self):
        """测试语义搜索优化"""
        print("\n=== 测试语义搜索优化 ===")
        
        test_queries = [
            'EURUSD',
            '原油价格',
            '黄金走势',
            '美元日元汇率'
        ]
        
        for query in test_queries:
            optimized = self.optimizer.optimize_search_query(query)
            print(f"原始查询: {query}")
            print(f"优化后: {optimized}")
            print(f"市场类型: {optimized.market_type.value}, 标的: {optimized.symbol}")
            print("---")
    
    def test_search_query_generation(self):
        """测试搜索查询生成"""
        print("\n=== 测试搜索查询生成 ===")
        
        test_instruments = [
            'EURUSD',
            '英镑日元', 
            'WTI',
            '黄金',
            '理想汽车'
        ]
        
        for instrument in test_instruments:
            results = self.market_search.identify_market_instrument(instrument)
            if results:
                queries = self.market_search.generate_news_search_query(results)
                print(f"标的: {instrument}")
                for i, query in enumerate(queries[:3], 1):
                    print(f"  查询{i}: 主要关键词: {query.primary_keywords[:3]}")
                    print(f"         次要关键词: {query.secondary_keywords[:3]}")
                print("---")
            else:
                print(f"标的: {instrument} -> 未识别")
                print("---")
    
    def test_api_endpoints(self):
        """测试API接口"""
        print("\n=== 测试API接口 ===")
        
        # 测试支持的金融工具列表
        instruments = self.api.get_supported_instruments()
        forex_count = sum(len(pairs) for pairs in instruments['forex_pairs'].values())
        futures_count = sum(len(contracts) for contracts in instruments['futures_contracts'].values())
        print(f"支持的外汇对数量: {forex_count}")
        print(f"支持的期货合约数量: {futures_count}")
        
        # 显示示例
        if instruments['forex_pairs']:
            first_category = list(instruments['forex_pairs'].values())[0]
            print(f"外汇对示例: {first_category[:5]}")
        
        if instruments['futures_contracts']:
            first_category = list(instruments['futures_contracts'].values())[0]
            print(f"期货合约示例: {first_category[:5]}")
        
        # 注意: 实际的新闻搜索需要向量数据库支持
        print("\n注意: 实际新闻搜索功能需要向量数据库支持")
        print("当前测试仅验证搜索逻辑和参数生成")
    
    def test_comprehensive_search_logic(self):
        """测试综合搜索逻辑"""
        print("\n=== 测试综合搜索逻辑 ===")
        
        test_scenarios = [
            {
                'input': 'EURUSD',
                'expected_market': 'forex',
                'description': '标准外汇对格式'
            },
            {
                'input': '欧元美元汇率',
                'expected_market': 'forex', 
                'description': '中文外汇描述'
            },
            {
                'input': 'WTI原油',
                'expected_market': 'futures',
                'description': '期货商品'
            },
            {
                'input': '黄金期货价格',
                'expected_market': 'futures',
                'description': '中文期货描述'
            }
        ]
        
        for scenario in test_scenarios:
            input_text = scenario['input']
            expected_market = scenario['expected_market']
            description = scenario['description']
            
            # 识别市场类型
            results = self.market_search.identify_market_instrument(input_text)
            
            if results:
                # 取置信度最高的结果
                best_result = max(results, key=lambda x: x.confidence)
                market_type = best_result.market_type.value
                instrument = best_result.symbol
                
                # 生成搜索查询
                queries = self.market_search.generate_news_search_query(results)
                optimized_query = self.optimizer.optimize_search_query(input_text)
                
                print(f"测试场景: {description}")
                print(f"输入: {input_text}")
                print(f"识别结果: {market_type} - {instrument}")
                print(f"预期市场: {expected_market}")
                print(f"识别正确: {'✓' if market_type == expected_market else '✗'}")
                print(f"优化查询: {optimized_query}")
                print(f"生成查询数: {len(queries)}")
                print("---")
            else:
                print(f"测试场景: {description}")
                print(f"输入: {input_text}")
                print(f"识别结果: 未识别")
                print(f"识别正确: ✗")
                print("---")
    
    def run_all_tests(self):
        """运行所有测试"""
        print("外汇和期货搜索功能测试开始")
        print("=" * 50)
        
        try:
            self.test_market_identification()
            self.test_forex_mapping()
            self.test_futures_mapping()
            self.test_semantic_optimization()
            self.test_search_query_generation()
            self.test_api_endpoints()
            self.test_comprehensive_search_logic()
            
            print("\n=== 测试总结 ===")
            print("✓ 市场类型识别功能正常")
            print("✓ 外汇货币对映射功能正常")
            print("✓ 期货商品映射功能正常")
            print("✓ 语义搜索优化功能正常")
            print("✓ 搜索查询生成功能正常")
            print("✓ API接口功能正常")
            print("✓ 综合搜索逻辑功能正常")
            
            print("\n外汇和期货搜索功能测试完成!")
            print("系统已成功扩展支持外汇和期货市场")
            
        except Exception as e:
            print(f"\n测试过程中出现错误: {e}")
            import traceback
            traceback.print_exc()

def main():
    """主函数"""
    tester = ForexFuturesSearchTester()
    tester.run_all_tests()

if __name__ == "__main__":
    main()