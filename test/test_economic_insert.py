#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试经济数据插入功能
"""

import sys
import os
import datetime
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import db

def test_economic_data_insert():
    """测试经济数据插入功能"""
    try:
        print("=== 测试经济数据插入功能 ===")
        
        # 准备测试数据
        test_data = {
            'ds_mnemonic': 'TEST_GDP_001',
            'indicator_name': 'GDP Growth Rate',
            'latest_value': 2.5,
            'latest_value_date': datetime.datetime(2024, 3, 15),
            'previous_value': 2.3,
            'previous_value_date': datetime.datetime(2024, 2, 15),
            'previous_year_value': 2.1,
            'yoy_change_pct': 19.0,
            'year': 2024,
            'units': '%',
            'source': 'Test Source'
        }
        
        print("1. 插入测试数据...")
        success = db.economic_data_insert(test_data)
        
        if success:
            print("   ✓ 数据插入成功")
        else:
            print("   ✗ 数据插入失败")
            return False
        
        # 验证数据是否插入成功
        print("2. 验证数据插入...")
        total_count = db.economic_data_count()
        print(f"   数据库中总记录数: {total_count}")
        
        # 查询刚插入的数据
        print("3. 查询插入的数据...")
        record = db.economic_data_get_by_mnemonic('TEST_GDP_001')
        
        if record:
            print("   ✓ 找到插入的记录:")
            print(f"     ID: {record.id}")
            print(f"     指标名称: {record.indicator_name}")
            print(f"     数据源助记符: {record.ds_mnemonic}")
            print(f"     最新值: {record.latest_value}")
            print(f"     最新值日期: {record.latest_value_date}")
            print(f"     前值: {record.previous_value}")
            print(f"     年同比变化: {record.yoy_change_pct}%")
            print(f"     年份: {record.year}")
            print(f"     单位: {record.units}")
        else:
            print("   ✗ 未找到插入的记录")
            return False
        
        # 测试查询功能
        print("4. 测试查询功能...")
        records = db.economic_data_query(limit=5)
        print(f"   查询到 {len(records)} 条记录")
        
        # 测试按年份查询
        records_2024 = db.economic_data_query(year=2024, limit=5)
        print(f"   2024年记录数: {len(records_2024)}")
        
        # 测试按指标名称查询
        gdp_records = db.economic_data_query(indicator_name="GDP", limit=5)
        print(f"   包含'GDP'的记录数: {len(gdp_records)}")
        
        # 清理测试数据
        print("5. 清理测试数据...")
        cleanup_success = db.economic_data_delete('TEST_GDP_001')
        if cleanup_success:
            print("   ✓ 测试数据清理成功")
        else:
            print("   ✗ 测试数据清理失败")
        
        print("\n=== 测试完成，所有功能正常 ===")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_economic_data_insert()
    sys.exit(0 if success else 1)