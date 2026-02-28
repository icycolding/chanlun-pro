#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EURUSD真实新闻搜索演示
展示从真实向量数据库中搜索到的EURUSD相关新闻
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

def demo_eurusd_real_news():
    """
    演示EURUSD真实新闻搜索结果
    """
    print("🔍 EURUSD真实新闻搜索演示")
    print("=" * 50)
    
    try:
        from news_vector_db import NewsVectorDB
        
        # 连接真实数据库
        vector_db = NewsVectorDB(db_path="./web/chanlun_chart/cl_app/chroma_db")
        stats = vector_db.get_collection_stats()
        
        print(f"✓ 数据库连接成功，包含 {stats.get('total_documents', 0)} 条新闻")
        
        # 设置搜索参数
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        # 重点测试查询
        key_queries = [
            ('EURUSD', '直接货币对搜索'),
            ('欧元兑美元', '中文表达搜索'),
            ('欧洲央行', '相关机构搜索'),
            ('美联储', '相关机构搜索'),
            ('EUR/USD', '标准格式搜索')
        ]
        
        total_found = 0
        all_results = []
        
        print("\n📰 搜索结果展示:")
        print("=" * 50)
        
        for query, description in key_queries:
            print(f"\n🔎 {description}: '{query}'")
            print("-" * 30)
            
            try:
                results = vector_db.semantic_search(
                    query=query,
                    n_results=3,  # 每个查询显示前3条
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat()
                )
                
                if results and len(results) > 0:
                    print(f"✅ 找到 {len(results)} 条相关新闻:")
                    total_found += len(results)
                    
                    for i, result in enumerate(results, 1):
                        title = result.get('title', '无标题')
                        similarity = result.get('similarity', 0)
                        source = result.get('source', '未知来源')
                        published_at = result.get('published_at', '未知时间')
                        body = result.get('body', '')[:100] + '...' if result.get('body') else '无内容预览'
                        
                        print(f"\n  📄 新闻 {i}:")
                        print(f"     标题: {title}")
                        print(f"     来源: {source}")
                        print(f"     时间: {published_at}")
                        print(f"     相似度: {similarity:.3f}")
                        print(f"     预览: {body}")
                        
                        # 保存到总结果中
                        all_results.append({
                            'query': query,
                            'title': title,
                            'source': source,
                            'similarity': similarity,
                            'published_at': published_at
                        })
                else:
                    print("❌ 未找到相关新闻")
                    
            except Exception as e:
                print(f"❌ 搜索出错: {str(e)}")
        
        # 总结展示
        print("\n" + "=" * 50)
        print("📊 搜索结果总结")
        print("=" * 50)
        
        print(f"🎯 总共找到: {total_found} 条EURUSD相关新闻")
        print(f"📅 搜索时间范围: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
        print(f"🗄