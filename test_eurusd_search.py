#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EURUSD新闻搜索功能
"""

import os
import sys
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

from news_vector_db import NewsVectorDB

def add_test_eurusd_news():
    """
    添加EURUSD相关的测试新闻数据
    """
    print("=== 添加EURUSD测试新闻数据 ===")
    
    # 初始化向量数据库
    vector_db = NewsVectorDB(db_path="./web/chanlun_chart/cl_app/chroma_db")
    
    # 测试新闻数据
    test_news = [
        {
            "news_id": "test_eurusd_001",
            "title": "欧洲央行维持利率不变，欧元兑美元汇率波动",
            "body": "欧洲央行今日宣布维持主要再融资利率在4.25%不变，这一决定符合市场预期。欧元兑美元汇率在消息公布后出现波动，目前交易在1.0850附近。分析师认为，央行的鸽派立场可能对欧元构成压力。",
            "published_at": (datetime.now() - timedelta(hours=2)).isoformat(),
            "source": "财经新闻网",
            "url": "https://example.com/news1",
            "category": "央行政策"
        },
        {
            "news_id": "test_eurusd_002",
            "title": "美联储官员暗示可能进一步加息，美元走强",
            "body": "美联储官员在最新讲话中暗示，如果通胀持续高企，央行可能会考虑进一步加息。这一表态推动美元指数上涨，欧元兑美元汇率承压下跌至1.0820。市场关注本周五的非农就业数据。",
            "published_at": (datetime.now() - timedelta(hours=4)).isoformat(),
            "source": "路透社",
            "url": "https://example.com/news2",
            "category": "货币政策"
        },
        {
            "news_id": "test_eurusd_003",
            "title": "欧元区通胀数据超预期，EURUSD技术分析",
            "body": "欧元区11月通胀率达到2.4%，超出市场预期的2.2%。这一数据公布后，欧元兑美元短线拉升至1.0880。技术分析显示，EURUSD如能突破1.0900阻力位，有望进一步上涨至1.0950。",
            "published_at": (datetime.now() - timedelta(hours=6)).isoformat(),
            "source": "FX168",
            "url": "https://example.com/news3",
            "category": "经济数据"
        },
        {
            "news_id": "test_eurusd_004",
            "title": "德国制造业PMI数据疲软，欧元承压",
            "body": "德国11月制造业PMI初值为42.6，低于预期的44.0，连续第17个月处于收缩区间。疲软的经济数据令市场对欧洲经济前景担忧加剧，欧元兑美元汇率下跌至1.0800下方。",
            "published_at": (datetime.now() - timedelta(hours=8)).isoformat(),
            "source": "彭博社",
            "url": "https://example.com/news4",
            "category": "经济数据"
        },
        {
            "news_id": "test_eurusd_005",
            "title": "EURUSD交易策略：关注1.0850关键支撑位",
            "body": "从技术面看，欧元兑美元目前在1.0850附近寻求支撑。如果该位置失守，下一个支撑位在1.0800。反之，如果能够站稳1.0850，则有望挑战1.0900阻力位。建议投资者密切关注美国通胀数据和欧洲央行官员讲话。",
            "published_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "source": "汇通网",
            "url": "https://example.com/news5",
            "category": "技术分析"
        }
    ]
    
    # 添加新闻到向量数据库
    success_count = 0
    for i, news in enumerate(test_news, 1):
        print(f"添加新闻 {i}/{len(test_news)}: {news['title'][:30]}...")
        if vector_db.add_news(news):
            success_count += 1
        else:
            print(f"  ❌ 添加失败")
    
    print(f"\n✅ 成功添加 {success_count}/{len(test_news)} 条新闻")
    return vector_db

def test_eurusd_search(vector_db):
    """
    测试EURUSD相关新闻搜索
    """
    print("\n=== 测试EURUSD新闻搜索 ===")
    
    # 测试查询列表
    test_queries = [
        "EURUSD汇率走势",
        "欧元美元",
        "欧洲央行利率政策",
        "美联储加息",
        "欧元区通胀",
        "德国PMI数据",
        "技术分析支撑阻力"
    ]
    
    for query in test_queries:
        print(f"\n--- 搜索查询: '{query}' ---")
        
        # 使用semantic_search_reimagined方法
        results = vector_db.semantic_search_reimagined(
            query=query,
            n_results=3
        )
        
        if results:
            print(f"找到 {len(results)} 条相关新闻:")
            for i, result in enumerate(results, 1):
                print(f"  {i}. {result.get('title', 'N/A')[:50]}...")
                print(f"     相似度: {result.get('similarity', 0):.3f}")
                print(f"     发布时间: {result.get('published_at', 'N/A')}")
        else:
            print("  ❌ 未找到相关新闻")

def test_keyword_filtering(vector_db):
    """
    测试关键词过滤功能
    """
    print("\n=== 测试关键词过滤 ===")
    
    # 测试关键词过滤
    test_cases = [
        {
            "query": "央行政策",
            "keywords": ["央行", "利率"],
            "description": "搜索央行相关新闻"
        },
        {
            "query": "经济数据",
            "keywords": ["PMI", "通胀"],
            "description": "搜索经济数据相关新闻"
        },
        {
            "query": "技术分析",
            "keywords": ["支撑", "阻力", "技术"],
            "description": "搜索技术分析相关新闻"
        }
    ]
    
    for case in test_cases:
        print(f"\n--- {case['description']} ---")
        print(f"查询: '{case['query']}', 关键词: {case['keywords']}")
        
        results = vector_db.semantic_search_reimagined(
            query=case['query'],
            keywords=case['keywords'],
            n_results=3
        )
        
        if results:
            print(f"找到 {len(results)} 条相关新闻:")
            for i, result in enumerate(results, 1):
                print(f"  {i}. {result.get('title', 'N/A')[:50]}...")
                print(f"     关键词: {result.get('keywords', [])}")
        else:
            print("  ❌ 未找到相关新闻")

def test_time_filtering(vector_db):
    """
    测试时间过滤功能
    """
    print("\n=== 测试时间过滤 ===")
    
    # 测试最近4小时的新闻
    start_time = (datetime.now() - timedelta(hours=4)).isoformat()
    
    print(f"搜索最近4小时的新闻 (从 {start_time})")
    
    results = vector_db.semantic_search_reimagined(
        query="EURUSD",
        start_date=start_time,
        n_results=5
    )
    
    if results:
        print(f"找到 {len(results)} 条最近的新闻:")
        for i, result in enumerate(results, 1):
            print(f"  {i}. {result.get('title', 'N/A')[:50]}...")
            print(f"     发布时间: {result.get('published_at', 'N/A')}")
    else:
        print("  ❌ 未找到最近的新闻")

def main():
    """
    主测试函数
    """
    print("EURUSD新闻搜索功能测试")
    print("=" * 50)
    
    try:
        # 1. 添加测试数据
        vector_db = add_test_eurusd_news()
        
        # 2. 检查数据库状态
        stats = vector_db.get_collection_stats()
        print(f"\n数据库状态: {stats}")
        
        # 3. 测试基本搜索
        test_eurusd_search(vector_db)
        
        # 4. 测试关键词过滤
        test_keyword_filtering(vector_db)
        
        # 5. 测试时间过滤
        test_time_filtering(vector_db)
        
        print("\n=== 测试完成 ===")
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()