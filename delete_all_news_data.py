#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除关系数据库和向量数据库中的所有新闻数据
"""

import os
import sys
import datetime

# 添加项目路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import db

def delete_relational_db_news():
    """
    删除关系数据库中的新闻数据
    """
    print("=== 删除关系数据库新闻数据 ===")
    
    try:
        # 查询当前新闻数量
        current_count = db.news_count()
        print(f"当前关系数据库中新闻数量: {current_count}")
        
        if current_count == 0:
            print("关系数据库中没有新闻数据需要删除")
            return True
            
        # 删除所有新闻数据
        with db.Session() as session:
            from chanlun.db import TableByNews
            deleted_count = session.query(TableByNews).delete()
            session.commit()
            
        print(f"✅ 成功删除关系数据库中 {deleted_count} 条新闻记录")
        return True
        
    except Exception as e:
        print(f"❌ 删除关系数据库新闻数据失败: {str(e)}")
        return False

def delete_vector_db_news():
    """
    删除向量数据库中的新闻数据
    """
    print("\n=== 删除向量数据库新闻数据 ===")
    
    try:
        # 检查ChromaDB是否存在
        chroma_db_path = "./web/chanlun_chart/chroma_db"
        if not os.path.exists(chroma_db_path):
            print(f"向量数据库路径不存在: {chroma_db_path}")
            return True
            
        # 导入ChromaDB相关模块
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            print("❌ ChromaDB未安装，无法删除向量数据库数据")
            return False
            
        # 连接到ChromaDB
        client = chromadb.PersistentClient(
            path=chroma_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # 检查集合是否存在
        collections = client.list_collections()
        news_collection_exists = any(col.name == "news_vectors" for col in collections)
        
        if not news_collection_exists:
            print("向量数据库中没有 news_vectors 集合")
            return True
            
        # 获取集合
        collection = client.get_collection("news_vectors")
        
        # 获取当前记录数
        current_count = collection.count()
        print(f"当前向量数据库中新闻数量: {current_count}")
        
        if current_count == 0:
            print("向量数据库中没有新闻数据需要删除")
            return True
            
        # 删除集合
        client.delete_collection("news_vectors")
        print(f"✅ 成功删除向量数据库集合 news_vectors，包含 {current_count} 条记录")
        
        # 重新创建空集合
        client.create_collection(
            name="news_vectors",
            metadata={"hnsw:space": "cosine"}
        )
        print("✅ 重新创建了空的 news_vectors 集合")
        
        return True
        
    except Exception as e:
        print(f"❌ 删除向量数据库新闻数据失败: {str(e)}")
        return False

def show_database_status():
    """
    显示数据库状态
    """
    print("\n=== 数据库状态检查 ===")
    
    # 检查关系数据库
    try:
        relational_count = db.news_count()
        print(f"关系数据库新闻数量: {relational_count}")
    except Exception as e:
        print(f"关系数据库检查失败: {str(e)}")
    
    # 检查向量数据库
    try:
        chroma_db_path = "./web/chanlun_chart/chroma_db"
        if os.path.exists(chroma_db_path):
            import chromadb
            client = chromadb.PersistentClient(path=chroma_db_path)
            collections = client.list_collections()
            
            news_collection_exists = any(col.name == "news_vectors" for col in collections)
            if news_collection_exists:
                collection = client.get_collection("news_vectors")
                vector_count = collection.count()
                print(f"向量数据库新闻数量: {vector_count}")
            else:
                print("向量数据库新闻数量: 0 (集合不存在)")
        else:
            print("向量数据库新闻数量: 0 (数据库不存在)")
    except Exception as e:
        print(f"向量数据库检查失败: {str(e)}")

def main():
    """
    主函数
    """
    print("开始删除关系数据库和向量数据库中的新闻数据...")
    print(f"执行时间: {datetime.datetime.now()}")
    
    # 显示删除前的状态
    print("\n=== 删除前状态 ===")
    show_database_status()
    
    # 确认删除操作
    print("\n⚠️  警告: 此操作将删除所有新闻数据，无法恢复！")
    confirm = input("确认删除所有新闻数据？(输入 'yes' 确认): ")
    
    if confirm.lower() != 'yes':
        print("操作已取消")
        return
    
    # 执行删除操作
    success_relational = delete_relational_db_news()
    success_vector = delete_vector_db_news()
    
    # 显示删除后的状态
    print("\n=== 删除后状态 ===")
    show_database_status()
    
    # 总结
    print("\n=== 删除操作总结 ===")
    if success_relational and success_vector:
        print("✅ 所有新闻数据删除成功")
    elif success_relational:
        print("⚠️  关系数据库删除成功，向量数据库删除失败")
    elif success_vector:
        print("⚠️  向量数据库删除成功，关系数据库删除失败")
    else:
        print("❌ 所有数据库删除操作都失败")
    
    print(f"完成时间: {datetime.datetime.now()}")

if __name__ == "__main__":
    main()