#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复ChromaDB中的时间格式，统一转换为中国时区
"""

import os
import sys
import json
from datetime import datetime
import pytz
from typing import List, Dict, Any

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("ChromaDB未安装，请先安装: pip install chromadb")
    sys.exit(1)

def normalize_datetime_to_china(dt_input):
    """
    统一时间格式转换函数，转换为中国时区
    """
    china_tz = pytz.timezone('Asia/Shanghai')
    
    try:
        if dt_input is None or dt_input == "":
            return datetime.now(china_tz).isoformat()
        
        if isinstance(dt_input, datetime):
            if dt_input.tzinfo is None:
                # 无时区信息，假设为UTC
                dt_utc = pytz.utc.localize(dt_input)
                dt_china = dt_utc.astimezone(china_tz)
            else:
                # 有时区信息，直接转换
                dt_china = dt_input.astimezone(china_tz)
            return dt_china.isoformat()
        
        if isinstance(dt_input, str):
            dt_input = dt_input.strip()
            if not dt_input:
                return datetime.now(china_tz).isoformat()
            
            try:
                if 'T' in dt_input:
                    if dt_input.endswith('Z'):
                        # Zulu时间 (UTC)
                        parsed_dt = datetime.fromisoformat(dt_input.replace('Z', '+00:00'))
                        dt_china = parsed_dt.astimezone(china_tz)
                    elif '+' in dt_input or dt_input.count('-') > 2:
                        # 带时区的ISO格式
                        parsed_dt = datetime.fromisoformat(dt_input)
                        dt_china = parsed_dt.astimezone(china_tz)
                    else:
                        # 无时区的ISO格式，假设为UTC
                        parsed_dt = datetime.fromisoformat(dt_input)
                        dt_utc = pytz.utc.localize(parsed_dt)
                        dt_china = dt_utc.astimezone(china_tz)
                    return dt_china.isoformat()
                else:
                    # 简单日期格式，假设为中国时区
                    parsed_dt = datetime.strptime(dt_input, '%Y-%m-%d')
                    dt_china = china_tz.localize(parsed_dt)
                    return dt_china.isoformat()
            except ValueError:
                print(f"无法解析时间格式: {dt_input}，使用当前中国时间")
                return datetime.now(china_tz).isoformat()
        
        # 其他类型，使用当前中国时间
        print(f"不支持的时间类型: {type(dt_input)}，使用当前中国时间")
        return datetime.now(china_tz).isoformat()
        
    except Exception as e:
        print(f"时间格式化失败: {str(e)}，使用当前中国时间")
        return datetime.now(china_tz).isoformat()

def fix_chroma_timezone():
    """
    修复ChromaDB中的时间格式
    """
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
            total_count = collection.count()
            print(f"找到集合 'news_vectors'，包含 {total_count} 条记录")
        except Exception as e:
            print(f"获取集合失败: {e}")
            return
        
        if total_count == 0:
            print("数据库中没有数据需要修复")
            return
        
        # 分批处理数据
        batch_size = 100
        processed_count = 0
        updated_count = 0
        
        print(f"\n开始修复时间格式，分批处理，每批 {batch_size} 条记录...")
        
        # 获取所有数据
        all_results = collection.get(
            include=['metadatas', 'documents', 'embeddings']
        )
        
        ids_to_update = []
        metadatas_to_update = []
        documents_to_update = []
        embeddings_to_update = []
        
        for i, (doc_id, metadata, document) in enumerate(zip(
            all_results['ids'], 
            all_results['metadatas'], 
            all_results['documents']
        )):
            
            original_metadata = metadata.copy()
            needs_update = False
            
            # 检查并修复 published_at
            if 'published_at' in metadata:
                original_time = metadata['published_at']
                normalized_time = normalize_datetime_to_china(original_time)
                if original_time != normalized_time:
                    metadata['published_at'] = normalized_time
                    needs_update = True
            
            # 检查并修复 created_at
            if 'created_at' in metadata:
                original_time = metadata['created_at']
                normalized_time = normalize_datetime_to_china(original_time)
                if original_time != normalized_time:
                    metadata['created_at'] = normalized_time
                    needs_update = True
            
            if needs_update:
                ids_to_update.append(doc_id)
                metadatas_to_update.append(metadata)
                documents_to_update.append(document)
                
                # 获取对应的embedding
                if all_results['embeddings'] is not None and i < len(all_results['embeddings']):
                    embeddings_to_update.append(all_results['embeddings'][i])
                else:
                    embeddings_to_update.append(None)
                
                updated_count += 1
                
                if updated_count % 50 == 0:
                    print(f"已标记 {updated_count} 条记录需要更新...")
            
            processed_count += 1
        
        print(f"\n扫描完成：共处理 {processed_count} 条记录，需要更新 {updated_count} 条记录")
        
        if updated_count == 0:
            print("所有记录的时间格式都已正确，无需更新")
            return
        
        # 确认是否继续
        response = input(f"\n是否继续更新这 {updated_count} 条记录？(y/N): ")
        if response.lower() != 'y':
            print("操作已取消")
            return
        
        print("\n开始更新数据...")
        
        # 分批更新数据
        batch_start = 0
        while batch_start < len(ids_to_update):
            batch_end = min(batch_start + batch_size, len(ids_to_update))
            
            batch_ids = ids_to_update[batch_start:batch_end]
            batch_metadatas = metadatas_to_update[batch_start:batch_end]
            batch_documents = documents_to_update[batch_start:batch_end]
            batch_embeddings = embeddings_to_update[batch_start:batch_end]
            
            try:
                # 删除旧记录
                collection.delete(ids=batch_ids)
                
                # 添加更新后的记录
                add_params = {
                    'ids': batch_ids,
                    'documents': batch_documents,
                    'metadatas': batch_metadatas
                }
                
                # 如果有embeddings，添加到参数中
                if any(emb is not None for emb in batch_embeddings):
                    valid_embeddings = [emb for emb in batch_embeddings if emb is not None]
                    if len(valid_embeddings) == len(batch_ids):
                        add_params['embeddings'] = valid_embeddings
                
                collection.add(**add_params)
                
                print(f"已更新第 {batch_start + 1}-{batch_end} 条记录")
                
            except Exception as e:
                print(f"更新第 {batch_start + 1}-{batch_end} 条记录时出错: {e}")
                continue
            
            batch_start = batch_end
        
        print(f"\n时间格式修复完成！共更新了 {updated_count} 条记录")
        
        # 验证修复结果
        print("\n验证修复结果...")
        verify_results = collection.get(limit=5, include=['metadatas'])
        
        for i, metadata in enumerate(verify_results['metadatas']):
            print(f"\n验证记录 {i+1}:")
            for field in ['published_at', 'created_at']:
                if field in metadata:
                    value = metadata[field]
                    print(f"  {field}: {value}")
                    try:
                        parsed_time = datetime.fromisoformat(value)
                        print(f"    -> 时区: {parsed_time.tzinfo}")
                        if '+08:' in value:
                            print(f"    -> ✓ 已转换为中国时区")
                        else:
                            print(f"    -> ⚠ 可能未正确转换")
                    except Exception as e:
                        print(f"    -> ✗ 解析失败: {e}")
        
    except Exception as e:
        print(f"修复过程中出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("开始修复ChromaDB中的时间格式...\n")
    print("⚠️  警告：此操作将修改数据库中的所有时间字段")
    print("⚠️  建议在操作前备份数据库")
    print()
    
    # 确认操作
    response = input("是否继续？(y/N): ")
    if response.lower() != 'y':
        print("操作已取消")
        sys.exit(0)
    
    fix_chroma_timezone()
    print("\n修复完成！")