#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EnhancedMarketSearch对KH前缀股票代码的支持
简化版本，避免复杂的依赖问题
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any

class MarketType(Enum):
    """市场类型枚举"""
    STOCK = "stock"
    FOREX = "forex"
    FUTURES = "futures"
    UNKNOWN = "unknown"

@dataclass
class SearchResult:
    """搜索结果"""
    market_type: MarketType
    symbol: str
    name_en: str
    name_cn: str
    keywords: List[str]
    confidence: float
    additional_info: Dict[str, Any]

class SimpleEnhancedMarketSearch:
    """简化版的EnhancedMarketSearch，用于测试KH前缀支持"""
    
    def __init__(self):
        # 股票代码模式（按优先级排序，更具体的模式在前）
        self.stock_patterns = [
            r'KH\.\d{5}',      # KH前缀股票代码
            r'\d{4}\.HK',      # 港股
            r'\d{6}\.SH',      # 沪市
            r'\d{6}\.SZ',      # 深市
            r'\b(?!KH\b)[A-Z]{2,5}\b'  # 美股代码，排除KH前缀，至少2个字母
        ]
    
    def _identify_stock_symbols(self, query: str) -> List[SearchResult]:
        """识别股票代码"""
        results = []
        found_symbols = set()  # 避免重复识别同一个符号
        
        for pattern in self.stock_patterns:
            matches = re.findall(pattern, query.upper())
            for match in matches:
                if match not in found_symbols:
                    found_symbols.add(match)
                    # 这里可以扩展股票信息查询
                    result = SearchResult(
                        market_type=MarketType.STOCK,
                        symbol=match,
                        name_en=f"Stock {match}",
                        name_cn=f"股票 {match}",
                        keywords=[match, '股票', '股价', '财报'],
                        confidence=0.8,
                        additional_info={'exchange': self._get_stock_exchange(match)}
                    )
                    results.append(result)
        
        return results
    
    def _get_stock_exchange(self, symbol: str) -> str:
        """根据股票代码获取交易所"""
        if '.HK' in symbol or symbol.startswith('KH.'):
            return '港交所'
        elif '.SH' in symbol:
            return '上交所'
        elif '.SZ' in symbol:
            return '深交所'
        else:
            return '美股'
    
    def identify_market_instrument(self, query: str) -> List[SearchResult]:
        """识别市场工具类型和具体标的"""
        results = []
        
        # 识别股票代码
        stock_matches = self._identify_stock_symbols(query)
        results.extend(stock_matches)
        
        return results

def test_kh_stock_recognition():
    """测试KH前缀股票代码识别"""
    print("=== 测试EnhancedMarketSearch对KH前缀股票代码的支持 ===")
    
    # 初始化搜索引擎
    search_engine = SimpleEnhancedMarketSearch()
    
    # 测试用例
    test_cases = [
        "KH.02015",
        "KH.02015 理想汽车",
        "理想汽车 KH.02015",
        "查看KH.02015的新闻",
        "KH.02015股票分析"
    ]
    
    for i, query in enumerate(test_cases, 1):
        print(f"\n--- 测试用例 {i}: '{query}' ---")
        
        # 识别市场工具
        results = search_engine.identify_market_instrument(query)
        
        if results:
            for j, result in enumerate(results, 1):
                print(f"结果 {j}:")
                print(f"  市场类型: {result.market_type.value}")
                print(f"  代码: {result.symbol}")
                print(f"  英文名: {result.name_en}")
                print(f"  中文名: {result.name_cn}")
                print(f"  关键词: {result.keywords}")
                print(f"  置信度: {result.confidence}")
                print(f"  交易所: {result.additional_info.get('exchange', 'N/A')}")
                
                # 验证是否正确识别为股票
                if result.market_type == MarketType.STOCK and result.symbol == "KH.02015":
                    print(f"  ✅ 成功识别KH.02015为股票代码")
                else:
                    print(f"  ❌ 识别结果不正确")
        else:
            print("  ❌ 未识别到任何市场工具")

def test_stock_exchange_mapping():
    """测试股票交易所映射"""
    print("\n=== 测试股票交易所映射 ===")
    
    searcher = SimpleEnhancedMarketSearch()
    
    test_cases = [
        ('KH.02015', '港交所'),
        ('0700.HK', '港交所'),
        ('000001.SZ', '深交所'),
        ('600000.SH', '上交所'),
        ('AAPL', '美股')
    ]
    
    for symbol, expected_exchange in test_cases:
        actual_exchange = searcher._get_stock_exchange(symbol)
        print(f"  {symbol} -> {actual_exchange}")
        if symbol == 'KH.02015':
            if actual_exchange == expected_exchange:
                print(f"    ✅ KH前缀正确映射到{expected_exchange}")
            else:
                print(f"    ❌ KH前缀映射错误: {actual_exchange}")

def test_regex_patterns():
    """测试正则表达式模式"""
    print("\n=== 测试正则表达式模式 ===")
    
    search_engine = SimpleEnhancedMarketSearch()
    
    test_strings = [
        "KH.02015",
        "kh.02015",  # 小写测试
        "KH.2015",   # 4位数字
        "KH.123456", # 6位数字
        "0700.HK",
        "AAPL"
    ]
    
    for test_str in test_strings:
        print(f"\n测试字符串: '{test_str}'")
        for i, pattern in enumerate(search_engine.stock_patterns):
            matches = re.findall(pattern, test_str.upper())
            if matches:
                print(f"  模式 {i+1} ({pattern}): 匹配 -> {matches}")
            else:
                print(f"  模式 {i+1} ({pattern}): 无匹配")

if __name__ == "__main__":
    try:
        test_regex_patterns()
        test_kh_stock_recognition()
        test_stock_exchange_mapping()
        print("\n=== 测试完成 ===")
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()