#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查ChromaDB中关键字是否已正确迁移到文档中。
"""

import os
import sys

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("ChromaDB未安装，请先安装: pip install chromadb")
    sys.exit(1)

# --- 配置 ---
DB_PATH = "/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/chroma_db"
COLLECTION_NAME = "news_vectors"

def check_keyword_migration():
    """连接到ChromaDB并检查一条记录的文档和元数据。"""
    if not os.path.exists(DB_PATH):
        print(f"数据库路径不存在: {DB_PATH}")
        return

    try:
        # 连接到ChromaDB
        client = chromadb.PersistentClient(
            path=DB_PATH,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=False
            )
        )

        # 获取集合
        try:
            collection = client.get_collection(name=COLLECTION_NAME)
            print(f"成功连接到集合 '{COLLECTION_NAME}'，包含 {collection.count()} 条记录。")
        except Exception as e:
            print(f"获取集合 '{COLLECTION_NAME}' 失败: {e}")
            collections = client.list_collections()
            if collections:
                print(f"可用的集合: {[c.name for c in collections]}")
            else:
                print("数据库中没有可用的集合。")
            return

        # 获取一条记录进行检查
        print("\n--- 正在获取一条记录进行检查 ---")
        results = collection.get(
            limit=1,
            include=['metadatas', 'documents']
        )

        if not results or not results.get('ids'):
            print("无法从集合中获取任何记录，集合可能为空。")
            return

        doc_id = results['ids'][0]
        document = results['documents'][0]
        metadata = results['metadatas'][0]

        print(f"\n--- 检查记录 (ID: {doc_id}) ---")

        # 1. 打印文档内容
        print("\n[文档内容]:")
        print(document)

        # 2. 打印元数据
        print("\n[元数据]:")
        for key, value in metadata.items():
            print(f"  - {key}: {value}")

        # 3. 验证关键词迁移
        print("\n[验证结果]:")
        if 'keywords' in metadata:
            print("  - ❌ 失败: 'keywords' 字段仍然存在于元数据中。")
        else:
            print("  - ✅ 成功: 'keywords' 字段已从元数据中移除。")

        if "Keywords:" in document:
            print("  - ✅ 成功: 文档内容中找到了 'Keywords:' 标记。")
        else:
            print("  - ⚠️  注意: 文档内容中未找到 'Keywords:' 标记。请手动检查关键词是否已附加。")

    except Exception as e:
        print(f"\n检查数据库时发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("开始检查ChromaDB中的关键词迁移情况...")
    check_keyword_migration()
    print("\n检查完成！")