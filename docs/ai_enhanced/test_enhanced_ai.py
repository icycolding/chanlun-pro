#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.abspath('.')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from chanlun.tools.ai_analyse_enhanced import AIAnalyseEnhanced
from chanlun.tools.knowledge_base import KnowledgeBase

def test_enhanced_ai_analysis():
    """
    测试增强版AI分析功能
    """
    print("=== 测试增强版AI分析功能 ===")
    
    # 创建增强版AI分析实例
    ai = AIAnalyseEnhanced("a", kb_name="test_chanlun_kb")
    
    # 1. 查看知识库统计信息
    print("\n1. 知识库统计信息:")
    stats = ai.get_knowledge_stats()
    print(f"   总文档数: {stats['total_documents']}")
    print(f"   分类: {stats['categories']}")
    
    # 2. 添加自定义知识
    print("\n2. 添加自定义知识:")
    custom_knowledge = [
        {
            "title": "一买点的实战应用",
            "content": "一买点是指在下跌趋势中，当价格跌破前一个中枢的下沿后，出现的第一个买入机会。实战中需要注意：1）确认中枢已经形成；2）价格确实跌破中枢下沿；3）出现背驰或其他买入信号。风险控制：止损位设在中枢下沿下方。",
            "category": "买卖点"
        },
        {
            "title": "背驰的判断方法",
            "content": "背驰是缠论中重要的买卖信号。判断背驰需要：1）比较相邻两段走势的力度；2）使用MACD等指标辅助判断；3）确认走势结构完整。背驰分为趋势背驰和盘整背驰，趋势背驰信号更强。",
            "category": "技术指标"
        },
        {
            "title": "中枢扩展的处理",
            "content": "当价格在中枢内震荡时，可能出现中枢扩展。处理方法：1）重新定义中枢边界；2）等待明确的突破信号；3）在中枢内可以进行高抛低吸操作。注意中枢扩展往往意味着方向选择的关键时刻。",
            "category": "中枢理论"
        }
    ]
    
    for knowledge in custom_knowledge:
        success = ai.add_knowledge(
            knowledge["title"], 
            knowledge["content"], 
            knowledge["category"]
        )
        print(f"   添加 '{knowledge['title']}': {'成功' if success else '失败'}")
    
    # 3. 测试知识搜索
    print("\n3. 测试知识搜索:")
    search_queries = ["一买点", "背驰", "中枢", "线段"]
    
    for query in search_queries:
        print(f"\n   搜索: '{query}'")
        results = ai.search_knowledge(query, top_k=2)
        for i, result in enumerate(results, 1):
            print(f"     {i}. {result['title']} (相似度: {result['similarity']:.3f})")
            print(f"        分类: {result['category']}")
            print(f"        内容: {result['content'][:50]}...")
    
    # 4. 测试按分类搜索
    print("\n4. 测试按分类搜索:")
    categories = ai.get_knowledge_stats()["categories"]
    for category in categories[:3]:  # 只测试前3个分类
        print(f"\n   分类 '{category}' 的知识:")
        results = ai.search_knowledge("理论", top_k=2, category=category)
        for i, result in enumerate(results, 1):
            print(f"     {i}. {result['title']} (相似度: {result['similarity']:.3f})")
    
    # 5. 模拟增强分析（不实际调用AI接口）
    print("\n5. 模拟增强分析流程:")
    print("   注意: 这里只演示知识库集成，不实际调用AI接口")
    
    # 模拟缠论数据的搜索关键词提取
    mock_queries = ["一买点", "背驰理论", "中枢理论"]
    print(f"   模拟提取的搜索关键词: {mock_queries}")
    
    # 为每个关键词搜索相关知识
    all_knowledge = []
    for query in mock_queries:
        results = ai.search_knowledge(query, top_k=1)
        all_knowledge.extend(results)
    
    # 去重并排序
    seen_ids = set()
    unique_knowledge = []
    for doc in all_knowledge:
        if doc['id'] not in seen_ids:
            unique_knowledge.append(doc)
            seen_ids.add(doc['id'])
    
    unique_knowledge.sort(key=lambda x: x['similarity'], reverse=True)
    unique_knowledge = unique_knowledge[:3]  # 限制为3个文档
    
    print(f"   找到 {len(unique_knowledge)} 个相关知识点:")
    for i, doc in enumerate(unique_knowledge, 1):
        print(f"     {i}. {doc['title']} (相似度: {doc['similarity']:.3f})")
    
    # 6. 展示知识增强提示词的构建
    print("\n6. 知识增强提示词示例:")
    if unique_knowledge:
        knowledge_prompt = "\n## 相关缠论理论知识\n\n"
        knowledge_prompt += "以下是相关的缠论理论知识，请结合这些理论进行分析：\n\n"
        
        for i, doc in enumerate(unique_knowledge, 1):
            knowledge_prompt += f"### 知识点 {i}: {doc['title']}\n"
            knowledge_prompt += f"**分类**: {doc['category']}\n"
            knowledge_prompt += f"**内容**: {doc['content']}\n\n"
        
        knowledge_prompt += "---\n\n"
        knowledge_prompt += "**分析要求**：\n"
        knowledge_prompt += "1. 请结合以上理论知识，对当前缠论数据进行深入分析\n"
        knowledge_prompt += "2. 重点关注当前走势与理论的匹配程度\n"
        knowledge_prompt += "3. 基于理论知识，给出具体的操作建议\n"
        knowledge_prompt += "4. 如果发现与理论不符的情况，请特别说明\n"
        
        print("   知识增强提示词长度:", len(knowledge_prompt))
        print("   提示词预览:")
        print(knowledge_prompt[:300] + "...")
    
    print("\n=== 测试完成 ===")
    print("\n使用说明:")
    print("1. 使用 ai.analyse_with_knowledge(code, frequency) 进行增强分析")
    print("2. 设置 use_knowledge=True 启用知识库增强")
    print("3. 通过 knowledge_categories 参数限制搜索分类")
    print("4. 通过 max_knowledge_docs 参数控制引用的知识文档数量")
    print("\n示例调用:")
    print("result = ai.analyse_with_knowledge('000001', '30m', use_knowledge=True, knowledge_categories=['买卖点', '技术指标'], max_knowledge_docs=3)")

