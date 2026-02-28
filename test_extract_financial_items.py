#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试_extract_key_financial_items函数的字段提取效果
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db
from datetime import datetime, timedelta

def test_extract_financial_items():
    """测试财务指标提取函数"""
    
    # 模拟_extract_key_financial_items函数
    def _extract_key_financial_items(items: dict) -> dict:
        """提取关键财务指标 - 基于实际数据库财务代码格式
        
        数据库中的item_name格式为："代码 (英文描述)"
        例如："CIAC (Income Available to Com)", "ECOR (Vehicle sales)"
        """
        key_items = {}
        
        # 基于实际数据库中的财务代码格式进行精确匹配
        key_mappings = {
            # 收入相关 - 基于实际数据格式
            'Vehicle Sales': 'ECOR (Vehicle sales)',
            'Other Revenue': 'ECOR (Other sales and services)',
            
            # 利润相关 - 基于实际数据格式
            'Net Income': 'CIAC (Income Available to Com)',
            'Net Income Before Taxes': 'EIBT (Net Income Before Taxes)',
            'Operating Income': 'EONT (Other operating income, net)',
            
            # 费用相关 - 基于实际数据格式
            'Employee Compensation': 'ERAD (Employee compensation)',
            'Employee Compensation SGA': 'ELAR (Employee compensation in SGA)',
            'R&D Expenses': 'ERAD (Research and development)',
            
            # 每股数据 - 基于实际数据格式
            'Basic EPS': 'GBAI (Basic EPS Including ExtraOrd)',
            'Basic EPS Excluding': 'GBBF (Basic EPS Excluding ExtraOrd)',
            'Diluted EPS': 'GDAI (Diluted EPS Including ExtraOrd)',
            'Diluted EPS Excluding': 'GDBF (Diluted EPS Excluding ExtraOrd)',
            'Basic Shares': 'GBAS (Basic Weighted Average Shares)',
            'Diluted Shares': 'GDWS (Diluted Weighted Average Shares)',
            'DPS Class A': 'DDPS1 (DPS-Ordinary Shares Class A)',
            'DPS Class B': 'DDPS2 (DPS-Ordinary Shares Class B)',
            
            # 其他指标 - 基于实际数据格式
            'Minority Interest': 'CMIN (Net income attributable to nonco)',
        }
        
        # 精确匹配财务指标
        for key_name, exact_pattern in key_mappings.items():
            if exact_pattern in items:
                key_items[key_name] = items[exact_pattern]
        
        # 模糊匹配（用于处理可能的格式变化）
        fallback_mappings = {
            'Net Income': ['CIAC', 'NINC', 'GDNI'],
            'Net Income Before Taxes': ['EIBT'],
            'Operating Income': ['EONT'],
            'Employee Compensation': ['ERAD'],
            'Basic EPS': ['GBAI', 'GBBF'],
            'Diluted EPS': ['GDAI', 'GDBF'],
            'Basic Shares': ['GBAS'],
            'Diluted Shares': ['GDWS'],
            'DPS Class A': ['DDPS1'],
            'DPS Class B': ['DDPS2'],
            'Minority Interest': ['CMIN'],
        }
        
        # 对于没有精确匹配的指标，尝试模糊匹配
        for key_name, code_patterns in fallback_mappings.items():
            if key_name in key_items:  # 已经找到，跳过
                continue
                
            for code in code_patterns:
                for item_name, value in items.items():
                    if item_name.startswith(code + ' ('):
                        key_items[key_name] = value
                        break
                if key_name in key_items:
                    break
        
        # 计算总收入（Vehicle Sales + Other Revenue）
        if 'Vehicle Sales' in key_items and 'Other Revenue' in key_items:
            key_items['Total Revenue'] = key_items['Vehicle Sales'] + key_items['Other Revenue']
        elif 'Vehicle Sales' in key_items:
            key_items['Total Revenue'] = key_items['Vehicle Sales']
        elif 'Other Revenue' in key_items:
            key_items['Total Revenue'] = key_items['Other Revenue']
        
        # 合并员工薪酬数据
        if 'Employee Compensation' in key_items and 'Employee Compensation SGA' in key_items:
            key_items['Total Employee Compensation'] = key_items['Employee Compensation'] + key_items['Employee Compensation SGA']
        
        return key_items
    
    # 获取实际财务数据
    print("正在获取KH.02015的财务数据...")
    financial_data = db.company_financials_query(code='KH.02015', limit=50)
    
    # 构建财务数据字典
    items = {}
    for item in financial_data:
        if '损益表' in item.statement_type:
            items[item.item_name] = float(item.item_value)
    
    print(f"\n原始财务数据项目数: {len(items)}")
    print("原始数据样本:")
    for i, (key, value) in enumerate(list(items.items())[:10]):
        print(f"  {i+1}. {key}: {value}")
    
    # 测试提取函数
    extracted_items = _extract_key_financial_items(items)
    
    print(f"\n提取的关键财务指标数: {len(extracted_items)}")
    print("提取结果:")
    for key, value in extracted_items.items():
        print(f"  ✓ {key}: {value:,.2f}")
    
    # 验证关键指标是否提取成功
    expected_keys = ['Vehicle Sales', 'Other Revenue', 'Total Revenue', 'Net Income', 'Employee Compensation']
    success_count = 0
    for key in expected_keys:
        if key in extracted_items:
            success_count += 1
            print(f"  ✓ {key}: 提取成功")
        else:
            print(f"  ✗ {key}: 提取失败")
    
    print(f"\n提取成功率: {success_count}/{len(expected_keys)} ({success_count/len(expected_keys)*100:.1f}%)")
    
    if success_count >= len(expected_keys) * 0.8:  # 80%成功率
        print("🎉 财务指标提取功能测试通过！")
        return True
    else:
        print("❌ 财务指标提取功能需要进一步优化")
        return False

if __name__ == "__main__":
    test_extract_financial_items()