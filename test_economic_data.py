#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试经济数据模型
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import db

def test_economic_data_connection():
    """测试经济数据连接和查询"""
    try:
        print("=== 测试经济数据库连接 ===")
        
        # 测试数据库连接
        print("1. 测试数据库连接...")
        
        # 查询经济数据总数
        print("2. 查询经济数据总数...")
        total_count = db.economic_data_count()
        print(f"   经济数据总数: {total_count}")
        
        # 查询最新的几条记录
        print("3. 查询最新的5条经济数据记录...")
        latest_records = db.economic_data_query(limit=5)
        
        if latest_records:
            print(f"   找到 {len(latest_records)} 条记录:")
            for i, record in enumerate(latest_records, 1):
                print(f"   [{i}] ID: {record.id}")
                print(f"       指标名称: {record.indicator_name}")
                print(f"       数据源助记符: {record.ds_mnemonic}")
                print(f"       最新值: {record.latest_value}")
                print(f"       最新值日期: {record.latest_value_date}")
                print(f"       年份: {record.year}")
                print(f"       单位: {record.units}")
                print(f"       来源: {record.source}")
                print("       ---")
        else:
            print("   没有找到经济数据记录")
        
        # 测试按年份查询
        print("4. 测试按年份查询 (2024年)...")
        records_2024 = db.economic_data_query(year=2024, limit=3)
        print(f"   2024年记录数: {len(records_2024)}")
        
        # 测试按指标名称查询
        print("5. 测试按指标名称模糊查询...")
        gdp_records = db.economic_data_query(indicator_name="GDP", limit=3)
        print(f"   包含'GDP'的记录数: {len(gdp_records)}")
        
        print("\n=== 测试完成，数据库连接正常 ===")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_economic_data_connection()
    sys.exit(0 if success else 1)