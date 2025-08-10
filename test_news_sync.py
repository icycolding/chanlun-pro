#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的新闻数据同步测试脚本
直接使用数据库连接，避免复杂的模块依赖
"""

import sqlite3
import os
import sys
from datetime import datetime

def test_database_connection():
    """测试数据库连接和新闻数据"""
    print("=== 测试数据库连接 ===")
    
    # 查找数据库文件
    db_paths = [
        '/Users/jiming/Documents/trae/chanlun-pro/data/chanlun.db',
        '/Users/jiming/Documents/trae/chanlun-pro/chanlun.db',
        './data/chanlun.db',
        './chanlun.db'
    ]
    
    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        print("❌ 找不到数据库文件")
        print("尝试的路径:")
        for path in db_paths:
            print(f"  - {path}")
        return False
    
    print(f"✅ 找到数据库文件: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%news%'")
        tables = cursor.fetchall()
        
        if not tables:
            print("❌ 数据库中没有找到新闻相关的表")
            return False
        
        print(f"✅ 找到新闻表: {[table[0] for table in tables]}")
        
        # 查询新闻数据
        for table_name in [table[0] for table in tables]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"  - {table_name}: {count} 条记录")
                
                if count > 0:
                    # 获取表结构
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = cursor.fetchall()
                    print(f"    字段: {[col[1] for col in columns]}")
                    
                    # 获取示例数据
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                    rows = cursor.fetchall()
                    
                    for i, row in enumerate(rows):
                        print(f"    示例 {i+1}: {str(row)[:100]}...")
                        
            except Exception as e:
                print(f"  - {table_name}: 查询失败 - {str(e)}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 数据库连接失败: {str(e)}")
        return False

def test_vector_database_files():
    """测试向量数据库文件"""
    print("\n=== 测试向量数据库文件 ===")
    
    # 查找可能的向量数据库文件
    vector_db_paths = [
        '/Users/jiming/Documents/trae/chanlun-pro/data/chroma_db',
        '/Users/jiming/Documents/trae/chanlun-pro/chroma_db',
        './data/chroma_db',
        './chroma_db'
    ]
    
    found_paths = []
    for path in vector_db_paths:
        if os.path.exists(path):
            found_paths.append(path)
            print(f"✅ 找到向量数据库目录: {path}")
            
            # 列出目录内容
            try:
                files = os.listdir(path)
                print(f"  内容: {files}")
                
                # 检查文件大小
                total_size = 0
                for file in files:
                    file_path = os.path.join(path, file)
                    if os.path.isfile(file_path):
                        size = os.path.getsize(file_path)
                        total_size += size
                        print(f"    {file}: {size} bytes")
                
                print(f"  总大小: {total_size} bytes")
                
            except Exception as e:
                print(f"  ❌ 读取目录失败: {str(e)}")
    
    if not found_paths:
        print("❌ 没有找到向量数据库文件")
        print("尝试的路径:")
        for path in vector_db_paths:
            print(f"  - {path}")
        return False
    
    return True

def test_api_endpoint():
    """测试API端点可用性"""
    print("\n=== 测试API端点建议 ===")
    
    print("建议的测试步骤:")
    print("1. 启动Web服务器")
    print("2. 访问 GET /api/news 查看数据库中的新闻")
    print("3. 访问 GET /api/news?sync_to_vector=true 进行同步")
    print("4. 访问 POST /api/news/sync_to_vector 进行批量同步")
    
    print("\n示例curl命令:")
    print("# 查看新闻数据")
    print("curl -X GET 'http://localhost:5000/api/news?limit=5'")
    
    print("\n# 同步到向量数据库")
    print("curl -X GET 'http://localhost:5000/api/news?sync_to_vector=true&limit=10'")
    
    print("\n# 批量同步")
    print("curl -X POST 'http://localhost:5000/api/news/sync_to_vector' -H 'Content-Type: application/json' -d '{\"limit\": 100, \"offset\": 0}'")
    
    return True

def check_configuration_files():
    """检查配置文件"""
    print("\n=== 检查配置文件 ===")
    
    config_files = [
        'config.py',
        'web/chanlun_chart/cl_app/config.py',
        'web/chanlun_chart/config.py'
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            print(f"✅ 找到配置文件: {config_file}")
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # 查找数据库相关配置
                if 'DATABASE' in content or 'db' in content.lower():
                    print(f"  包含数据库配置")
                    
                if 'chroma' in content.lower() or 'vector' in content.lower():
                    print(f"  包含向量数据库配置")
                    
            except Exception as e:
                print(f"  ❌ 读取配置文件失败: {str(e)}")
        else:
            print(f"❌ 配置文件不存在: {config_file}")
    
    return True

def main():
    """主测试函数"""
    print("开始简化的新闻数据同步测试...\n")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"Python路径: {sys.executable}")
    
    tests = [
        ("数据库连接", test_database_connection),
        ("向量数据库文件", test_vector_database_files),
        ("配置文件检查", check_configuration_files),
        ("API端点建议", test_api_endpoint)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"正在执行: {test_name}")
        print(f"{'='*50}")
        
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ 测试 '{test_name}' 执行失败: {str(e)}")
            results.append((test_name, False))
    
    # 输出总结
    print(f"\n{'='*50}")
    print("测试结果总结")
    print(f"{'='*50}")
    
    passed = 0
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总体结果: {passed}/{len(results)} 项测试通过")
    
    print("\n=== 数据同步问题诊断 ===")
    print("根据测试结果，可能的问题和解决方案:")
    print("\n1. 如果数据库中有新闻但向量数据库为空:")
    print("   - 启动Web服务器")
    print("   - 使用 /api/news/sync_to_vector 端点进行批量同步")
    print("\n2. 如果找不到数据库文件:")
    print("   - 检查数据库路径配置")
    print("   - 确保新闻数据已正确导入")
    print("\n3. 如果向量数据库目录不存在:")
    print("   - 首次运行时会自动创建")
    print("   - 确保有写入权限")
    print("\n4. 数据格式不统一的解决方案:")
    print("   - 使用新增的 convert_db_news_to_vector_format 函数")
    print("   - 通过 /api/news?sync_to_vector=true 参数自动同步")

if __name__ == "__main__":
    main()