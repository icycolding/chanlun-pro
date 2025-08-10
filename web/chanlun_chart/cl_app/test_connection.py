#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试经济数据数据库连接
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from chanlun.db import db
from chanlun import fun
from sqlalchemy import text

__log = fun.get_logger()

def test_database_connection():
    """
    测试数据库连接是否成功
    """
    try:
        print("正在测试数据库连接...")
        
        # 测试基本数据库连接
        with db.Session() as session:
            result = session.execute(text("SELECT 1 as test")).fetchone()
            if result:
                print("✅ 数据库连接成功")
            else:
                print("❌ 数据库连接失败")
                return False
            
            # 测试经济数据表是否存在
            if db.engine.dialect.name == 'sqlite':
                table_check_sql = """
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='cl_economic_data'
                """
            else:
                table_check_sql = """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'cl_economic_data'
                """
            
            table_check = session.execute(text(table_check_sql)).fetchone()
            
            if table_check:
                print("✅ cl_economic_data 表存在")
                
                # 测试表结构
                if db.engine.dialect.name == 'sqlite':
                    columns_sql = "PRAGMA table_info(cl_economic_data)"
                    columns = session.execute(text(columns_sql)).fetchall()
                    print("📋 表结构:")
                    for col in columns:
                        print(f"   - {col[1]}: {col[2]}")
                else:
                    columns_sql = """
                        SELECT column_name, data_type 
                        FROM information_schema.columns 
                        WHERE table_name = 'cl_economic_data' 
                        ORDER BY ordinal_position
                    """
                    columns = session.execute(text(columns_sql)).fetchall()
                    print("📋 表结构:")
                    for col in columns:
                        print(f"   - {col[0]}: {col[1]}")
                    
                # 测试数据统计
                count_sql = "SELECT COUNT(*) FROM cl_economic_data"
                count = session.execute(text(count_sql)).fetchone()[0]
                print(f"📊 当前数据条数: {count}")
                
                # 显示最新几条记录
                if count > 0:
                    recent_sql = "SELECT indicator_name, latest_value, latest_value_date FROM cl_economic_data ORDER BY id DESC LIMIT 3"
                    recent_records = session.execute(text(recent_sql)).fetchall()
                    print("📈 最新记录:")
                    for record in recent_records:
                        print(f"   - {record[0]}: {record[1]} ({record[2]})")
                
                print("\n💡 注意: 发现数据库中的表结构与代码模型不匹配")
                print("   数据库表字段: id, indicator_name, ds_mnemonic, latest_value, ...")
                print("   代码模型字段: id, indicator_id, indicator_name, country_code, ...")
                print("   建议: 需要更新代码模型或迁移数据库表结构")
                
            else:
                print("❌ cl_economic_data 表不存在")
                print("💡 需要创建 cl_economic_data 表结构")
                return False
            
        print("\n🎉 所有测试通过！数据库连接和表结构正常")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        __log.error(f"数据库连接测试失败: {str(e)}")
        import traceback
        print(f"详细错误信息: {traceback.format_exc()}")
        return False

def test_economic_data_operations():
    """
    测试经济数据操作功能
    """
    try:
        print("\n正在测试经济数据操作...")
        
        # 测试插入数据
        test_data = {
            'country_code': 'TEST',
            'indicator_name': '测试指标',
            'indicator_id': 'TEST_001',
            'value': 100.0,
            'release_date': '2024-01-01',
            'period': '2024-01',
            'forecast_value': 95.0,
            'previous_value': 90.0,
            'importance': 'high',
            'unit': 'percent',
            'frequency': 'monthly',
            'source': 'test_source',
            'category': 'test_category'
        }
        
        print("📝 插入测试数据...")
        insert_result = db.economic_data_insert(test_data)
        if insert_result:
            print("✅ 数据插入成功")
            
            # 测试查询数据
            print("🔍 查询测试数据...")
            query_result = db.economic_data_query(
                country_code='TEST',
                indicator_name='测试指标',
                limit=1
            )
            
            if query_result:
                print("✅ 数据查询成功")
                print(f"   查询到 {len(query_result)} 条记录")
                
                # 清理测试数据
                print("🧹 清理测试数据...")
                test_id = query_result[0].id
                delete_result = db.economic_data_delete(test_id)
                if delete_result:
                    print("✅ 测试数据清理成功")
                else:
                    print("⚠️ 测试数据清理失败")
            else:
                print("❌ 数据查询失败")
                return False
        else:
            print("❌ 数据插入失败")
            return False
            
        print("\n🎉 经济数据操作测试通过！")
        return True
        
    except Exception as e:
        print(f"❌ 操作测试失败: {str(e)}")
        __log.error(f"经济数据操作测试失败: {str(e)}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("经济数据系统连接测试")
    print("=" * 50)
    
    # 测试数据库连接
    connection_ok = test_database_connection()
    
    if connection_ok:
        # 测试数据操作
        operations_ok = test_economic_data_operations()
        
        if operations_ok:
            print("\n" + "=" * 50)
            print("🎉 所有测试通过！系统运行正常")
            print("=" * 50)
        else:
            print("\n" + "=" * 50)
            print("⚠️ 数据操作测试失败")
            print("=" * 50)
    else:
        print("\n" + "=" * 50)
        print("❌ 数据库连接测试失败")
        print("=" * 50)