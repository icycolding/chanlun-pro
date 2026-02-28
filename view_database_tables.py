#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查看数据库表内容脚本
显示数据库中所有表的结构和数据记录数量
"""

import sys
import os

# 添加项目路径到sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import DB
from sqlalchemy import text, inspect

def view_database_tables():
    """查看数据库中所有表的内容"""
    try:
        # 初始化数据库连接
        db = DB()
        
        print("=" * 60)
        print("数据库表结构和内容查看")
        print("=" * 60)
        
        # 获取数据库引擎
        engine = db.engine
        
        # 使用inspector检查数据库结构
        inspector = inspect(engine)
        
        # 获取所有表名
        table_names = inspector.get_table_names()
        
        print(f"\n数据库中共有 {len(table_names)} 个表:")
        for i, table_name in enumerate(table_names, 1):
            print(f"{i}. {table_name}")
        
        print("\n" + "=" * 60)
        
        # 详细查看每个表的信息
        with engine.connect() as conn:
            for table_name in table_names:
                print(f"\n表名: {table_name}")
                print("-" * 40)
                
                # 获取表结构
                columns = inspector.get_columns(table_name)
                print("表结构:")
                for col in columns:
                    col_type = str(col['type'])
                    nullable = "可空" if col['nullable'] else "不可空"
                    print(f"  - {col['name']}: {col_type} ({nullable})")
                
                # 获取记录数量
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    count = result.scalar()
                    print(f"\n记录数量: {count} 条")
                    
                    # 如果是company_financials表且有数据，显示前几条记录
                    if table_name == 'company_financials' and count > 0:
                        print("\n前5条记录示例:")
                        result = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 5"))
                        rows = result.fetchall()
                        for i, row in enumerate(rows, 1):
                            print(f"  记录{i}: {dict(row._mapping)}")
                    
                    # 如果表有数据，显示一些统计信息
                    if count > 0:
                        # 尝试获取最新记录的时间信息（如果有时间字段）
                        time_columns = ['created_at', 'updated_at', 'dt', 'add_dt', 'report_date']
                        for time_col in time_columns:
                            if any(col['name'] == time_col for col in columns):
                                try:
                                    result = conn.execute(text(f"SELECT MAX({time_col}) FROM {table_name}"))
                                    max_time = result.scalar()
                                    if max_time:
                                        print(f"最新{time_col}: {max_time}")
                                    break
                                except:
                                    continue
                    
                except Exception as e:
                    print(f"查询记录数量时出错: {e}")
                
                print("\n" + "=" * 60)
        
        # 特别关注company_financials表
        if 'company_financials' in table_names:
            print("\n" + "*" * 60)
            print("company_financials 表详细信息")
            print("*" * 60)
            
            with engine.connect() as conn:
                try:
                    # 检查是否有数据
                    result = conn.execute(text("SELECT COUNT(*) FROM company_financials"))
                    total_count = result.scalar()
                    
                    if total_count == 0:
                        print("\n⚠️  company_financials表当前为空，没有任何数据记录。")
                        print("这解释了为什么财务分析功能显示'数据不足'。")
                    else:
                        print(f"\n✅ company_financials表共有 {total_count} 条记录")
                        
                        # 按公司分组统计
                        result = conn.execute(text("""
                            SELECT code, name, COUNT(*) as record_count 
                            FROM company_financials 
                            GROUP BY code, name
                        """))
                        companies = result.fetchall()
                        
                        print("\n按公司统计:")
                        for company in companies:
                            print(f"  - {company.code} ({company.name}): {company.record_count} 条记录")
                        
                        # 按报表类型统计
                        result = conn.execute(text("""
                            SELECT statement_type, COUNT(*) as record_count 
                            FROM company_financials 
                            GROUP BY statement_type
                        """))
                        statements = result.fetchall()
                        
                        print("\n按报表类型统计:")
                        for stmt in statements:
                            print(f"  - {stmt.statement_type}: {stmt.record_count} 条记录")
                
                except Exception as e:
                    print(f"查询company_financials表详细信息时出错: {e}")
        else:
            print("\n⚠️  未找到company_financials表")
        
        print("\n" + "=" * 60)
        print("数据库表查看完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"查看数据库表时出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    view_database_tables()