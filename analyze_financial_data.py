#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.append(src_path)

from chanlun.db import db

def analyze_financial_data():
    """分析数据库中的财务数据格式"""
    print("=== 财务数据格式分析 ===")
    
    # 查询LI的财务数据
    data = db.company_financials_query(code='LI', limit=100)
    
    if not data:
        print("未找到财务数据")
        return
    
    print(f"总共找到 {len(data)} 条财务数据")
    
    # 分析报表类型
    statement_types = set()
    item_codes = set()
    
    for item in data:
        statement_types.add(item.statement_type)
        # 提取财务指标代码（通常是括号前的部分）
        item_code = item.item_name.split(' ')[0] if ' ' in item.item_name else item.item_name
        item_codes.add(item_code)
    
    print(f"\n报表类型: {sorted(statement_types)}")
    print(f"\n财务指标代码样本 (前30个): {sorted(list(item_codes))[:30]}")
    
    print("\n=== 详细数据样本 (前20条) ===")
    for i, item in enumerate(data[:20]):
        print(f"{i+1}. [{item.report_date}] {item.statement_type}")
        print(f"   {item.item_name} = {item.item_value}")
        print()
    
    # 按报表类型分组显示
    print("\n=== 按报表类型分组 ===")
    by_statement = {}
    for item in data:
        if item.statement_type not in by_statement:
            by_statement[item.statement_type] = []
        by_statement[item.statement_type].append(item)
    
    for statement_type, items in by_statement.items():
        print(f"\n{statement_type} ({len(items)} 项):")
        for item in items[:5]:  # 只显示前5项
            print(f"  - {item.item_name} = {item.item_value}")
        if len(items) > 5:
            print(f"  ... 还有 {len(items) - 5} 项")

if __name__ == "__main__":
    analyze_financial_data()