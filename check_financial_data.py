#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import os
import pathlib

def check_financial_data():
    """检查数据库中理想汽车的财务数据"""
    # 获取正确的数据库路径
    home_path = pathlib.Path.home()
    db_path = home_path / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite'
    
    if not db_path.exists():
        print(f"数据库文件不存在: {db_path}")
        return
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 检查理想汽车的报表类型
        print("=== 理想汽车的报表类型 ===")
        cursor.execute('''
            SELECT DISTINCT name, statement_type 
            FROM company_financials 
            WHERE code = 'LI' OR name = '理想汽车'
            ORDER BY statement_type
        ''')
        
        statement_types = cursor.fetchall()
        if statement_types:
            for row in statement_types:
                print(f"  - {row[0]} | {row[1]}")
        else:
            print("  未找到理想汽车的财务数据")
        
        # 检查每种报表类型的数据量
        print("\n=== 各报表类型的数据量 ===")
        cursor.execute('''
            SELECT name, statement_type, COUNT(*) as count
            FROM company_financials 
            WHERE code = 'LI' OR name = '理想汽车'
            GROUP BY name, statement_type
            ORDER BY statement_type
        ''')
        results = cursor.fetchall()
        for row in results:
            print(f"  - {row[0]} | {row[1]} : {row[2]} 条记录")
        
        # 检查资产负债表的具体字段
        if any('资产负债表' in st[1] for st in statement_types):
            print("\n=== 资产负债表字段示例 ===")
            cursor.execute('''
                SELECT item_name, item_value, report_date
                FROM company_financials 
                WHERE (code = 'LI' OR name = '理想汽车') AND statement_type LIKE '%资产负债表%'
                ORDER BY report_date DESC, item_name
                LIMIT 20
            ''')
            
            balance_sheet_data = cursor.fetchall()
            for row in balance_sheet_data:
                print(f"  - {row[0]}: {row[1]} ({row[2]})")
        
        # 检查现金流量表的具体字段
        if any('现金流量表' in st[1] for st in statement_types):
            print("\n=== 现金流量表字段示例 ===")
            cursor.execute('''
                SELECT item_name, item_value, report_date
                FROM company_financials 
                WHERE (code = 'LI' OR name = '理想汽车') AND statement_type LIKE '%现金流量表%'
                ORDER BY report_date DESC, item_name
                LIMIT 20
            ''')
            
            cashflow_data = cursor.fetchall()
            for row in cashflow_data:
                print(f"  - {row[0]}: {row[1]} ({row[2]})")
        
        conn.close()
        
    except Exception as e:
        print(f"查询数据库时出错: {e}")

if __name__ == '__main__':
    check_financial_data()