#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移脚本，用于更新 ChromaDB 中现有新闻的 keywords 字段。

背景：
旧版 `add_news` 方法将 keywords 存储为 JSON 字符串。
新版 `add_news` 方法将 keywords 存储为 List[str]。

此脚本将执行以下操作：
1. 连接到现有的 ChromaDB 数据库。
2. 遍历所有新闻文档。
3. 检查 `keywords` 字段的类型。
4. 如果是字符串，则将其解析为列表。
5. 如果是列表，则保持不变。
6. （可选）重新提取关键词以确保一致性。
7. 更新文档的元数据。
"""

import os
import sys
import json
import logging
from typing import List, Dict, Any

# -- 添加项目根目录到 sys.path --
# 这对于在脚本中直接导入项目模块至关重要
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ''))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))
# -- 完成路径添加 --

from web.chanlun_chart.cl_app.news_vector_db import NewsVectorDB

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def migrate_keywords_in_db():
    """
    主迁移函数
    """
    logger.info("开始关键词迁移...")
    
    try:
        # 明确指定数据库路径，确保连接到正确的数据库
        db_path = os.path.join(project_root, "web", "chanlun_chart", "chroma_db")
        logger.info(f"使用数据库路径: {db_path}")
        
        if not os.path.exists(db_path):
            logger.error(f"数据库路径不存在: {db_path}")
            logger.error("请确认路径是否正确，或者数据库是否已初始化。")
            return

        db = NewsVectorDB(db_path=db_path)
        
        if db.collection is None:
            logger.error("无法初始化数据库集合。")
            return

        total_records = db.collection.count()
        logger.info(f"数据库中总记录数: {total_records}")

        if total_records == 0:
            logger.info("数据库为空，无需迁移。")
            return

        batch_size = 100
        updated_count = 0
        processed_ids = set()

        for offset in range(0, total_records, batch_size):
            logger.info(f"正在处理批次: {offset} - {offset + batch_size}")
            batch = db.collection.get(offset=offset, limit=batch_size, include=["metadatas", "documents"])
            
            ids_to_update = []
            metadatas_to_update = []

            for i, doc_id in enumerate(batch['ids']):
                if doc_id in processed_ids:
                    continue
                processed_ids.add(doc_id)

                metadata = batch['metadatas'][i]
                document = batch['documents'][i]
                current_keywords = metadata.get('keywords')

                needs_update = False
                new_keywords = []

                if isinstance(current_keywords, str):
                    try:
                        # 尝试解析旧的JSON字符串格式
                        parsed_keywords = json.loads(current_keywords)
                        if isinstance(parsed_keywords, list):
                            new_keywords = parsed_keywords
                        else:
                            # 如果解析出来不是列表，则重新提取
                            new_keywords = db._extract_keywords(document)
                        needs_update = True
                    except (json.JSONDecodeError, TypeError):
                        # 如果解析失败，说明可能是普通字符串或其他格式，重新提取
                        new_keywords = db._extract_keywords(document)
                        needs_update = True
                elif current_keywords is None:
                    # 如果没有关键词，则提取
                    new_keywords = db._extract_keywords(document)
                    needs_update = True
                else:
                    # 已经是列表或其他格式，可以选择跳过或强制重新提取
                    # 这里我们选择信任现有的列表格式，除非需要强制刷新
                    pass

                if needs_update:
                    # ChromaDB的update方法不支持列表，我们必须将其转换回JSON字符串
                    metadata['keywords'] = json.dumps(new_keywords, ensure_ascii=False)
                    ids_to_update.append(doc_id)
                    metadatas_to_update.append(metadata)
            
            if ids_to_update:
                logger.info(f"在本批次中找到 {len(ids_to_update)} 条记录需要更新。")
                db.collection.update(
                    ids=ids_to_update,
                    metadatas=metadatas_to_update
                )
                updated_count += len(ids_to_update)
                logger.info(f"成功更新 {len(ids_to_update)} 条记录。")
            else:
                logger.info("本批次中没有需要更新的记录。")

        logger.info(f"迁移完成！总共处理了 {len(processed_ids)} 条独立记录，更新了 {updated_count} 条记录的关键词。")

    except Exception as e:
        logger.error(f"迁移过程中发生严重错误: {e}", exc_info=True)

if __name__ == "__main__":
    migrate_keywords_in_db()