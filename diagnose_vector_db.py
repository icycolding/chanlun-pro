#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量数据库诊断脚本
用于检查向量数据库的状态和数据完整性
"""

import sys
import os
import logging
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / 'web' / 'chanlun_chart'))
sys.path.insert(0, str(project_root / 'src'))

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def diagnose_vector_db():
    """
    诊断向量数据库状态
    """
    try:
        # 导入向量数据库模块
        from cl_app.news_vector_db import get_vector_db
        
        logger.info("=== 向量数据库诊断开始 ===")
        
        # 1. 初始化数据库
        db_path = "./web/chanlun_chart/cl_app/chroma_db"
        logger.info(f"数据库路径: {db_path}")
        
        # 检查数据库目录是否存在
        if os.path.exists(db_path):
            logger.info(f"✓ 数据库目录存在")
            # 列出目录内容
            files = os.listdir(db_path)
            logger.info(f"数据库目录内容: {files}")
        else:
            logger.warning(f"✗ 数据库目录不存在: {db_path}")
        
        # 2. 获取向量数据库实例
        logger.info("初始化向量数据库实例...")
        vector_db = get_vector_db(db_path=db_path)
        
        if vector_db is None:
            logger.error("✗ 向量数据库实例初始化失败")
            return False
        
        logger.info("✓ 向量数据库实例初始化成功")
        
        # 3. 检查数据库连接
        logger.info("检查数据库连接...")
        if vector_db.collection is None:
            logger.error("✗ 数据库集合未初始化")
            return False
        
        logger.info(f"✓ 数据库集合已初始化: {vector_db.collection.name}")
        
        # 4. 获取统计信息
        logger.info("获取数据库统计信息...")
        stats = vector_db.get_collection_stats()
        logger.info(f"统计信息: {stats}")
        
        total_docs = stats.get('total_documents', 0)
        if total_docs == 0:
            logger.warning("✗ 数据库中没有文档")
        else:
            logger.info(f"✓ 数据库中有 {total_docs} 个文档")
        
        # 5. 测试搜索功能
        logger.info("测试搜索功能...")
        test_query = "EURUSD"
        search_results = vector_db.semantic_search(test_query, n_results=5)
        
        if not search_results:
            logger.warning(f"✗ 搜索 '{test_query}' 返回空结果")
        else:
            logger.info(f"✓ 搜索 '{test_query}' 返回 {len(search_results)} 个结果")
            for i, result in enumerate(search_results[:3]):
                logger.info(f"  结果 {i+1}: {result.get('title', 'N/A')[:50]}...")
        
        # 6. 检查嵌入模型
        logger.info("检查嵌入模型...")
        if hasattr(vector_db, 'embedding_model') and vector_db.embedding_model is None:
            logger.warning("✗ 嵌入模型未加载")
        else:
            logger.info(f"✓ 嵌入模型配置: {vector_db.model_name}")
        
        # 7. 测试添加新闻功能
        logger.info("测试添加新闻功能...")
        test_news = {
            'news_id': 'test_diagnose_001',
            'title': '测试新闻标题 - EURUSD汇率分析',
            'body': '这是一条测试新闻，用于验证向量数据库的添加功能。EURUSD汇率今日表现良好。',
            'source': '测试来源',
            'published_at': '2024-01-15T10:00:00+08:00',
            'category': '外汇',
            'sentiment_score': 0.6,
            'importance_score': 0.7,
            'language': 'zh'
        }
        
        add_result = vector_db.add_news(test_news)
        if add_result:
            logger.info("✓ 测试新闻添加成功")
            
            # 重新获取统计信息
            new_stats = vector_db.get_collection_stats()
            new_total = new_stats.get('total_documents', 0)
            logger.info(f"添加后文档数量: {new_total}")
            
            # 测试搜索刚添加的新闻
            search_test_results = vector_db.semantic_search("测试新闻", n_results=3)
            if search_test_results:
                logger.info(f"✓ 能够搜索到刚添加的测试新闻: {len(search_test_results)} 个结果")
            else:
                logger.warning("✗ 无法搜索到刚添加的测试新闻")
        else:
            logger.error("✗ 测试新闻添加失败")
        
        logger.info("=== 向量数据库诊断完成 ===")
        return True
        
    except ImportError as e:
        logger.error(f"导入错误: {e}")
        logger.error("请确保已安装所需依赖: chromadb, sentence-transformers, jieba")
        return False
    except Exception as e:
        logger.error(f"诊断过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """
    主函数
    """
    logger.info("开始向量数据库诊断...")
    success = diagnose_vector_db()
    
    if success:
        logger.info("诊断完成")
    else:
        logger.error("诊断失败")
        sys.exit(1)

if __name__ == "__main__":
    main()