def test_knowledge_base_operations():
    """
    测试知识库的基本操作
    """
    print("\n=== 测试知识库基本操作 ===")
    
    # 创建知识库实例
    kb = KnowledgeBase("test_operations_kb")
    
    # 添加测试文档
    test_docs = [
        ("缠论基础", "缠论是一套完整的技术分析理论体系", "基础理论"),
        ("笔的定义", "笔是缠论中的基本单位，由顶底分型构成", "基础理论"),
        ("线段的定义", "线段是由笔构成的更高级别结构", "基础理论"),
        ("一买点详解", "一买点是重要的买入时机", "买卖点"),
        ("MACD背驰", "MACD是判断背驰的重要工具", "技术指标")
    ]
    
    print("\n1. 添加测试文档:")
    for title, content, category in test_docs:
        success = kb.add_document(title, content, category)
        print(f"   添加 '{title}': {'成功' if success else '失败'}")
    
    print(f"\n2. 知识库统计: 总文档数 {kb.get_document_count()}")
    print(f"   分类: {kb.get_categories()}")
    
    print("\n3. 搜索测试:")
    search_results = kb.search("买点", top_k=3)
    for result in search_results:
        print(f"   - {result['title']}: {result['similarity']:.3f}")
    
    print("\n4. 按分类搜索:")
    category_results = kb.search("理论", top_k=2, category="基础理论")
    for result in category_results:
        print(f"   - {result['title']}: {result['similarity']:.3f}")
    
    print("\n5. 保存和加载测试:")
    # 保存当前知识库
    kb.save_knowledge_base()
    print(f"   知识库已保存")
    
    # 创建新的知识库实例并加载
    kb2 = KnowledgeBase("test_load_kb2")
    print(f"   新知识库加载后的文档数: {kb2.get_document_count()}")
    
    # 测试清空功能
    print("\n6. 测试清空功能:")
    initial_count = kb.get_document_count()
    kb.clear_knowledge_base()
    final_count = kb.get_document_count()
    print(f"   清空前文档数: {initial_count}, 清空后文档数: {final_count}")
    
    print("\n=== 知识库操作测试完成 ===")

if __name__ == "__main__":
    # 运行测试
    test_knowledge_base_operations()
    test_enhanced_ai_analysis()