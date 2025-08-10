#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import db

def main():
    print("=== 经济数据问题分析 ===")
    
    # 获取前5条记录进行详细分析
    results = db.economic_data_query(limit=5)
    
    print(f"\n分析前5条记录的详细信息:")
    print("=" * 80)
    
    for i, r in enumerate(results, 1):
        print(f"\n记录 {i} (ID: {r.id}):")
        print(f"  助记符 (ds_mnemonic): '{r.ds_mnemonic}'")
        print(f"  指标名称 (indicator_name): '{r.indicator_name}'")
        print(f"  最新值 (latest_value): {r.latest_value} (类型: {type(r.latest_value)})")
        print(f"  最新值日期 (latest_value_date): {r.latest_value_date}")
        print(f"  前值 (previous_value): {r.previous_value} (类型: {type(r.previous_value)})")
        print(f"  前值日期 (previous_value_date): {r.previous_value_date}")
        print(f"  去年同期值 (previous_year_value): {r.previous_year_value} (类型: {type(r.previous_year_value)})")
        print(f"  年同比变化 (yoy_change_pct): {r.yoy_change_pct} (类型: {type(r.yoy_change_pct)})")
        print(f"  年份 (year): {r.year}")
        print(f"  单位 (units): '{r.units}'")
        print(f"  来源 (source): '{r.source}'")
        print(f"  创建时间: {r.created_at}")
        print(f"  更新时间: {r.updated_at}")
        print("-" * 60)
    
    # 统计各字段的空值情况
    print("\n=== 字段空值统计 ===")
    all_results = db.economic_data_query(limit=1000)
    
    field_stats = {
        'ds_mnemonic': {'null': 0, 'not_null': 0},
        'indicator_name': {'null': 0, 'not_null': 0, 'indicator_name_literal': 0},
        'latest_value': {'null': 0, 'not_null': 0},
        'previous_value': {'null': 0, 'not_null': 0},
        'previous_year_value': {'null': 0, 'not_null': 0},
        'yoy_change_pct': {'null': 0, 'not_null': 0},
        'units': {'empty': 0, 'not_empty': 0}
    }
    
    for r in all_results:
        # ds_mnemonic
        if r.ds_mnemonic is None:
            field_stats['ds_mnemonic']['null'] += 1
        else:
            field_stats['ds_mnemonic']['not_null'] += 1
        
        # indicator_name
        if r.indicator_name is None:
            field_stats['indicator_name']['null'] += 1
        elif r.indicator_name == 'indicator_name':
            field_stats['indicator_name']['indicator_name_literal'] += 1
        else:
            field_stats['indicator_name']['not_null'] += 1
        
        # latest_value
        if r.latest_value is None:
            field_stats['latest_value']['null'] += 1
        else:
            field_stats['latest_value']['not_null'] += 1
        
        # previous_value
        if r.previous_value is None:
            field_stats['previous_value']['null'] += 1
        else:
            field_stats['previous_value']['not_null'] += 1
        
        # previous_year_value
        if r.previous_year_value is None:
            field_stats['previous_year_value']['null'] += 1
        else:
            field_stats['previous_year_value']['not_null'] += 1
        
        # yoy_change_pct
        if r.yoy_change_pct is None:
            field_stats['yoy_change_pct']['null'] += 1
        else:
            field_stats['yoy_change_pct']['not_null'] += 1
        
        # units
        if not r.units or r.units.strip() == '':
            field_stats['units']['empty'] += 1
        else:
            field_stats['units']['not_empty'] += 1
    
    total_records = len(all_results)
    print(f"\n总记录数: {total_records}")
    print("\n各字段统计:")
    
    for field, stats in field_stats.items():
        print(f"\n{field}:")
        for stat_name, count in stats.items():
            percentage = (count / total_records) * 100 if total_records > 0 else 0
            print(f"  {stat_name}: {count} ({percentage:.1f}%)")
    
    # 查找可能有问题的记录
    print("\n=== 问题记录分析 ===")
    
    # 查找助记符为None的记录
    none_mnemonic_count = sum(1 for r in all_results if r.ds_mnemonic is None)
    print(f"助记符为None的记录: {none_mnemonic_count} 条")
    
    # 查找指标名称为'indicator_name'的记录
    literal_indicator_count = sum(1 for r in all_results if r.indicator_name == 'indicator_name')
    print(f"指标名称为字面值'indicator_name'的记录: {literal_indicator_count} 条")
    
    # 查找所有数值字段都为空的记录
    all_values_null_count = sum(1 for r in all_results 
                               if r.latest_value is None and r.previous_value is None)
    print(f"最新值和前值都为空的记录: {all_values_null_count} 条")
    
    print("\n=== 结论 ===")
    print("数据存在以下问题:")
    print("1. 所有记录的indicator_name字段都是字面值'indicator_name'，而不是实际的指标名称")
    print("2. 所有记录的latest_value和previous_value都为None，没有实际数值")
    print("3. 只有previous_year_value和yoy_change_pct字段有数据")
    print("4. 数据来源都是'excel_upload'，说明是通过Excel上传的")
    print("\n建议检查数据上传过程中的字段映射问题。")

if __name__ == "__main__":
    main()