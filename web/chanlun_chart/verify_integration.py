#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证EnhancedMarketSearch和StockCodeMapper集成逻辑
独立验证脚本，不依赖外部模块
"""

import re
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import json

class MarketType(Enum):
    """市场类型枚举"""
    STOCK = "stock"
    FOREX = "forex"
    FUTURES = "futures"
    UNKNOWN = "unknown"

@dataclass
class StockInfo:
    code: str
    name: str
    exchange: str
    market_type: str
    original_input: str
    aliases: List[str]

@dataclass
class SearchResult:
    """搜索结果"""
    market_type: MarketType
    symbol: str
    name_en: str
    name_cn: str
    keywords: List[str]
    confidence: float  # 置信度 0-1
    additional_info: Dict[str, Any]

class MockStockCodeMapper:
    """模拟StockCodeMapper"""
    
    def __init__(self):
        # 预定义理想汽车的映射
        self.predefined_mappings = {
            "2015": StockInfo(
                code="02015",
                name="理想汽车",
                exchange="HKEX",
                market_type="HK",
                original_input="2015",
                aliases=["理想汽车", "Li Auto", "LI", "理想", "Li Auto Inc", "理想汽车-W"]
            ),
            "02015": StockInfo(
                code="02015",
                name="理想汽车",
                exchange="HKEX",
                market_type="HK",
                original_input="02015",
                aliases=["理想汽车", "Li Auto", "LI", "理想", "Li Auto Inc", "理想汽车-W"]
            )
        }
    
    def parse_stock_input(self, input_str: str) -> Optional[StockInfo]:
        """解析股票输入"""
        if not input_str or not input_str.strip():
            return None
            
        input_str = input_str.strip()
        print(f"🔍 StockCodeMapper解析: '{input_str}'")
        
        # 1. 尝试直接匹配预定义映射
        stock_info = self._match_predefined_mapping(input_str)
        if stock_info:
            print(f"✅ 直接匹配成功: {stock_info.name} ({stock_info.code})")
            return stock_info
        
        # 2. 尝试解析KH前缀格式
        if input_str.upper().startswith('KH.'):
            hk_code = input_str[3:]  # 移除 "KH." 前缀
            return self._create_hk_stock_info(hk_code, input_str)
        
        print(f"❌ 无法解析股票输入: '{input_str}'")
        return None
    
    def _match_predefined_mapping(self, input_str: str) -> Optional[StockInfo]:
        """匹配预定义映射表"""
        # 直接匹配代码
        if input_str in self.predefined_mappings:
            return self.predefined_mappings[input_str]
        
        # 匹配别名
        for stock_info in self.predefined_mappings.values():
            if input_str in stock_info.aliases or input_str.lower() in [alias.lower() for alias in stock_info.aliases]:
                return stock_info
        
        return None
    
    def _create_hk_stock_info(self, code: str, original_input: str) -> Optional[StockInfo]:
        """创建港股信息"""
        # 标准化为5位港股代码
        normalized_code = code.zfill(5)
        
        # 检查预定义映射
        if normalized_code in self.predefined_mappings:
            return self.predefined_mappings[normalized_code]
        
        # 创建默认港股信息
        return StockInfo(
            code=normalized_code,
            name=f"港股{normalized_code}",
            exchange="HKEX",
            market_type="HK",
            original_input=original_input,
            aliases=[f"港股{normalized_code}"]
        )

class MockEnhancedMarketSearch:
    """模拟EnhancedMarketSearch的核心逻辑"""
    
    def __init__(self):
        self.stock_mapper = MockStockCodeMapper()
        
        # 股票代码模式（按优先级排序，更具体的模式在前）
        self.stock_patterns = [
            r'KH\.\d{5}',      # KH前缀股票代码
            r'\d{4}\.HK',      # 港股
            r'\d{6}\.SH',      # 沪市
            r'\d{6}\.SZ',      # 深市
            r'\b(?!KH\b)[A-Z]{2,5}\b',  # 美股（至少2个字母，排除KH前缀）
        ]
    
    def identify_market_instrument(self, query: str) -> List[SearchResult]:
        """识别市场工具类型和具体标的"""
        results = []
        
        # 识别股票代码
        stock_matches = self._identify_stock_symbols(query)
        results.extend(stock_matches)
        
        return results
    
    def _identify_stock_symbols(self, query: str) -> List[SearchResult]:
        """识别股票代码"""
        results = []
        found_symbols = set()  # 避免重复识别同一个符号
        
        print(f"🔍 开始识别股票代码: '{query}'")
        
        for pattern in self.stock_patterns:
            matches = re.findall(pattern, query.upper())
            print(f"  模式 '{pattern}' 匹配结果: {matches}")
            
            for match in matches:
                if match not in found_symbols:
                    found_symbols.add(match)
                    
                    print(f"  处理匹配项: '{match}'")
                    
                    # 使用StockCodeMapper获取股票信息
                    stock_info = self.stock_mapper.parse_stock_input(match)
                    
                    if stock_info:
                        # 使用映射器获取的详细信息
                        keywords = [match, stock_info.code, stock_info.name] + stock_info.aliases + ['股票', '股价', '财报']
                        result = SearchResult(
                            market_type=MarketType.STOCK,
                            symbol=stock_info.code,
                            name_en=stock_info.name,
                            name_cn=stock_info.name,
                            keywords=keywords,
                            confidence=0.9,
                            additional_info={
                                'exchange': stock_info.exchange,
                                'market_type': stock_info.market_type,
                                'aliases': stock_info.aliases
                            }
                        )
                        print(f"    ✅ 使用StockCodeMapper成功识别: {stock_info.name}")
                    else:
                        # 回退到原有逻辑
                        result = SearchResult(
                            market_type=MarketType.STOCK,
                            symbol=match,
                            name_en=f"Stock {match}",
                            name_cn=f"股票 {match}",
                            keywords=[match, '股票', '股价', '财报'],
                            confidence=0.8,
                            additional_info={'exchange': self._get_stock_exchange(match)}
                        )
                        print(f"    ⚠️ 回退到默认逻辑: Stock {match}")
                    
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

def test_kh_integration():
    """测试KH.02015集成效果"""
    print("=== 验证EnhancedMarketSearch和StockCodeMapper集成 ===\n")
    
    search_engine = MockEnhancedMarketSearch()
    
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
                    print(f"    ✅ KH.02015 -> 02015 (理想汽车) 映射成功!")
                
                print()
        else:
            print(f"  ❌ 未能识别任何市场工具")
        
        print("\n")

def test_pattern_matching():
    """测试正则表达式模式匹配"""
    print("=== 测试正则表达式模式匹配 ===\n")
    
    patterns = [
        r'KH\.\d{5}',      # KH前缀股票代码
        r'\d{4}\.HK',      # 港股
        r'\d{6}\.SH',      # 沪市
        r'\d{6}\.SZ',      # 深市
        r'\b(?!KH\b)[A-Z]{2,5}\b',  # 美股（至少2个字母，排除KH前缀）
    ]
    
    test_strings = [
        "KH.02015",
        "查询KH.02015的新闻",
        "理想汽车KH.02015最新消息",
        "2015.HK股价",
        "AAPL股票"
    ]
    
    for test_str in test_strings:
        print(f"测试字符串: '{test_str}'")
        for i, pattern in enumerate(patterns):
            matches = re.findall(pattern, test_str.upper())
            if matches:
                print(f"  模式 {i+1} ('{pattern}'): {matches}")
        print()

if __name__ == "__main__":
    test_pattern_matching()
    print("=" * 60)
    test_kh_integration()