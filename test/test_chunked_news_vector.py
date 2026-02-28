#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试改造后的新闻向量数据库块功能
验证新闻切分、存储、搜索和删除功能
"""

import sys
import os
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app')

from news_vector_db import NewsVectorDB
import datetime
import json

def test_chunked_news_functionality():
    """
    测试改造后的新闻向量数据库功能
    """
    print("=== 测试改造后的新闻向量数据库块功能 ===")
    
    # 初始化数据库
    db = NewsVectorDB(db_path="./test_chroma_db")
    
    # 准备测试新闻数据
    test_news = {
        'news_id': 'test_chunk_001',
        'title': '美联储主席鲍威尔发表重要讲话：通胀压力持续，货币政策将保持紧缩',
        'body': '''美联储主席鲍威尔在杰克逊霍尔全球央行年会上发表了备受关注的讲话。他强调，尽管近期通胀数据有所缓解，但通胀压力依然存在，美联储将继续致力于将通胀率降至2%的目标水平。
        
        鲍威尔指出，劳动力市场仍然紧张，工资增长速度超过了生产率增长，这可能推高服务业通胀。他表示，美联储准备在必要时进一步提高利率，以确保通胀预期得到良好锚定。
        
        对于市场关心的降息时机，鲍威尔表示，任何政策调整都将基于经济数据，特别是通胀和就业数据的变化。他强调，美联储不会过早放松货币政策，避免重蹈1970年代通胀失控的覆辙。
        
        这一讲话对金融市场产生了重要影响。美元指数在讲话后走强，10年期美债收益率上升，股市则出现下跌。分析师认为，鲍威尔的鹰派立场表明美联储在抗击通胀方面的决心，这可能意味着利率将在更长时间内保持在高位。''',
        'source': '路透社',
        'published_at': '2024-01-15T10:30:00Z',
        'category': '央行政策',
        'sentiment_score': -0.2,
        'importance_score': 0.9,
        'language': 'zh'
    }
    
    print("\n1. 测试新闻添加（块切分）功能")
    success = db.add_news(test_news)
    print(f"新闻添加结果: {success}")
    
    # 获取集合统计信息
    stats = db.get_collection_stats()
    print(f"数据库统计: {stats}")
    
    print("\n2. 测试语义搜索功能（块级搜索+合并）")
    search_queries = [
        "美联储货币政策",
        "通胀压力",
        "利率调整",
        "金融市场影响"
    ]
    
    for query in search_queries:
        print(f"\n搜索查询: '{query}'")
        results = db.semantic_search(query, n_results=3)
        
        for i, result in enumerate(results, 1):
            print(f"  结果 {i}:")
            print(f"    新闻ID: {result.get('news_id')}")
            print(f"    标题: {result.get('title', '')[:50]}...")
            print(f"    匹配分数: {result.get('score', 0):.4f}")
            print(f"    总块数: {result.get('total_chunks', 0)}")
            print(f"    匹配块数: {result.get('matched_chunks', 0)}")
            print(f"    内容预览: {result.get('content', '')[:100]}...")
            print()
    
    print("\n3. 测试相似新闻查找功能")
    similar_news = db.get_similar_news('test_chunk_001', n_results=3)
    print(f"找到 {len(similar_news)} 条相似新闻")
    
    print("\n4. 测试市场相关新闻获取")
    market_news = db.get_market_relevant_news(min_relevance=0.1, limit=5)
    print(f"找到 {len(market_news)} 条市场相关新闻")
    
    for news in market_news:
        print(f"  - {news.get('title', '')[:50]}... (相关性: {news.get('market_relevance', 0):.3f})")
    
    print("\n5. 测试情感分析统计")
    sentiment_stats = db.get_sentiment_analysis()
    print(f"情感分析统计: {sentiment_stats}")
    
    print("\n6. 测试新闻删除功能（删除所有块）")
    delete_success = db.delete_news('test_chunk_001')
    print(f"新闻删除结果: {delete_success}")
    
    # 验证删除后的统计
    final_stats = db.get_collection_stats()
    print(f"删除后统计: {final_stats}")
    
    print("\n=== 测试完成 ===")

def test_multiple_news_chunking():
    """
    测试多条新闻的块处理
    """
    print("\n=== 测试多条新闻的块处理 ===")
    
    db = NewsVectorDB(db_path="./test_chroma_db")
    
    # 准备多条测试新闻
    news_list = [
        {
            'news_id': 'multi_test_001',
            'title': '欧洲央行维持利率不变，关注通胀走势',
            'body': '欧洲央行在最新的货币政策会议上决定维持主要再融资利率在4.5%不变。央行行长拉加德表示，虽然通胀有所回落，但核心通胀仍然偏高。央行将继续密切关注经济数据，为未来的政策调整做准备。',
            'source': '彭博社',
            'published_at': '2024-01-16T14:00:00Z',
            'category': '央行政策',
            'sentiment_score': 0.1,
            'importance_score': 0.8
        },
        {
            'news_id': 'multi_test_002', 
            'title': '中国人民银行降准0.5个百分点，释放流动性约1万亿元',
            'body': '中国人民银行宣布下调金融机构存款准备金率0.5个百分点，此次降准将释放长期资金约1万亿元。央行表示，此举旨在保持银行体系流动性合理充裕，支持实体经济发展。市场分析认为，这是货币政策边际宽松的信号。',
            'source': '新华社',
            'published_at': '2024-01-17T09:15:00Z',
            'category': '央行政策',
            'sentiment_score': 0.3,
            'importance_score': 0.9
        }
    ]
    
    # 添加多条新闻
    for news in news_list:
        success = db.add_news(news)
        print(f"添加新闻 {news['news_id']}: {success}")
    
    # 测试跨新闻搜索
    print("\n测试跨新闻块搜索:")
    results = db.semantic_search("央行货币政策", n_results=5)
    
    for i, result in enumerate(results, 1):
        print(f"结果 {i}: {result.get('news_id')} - {result.get('title', '')[:40]}... (分数: {result.get('score', 0):.4f})")
    
    # 清理测试数据
    for news in news_list:
        db.delete_news(news['news_id'])
        print(f"删除新闻 {news['news_id']}")
    
    print("=== 多新闻测试完成 ===")

if __name__ == "__main__":
    try:
        # 基础功能测试
        test_chunked_news_functionality()
        
        # 多新闻测试
        test_multiple_news_chunking()
        
    except Exception as e:
        print(f"测试过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()