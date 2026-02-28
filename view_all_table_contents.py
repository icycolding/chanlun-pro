#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查看数据库中所有表的完整内容
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import DB
from sqlalchemy import text
import pandas as pd

def view_all_table_contents():
    """查看数据库中所有表的完整内容"""
    db = DB()
    
    try:
        # 获取所有表名
        if hasattr(db.engine.dialect, 'name') and db.engine.dialect.name == 'sqlite':
            # SQLite
            tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        else:
            # MySQL
            tables_query = "SHOW TABLES"
        
        with db.engine.connect() as conn:
            tables_result = conn.execute(text(tables_query))
            tables = [row[0] for row in tables_result]
            
            print(f"数据库中共有 {len(tables)} 个表:")
            print("=" * 50)
            
            for table_name in tables:
                print(f"\n表名: {table_name}")
                print("-" * 30)
                
                # 获取表结构
                if hasattr(db.engine.dialect, 'name') and db.engine.dialect.name == 'sqlite':
                    structure_query = f"PRAGMA table_info({table_name})"
                else:
                    structure_query = f"DESCRIBE {table_name}"
                
                try:
                    structure_result = conn.execute(text(structure_query))
                    print("表结构:")
                    for row in structure_result:
                        print(f"  {row}")
                    
                    # 获取记录数量
                    count_query = f"SELECT COUNT(*) FROM {table_name}"
                    count_result = conn.execute(text(count_query))
                    count = count_result.scalar()
                    print(f"\n记录数量: {count}")
                    
                    # 如果记录数量不为0，显示前10条记录
                    if count > 0:
                        print("\n前10条记录:")
                        data_query = f"SELECT * FROM {table_name} LIMIT 10"
                        df = pd.read_sql(data_query, conn)
                        print(df.to_string(index=False))
                        
                        # 如果是company_financials表，显示更多详细信息
                        if table_name == 'company_financials':
                            print("\n=== company_financials 表详细分析 ===")
                            
                            # 按报表类型统计
                            type_query = "SELECT statement_type, COUNT(*) as count FROM company_financials GROUP BY statement_type"
                            type_df = pd.read_sql(type_query, conn)
                            print("\n按报表类型统计:")
                            print(type_df.to_string(index=False))
                            
                            # 按公司统计
                            company_query = "SELECT code, name, COUNT(*) as count FROM company_financials GROUP BY code, name"
                            company_df = pd.read_sql(company_query, conn)
                            print("\n按公司统计:")
                            print(company_df.to_string(index=False))
                            
                            # 按报告期统计
                            date_query = "SELECT report_date, COUNT(*) as count FROM company_financials GROUP BY report_date ORDER BY report_date DESC"
                            date_df = pd.read_sql(date_query, conn)
                            print("\n按报告期统计:")
                            print(date_df.to_string(index=False))
                            
                            # 显示所有项目名称（前20个）
                            item_query = "SELECT DISTINCT item_name FROM company_financials ORDER BY item_name LIMIT 20"
                            item_df = pd.read_sql(item_query, conn)
                            print("\n财务项目名称（前20个）:")
                            for item in item_df['item_name']:
                                print(f"  - {item}")
                            
                            # 显示具体的财务数据示例
                            sample_query = """
                            SELECT code, name, report_date, statement_type, item_name, item_value 
                            FROM company_financials 
                            WHERE code = 'LI' 
                            ORDER BY report_date DESC, item_name 
                            LIMIT 50
                            """
                            sample_df = pd.read_sql(sample_query, conn)
                            print("\n理想汽车财务数据示例（前50条）:")
                            print(sample_df.to_string(index=False))
                    
                    print("\n" + "=" * 50)
                    
                except Exception as e:
                    print(f"查询表 {table_name} 时出错: {e}")
                    continue
    
    except Exception as e:
        print(f"连接数据库时出错: {e}")

if __name__ == "__main__":
    print("开始查看数据库所有表的内容...")
    view_all_table_contents()
    print("\n查看完成！")