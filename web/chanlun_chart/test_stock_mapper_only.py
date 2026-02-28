#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单独测试StockCodeMapper功能
"""

import sys
import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

# 模拟必要的类和模块
class AKShareProvider:
    def get_hk_stock_info(self, code):
        return None

@dataclass
class StockInfo:
    code: str
    name: str
    exchange: str
    market_type: str
    original_input: str
    aliases: List[str]

class StockCodeMapper:
    """简化版的股票代码映射器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.akshare_provider = AKShareProvider()
        self.predefined_mappings = {}
        self.code_patterns = {}
        self.exchange_info = {}
        
        # 加载配置文件
        self._load_config(config_file)
    
    def _load_config(self, config_file: Optional[str] = None):
        """加载股票映射配置文件"""
        if config_file is None:
            config_file = "cl_app/stock_mappings.json"
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            mappings = config.get('mappings', {})
            
            # 处理港股映射
            for code, info in mappings.get('hk_stocks', {}).items():
                stock_info = StockInfo(
                    code=code,
                    name=info['name'],
                    exchange=info['exchange'],
                    market_type=info['market_type'],
                    original_input=code,
                    aliases=info.get('aliases', [])
                )
                self.predefined_mappings[code] = stock_info
                # 添加去掉前导零的版本
                short_code = code.lstrip('0')
                if short_code and short_code != code:
                    self.predefined_mappings[short_code] = stock_info
            
            print(f"✅ 成功加载股票映射配置: {len(self.predefined_mappings)} 个股票")
            
        except Exception as e:
            print(f"❌ 加载配置文件失败: {e}，使用默认映射")
            self._load_default_mappings()
    
    def _load_default_mappings(self):
        """加载默认的股票映射"""
        self.predefined_mappings = {
            "2015": StockInfo(
                code="02015",
                name="理想汽车",
                exchange="HKEX",
                market_type="HK",
                original_input="2015",
                aliases=["理想汽车", "Li Auto", "LI", "理想", "Li Auto Inc"]
            ),
            "02015": StockInfo(
                code="02015",
                name="理想汽车",
                exchange="HKEX",
                market_type="HK",
                original_input="02015",
                aliases=["理想汽车", "Li Auto", "LI", "理想", "Li Auto Inc"]
            )
        }
    
    def parse_stock_input(self, input_str: str) -> Optional[StockInfo]:
        """解析股票输入"""
        if not input_str or not input_str.strip():
            return None
            
        input_str = input_str.strip()
        print(f"🔍 开始解析股票输入: '{input_str}'")
        
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

def test_stock_mapper():
    """测试StockCodeMapper"""
    print("=== 测试StockCodeMapper ===\n")
    
    try:
        mapper = StockCodeMapper()
        print("✅ 成功创建StockCodeMapper实例\n")
        
        # 测试不同的输入格式
        test_inputs = [
            "KH.02015",
            "02015", 
            "2015",
            "理想汽车",
            "Li Auto"
        ]
        
        for input_str in test_inputs:
            print(f"测试输入: '{input_str}'")
            print("-" * 30)
            
            stock_info = mapper.parse_stock_input(input_str)
            
            if stock_info:
                print(f"  ✅ 解析成功:")
                print(f"    代码: {stock_info.code}")
                print(f"    名称: {stock_info.name}")
                print(f"    交易所: {stock_info.exchange}")
                print(f"    市场类型: {stock_info.market_type}")
                print(f"    别名: {stock_info.aliases}")
                
                # 检查是否为理想汽车
                if "理想汽车" in stock_info.name:
                    print(f"    🎯 成功识别为理想汽车!")
            else:
                print(f"  ❌ 解析失败")
            
            print()
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_stock_mapper()