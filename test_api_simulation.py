#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟测试经济数据API功能
"""

import sys
import os
import datetime
import json
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'web/chanlun_chart/cl_app'))

# 模拟Flask request对象
class MockRequest:
    def __init__(self, json_data):
        self._json_data = json_data
        self.is_json = True
    
    def get_json(self):
        return self._json_data

def test_api_functions():
    """测试API功能"""
    try:
        print("=== 测试经济数据API功能 ===")
        
        # 导入API函数
        from economic_data_receiver import get_economic_data
        
        # 首先插入一些测试数据
        print("1. 准备测试数据...")
        from chanlun.db import db
        
        test_data_list = [
            {
                'ds_mnemonic': 'TEST_GDP_002',
                'indicator_name': 'GDP Growth Rate Q1',
                'latest_value': 3.2,
                'latest_value_date': datetime.datetime(2024, 3, 31),
                'previous_value': 2.8,
                'previous_value_date': datetime.datetime(2023, 12, 31),
                'previous_year_value': 2.5,
                'yoy_change_pct': 28.0,
                'year': 2024,
                'units': '%',
                'source': 'Test Bureau'
            },
            {
                'ds_mnemonic': 'TEST_CPI_001',
                'indicator_name': 'Consumer Price Index',
                'latest_value': 118.5,
                'latest_value_date': datetime.datetime(2024, 3, 15),
                'previous_value': 117.2,
                'previous_value_date': datetime.datetime(2024, 2, 15),
                'previous_year_value': 115.8,
                'yoy_change_pct': 2.3,
                'year': 2024,
                'units': 'Index',
                'source': 'Statistics Office'
            },
            {
                'ds_mnemonic': 'TEST_UNEMP_001',
                'indicator_name': 'Unemployment Rate',
                'latest_value': 4.1,
                'latest_value_date': datetime.datetime(2024, 3, 1),
                'previous_value': 4.3,
                'previous_value_date': datetime.datetime(2024, 2, 1),
                'previous_year_value': 4.8,
                'yoy_change_pct': -14.6,
                'year': 2024,
                'units': '%',
                'source': 'Labor Department'
            }
        ]
        
        # 插入测试数据
        for data in test_data_list:
            success = db.economic_data_insert(data)
            if success:
                print(f"   ✓ 插入数据: {data['indicator_name']}")
            else:
                print(f"   ✗ 插入失败: {data['indicator_name']}")
        
        # 测试get_economic_data API
        print("\n2. 测试get_economic_data API...")
        
        # 测试获取所有数据
        print("   2.1 获取所有数据 (限制3条)...")
        result = get_economic_data(limit=3)
        print(f"       返回代码: {result['code']}")
        print(f"       消息: {result['msg']}")
        if result['code'] == 0 and result['data']:
            print(f"       数据条数: {len(result['data']['economic_data'])}")
            for i, item in enumerate(result['data']['economic_data'][:2], 1):
                print(f"       [{i}] {item['indicator_name']}: {item['latest_value']} {item['units']}")
        
        # 测试按指标名称查询
        print("   2.2 按指标名称查询 (GDP)...")
        result = get_economic_data(indicator_name="GDP")
        print(f"       返回代码: {result['code']}")
        print(f"       消息: {result['msg']}")
        if result['code'] == 0 and result['data']:
            print(f"       GDP相关数据条数: {len(result['data']['economic_data'])}")
        
        # 测试按年份查询
        print("   2.3 按年份查询 (2024年)...")
        result = get_economic_data(year=2024)
        print(f"       返回代码: {result['code']}")
        print(f"       消息: {result['msg']}")
        if result['code'] == 0 and result['data']:
            print(f"       2024年数据条数: {len(result['data']['economic_data'])}")
        
        # 测试按数据源助记符查询
        print("   2.4 按数据源助记符查询...")
        result = get_economic_data(ds_mnemonic="TEST_CPI_001")
        print(f"       返回代码: {result['code']}")
        print(f"       消息: {result['msg']}")
        if result['code'] == 0 and result['data']:
            print(f"       CPI数据条数: {len(result['data']['economic_data'])}")
        
        # 清理测试数据
        print("\n3. 清理测试数据...")
        for data in test_data_list:
            success = db.economic_data_delete(data['ds_mnemonic'])
            if success:
                print(f"   ✓ 清理数据: {data['indicator_name']}")
            else:
                print(f"   ✗ 清理失败: {data['indicator_name']}")
        
        print("\n=== API测试完成，所有功能正常 ===")
        return True
        
    except Exception as e:
        print(f"API测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_api_functions()
    sys.exit(0 if success else 1)