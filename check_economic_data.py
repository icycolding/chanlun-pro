#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import db

def main():
    print("=== 经济数据库统计信息 ===")
    
    # 总记录数
    total_count = db.economic_data_count()
    print(f"\n数据库中总共有 {total_count} 条经济数据记录")
    
    # 按年份统计
    print("\n按年份统计:")
    for year in [2023, 2024, 2025]:
        count = db.economic_data_count(year=year)
        print(f"  {year}年: {count} 条记录")
    
    # 按来源统计
    print("\n按来源统计:")
    results = db.economic_data_query(limit=1000)
    sources = {}
    for r in results:
        source = r.source if r.source else 'None'
        sources[source] = sources.get(source, 0) + 1
    
    for source, count in sources.items():
        print(f"  {source}: {count} 条记录")
    
    # 查看一些具体的助记符
    print("\n助记符示例 (前10个):")
    results = db.economic_data_query(limit=10)
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r.ds_mnemonic} - {r.indicator_name}")
    
    # 查看有实际数值的记录
    print("\n查找有实际数值的记录:")
    all_results = db.economic_data_query(limit=1000)
    has_value_count = 0
    for r in all_results:
        if r.latest_value is not None:
            has_value_count += 1
            if has_value_count <= 5:  # 只显示前5个
                print(f"  {r.ds_mnemonic}: {r.latest_value} ({r.units})")
    
    print(f"\n总共有 {has_value_count} 条记录包含实际数值")

if __name__ == "__main__":
    main()