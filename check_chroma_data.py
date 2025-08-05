#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查ChromaDB中存储的时间格式
"""

import os
import sys
import json
from datetime import datetime

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("ChromaDB未安装，请先安装: pip install chromadb")
    sys.exit(1)

def check_chroma_data():
    """检查ChromaDB中的数据格式"""
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
        
        # 获取集合
        try:
            collection = client.get_collection(name="news_vectors")
            print(f"找到集合 'news_vectors'，包含 {collection.count()} 条记录")
        except Exception as e:
            print(f"获取集合失败: {e}")
            # 列出所有集合
            collections = client.list_collections()
            print(f"可用集合: {[c.name for c in collections]}")
            return
        
        # 获取前10条记录
        print("\n=== 检查前10条记录的时间格式 ===")
        results = collection.get(
            limit=10,
            include=['metadatas', 'documents']
        )
        
        if not results['ids']:
            print("数据库中没有数据")
            return
        
        for i, (doc_id, metadata) in enumerate(zip(results['ids'], results['metadatas'])):
            print(f"\n记录 {i+1}: ID = {doc_id}")
            
            # 检查时间相关字段
            time_fields = ['published_at', 'created_at', 'timestamp']
            for field in time_fields:
                if field in metadata:
                    value = metadata[field]
                    print(f"  {field}: {value} (类型: {type(value)})")
                    
                    # 尝试解析时间
                    try:
                        if isinstance(value, str):
                            parsed_time = datetime.fromisoformat(value)
                            print(f"    -> 解析结果: {parsed_time}")
                            print(f"    -> 时区信息: {parsed_time.tzinfo}")
                    except Exception as parse_e:
                        print(f"    -> 解析失败: {parse_e}")
            
            # 显示其他重要字段
            important_fields = ['title', 'source', 'language', 'sentiment_score']
            for field in important_fields:
                if field in metadata:
                    value = metadata[field]
                    if field == 'title':
                        print(f"  {field}: {value[:50]}..." if len(str(value)) > 50 else f"  {field}: {value}")
                    else:
                        print(f"  {field}: {value}")
        
        # 统计时间格式
        print("\n=== 时间格式统计 ===")
        all_results = collection.get(include=['metadatas'])
        time_formats = {}
        
        for metadata in all_results['metadatas']:
            for field in ['published_at', 'created_at']:
                if field in metadata:
                    value = metadata[field]
                    if isinstance(value, str):
                        # 分析时间格式
                        if 'Z' in value:
                            format_type = 'UTC_Zulu'
                        elif '+08:00' in value:
                            format_type = 'China_Timezone'
                        elif '+' in value or value.count('-') > 2:
                            format_type = 'Other_Timezone'
                        else:
                            format_type = 'No_Timezone'
                        
                        key = f"{field}_{format_type}"
                        time_formats[key] = time_formats.get(key, 0) + 1
        
        for format_type, count in time_formats.items():
            print(f"  {format_type}: {count} 条记录")
        
        print(f"\n总计检查了 {len(all_results['metadatas'])} 条记录")
        
    except Exception as e:
        print(f"检查数据库时出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("开始检查ChromaDB中的时间格式...\n")
    check_chroma_data()
    print("\n检查完成！")