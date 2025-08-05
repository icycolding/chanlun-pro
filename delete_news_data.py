#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除向量数据库中的新闻数据
"""

import os
import sys
from datetime import datetime

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("ChromaDB未安装，请先安装: pip install chromadb")
    sys.exit(1)

def delete_news_data():
    """删除ChromaDB中的所有新闻数据"""
    print("=== 删除向量数据库新闻数据 ===")
    
    db_path = "/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/chroma_db"
    
    if not os.path.exists(db_path):
        print(f"数据库路径不存在: {db_path}")
        return
    
    try:
        # 连接到ChromaDB
        client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=False
            )
        )
        
        # 检查集合是否存在
        try:
            collection = client.get_collection(name="news_vectors")
            total_count = collection.count()
            print(f"当前数据库记录总数: {total_count}")
            
            if total_count == 0:
                print("数据库中没有新闻数据，无需删除。")
                return
            
            # 确认删除操作
            print(f"\n警告：即将删除 {total_count} 条新闻记录！")
            print("此操作不可逆转，请确认是否继续。")
            
            # 在脚本中自动确认删除（如需手动确认，可以取消注释下面的代码）
            # confirm = input("输入 'YES' 确认删除所有数据: ")
            # if confirm != 'YES':
            #     print("操作已取消。")
            #     return
            
            print("\n开始删除数据...")
            
            # 方法1: 删除整个集合
            print("删除news_vectors集合...")
            client.delete_collection(name="news_vectors")
            print("✓ 集合删除成功")
            
            # 重新创建空集合
            print("重新创建空的news_vectors集合...")
            new_collection = client.create_collection(name="news_vectors")
            print("✓ 空集合创建成功")
            
            # 验证删除结果
            final_count = new_collection.count()
            print(f"\n删除后记录数: {final_count}")
            
            if final_count == 0:
                print("✓ 所有新闻数据已成功删除")
            else:
                print(f"✗ 删除可能不完整，仍有 {final_count} 条记录")
            
        except Exception as e:
            if "does not exist" in str(e).lower():
                print("news_vectors集合不存在，可能已经被删除或从未创建。")
            else:
                raise e
        
        print("\n=== 删除操作完成 ===")
        print(f"操作时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("数据库已清空，可以重新添加新闻数据。")
        
    except Exception as e:
        print(f"删除过程中出错: {e}")
        import traceback
        traceback.print_exc()

def show_database_info():
    """显示数据库信息"""
    print("=== 数据库信息 ===")
    
    db_path = "/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/chroma_db"
    
    if not os.path.exists(db_path):
        print(f"数据库路径不存在: {db_path}")
        return
    
    try:
        client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=False
            )
        )
        
        # 列出所有集合
        collections = client.list_collections()
        print(f"数据库路径: {db_path}")
        print(f"集合数量: {len(collections)}")
        
        for collection in collections:
            print(f"  - 集合名称: {collection.name}")
            try:
                count = collection.count()
                print(f"    记录数量: {count}")
            except Exception as e:
                print(f"    记录数量: 无法获取 ({e})")
        
    except Exception as e:
        print(f"获取数据库信息时出错: {e}")

if __name__ == "__main__":
    print("ChromaDB新闻数据删除工具\n")
    
    # 显示当前数据库状态
    show_database_info()
    print()
    
    # 执行删除操作
    delete_news_data()
    print()
    
    # 显示删除后的数据库状态
    show_database_info()