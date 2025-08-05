#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版AI分析使用示例
演示如何在实际场景中使用知识库增强的缠论AI分析功能
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.abspath('.')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from chanlun.tools.ai_analyse_enhanced import AIAnalyseEnhanced
from chanlun.tools.knowledge_base import KnowledgeBase

def add_custom_knowledge_to_ai(ai: AIAnalyseEnhanced):
    """
    向AI分析器添加自定义缠论知识
    """
    print("正在添加自定义缠论知识...")
    
    # 添加更多实战相关的知识
    custom_knowledge = [
        {
            "title": "一买点的确认条件",
            "content": "一买点的确认需要满足以下条件：1）价格跌破前一个中枢的下沿；2）出现背驰或其他技术指标确认；3）成交量配合（通常是放量下跌后缩量）。实战中，一买点往往是风险最小的买入时机，但需要严格的止损纪律。",
            "category": "买卖点实战"
        },
        {
            "title": "二买点的操作策略",
            "content": "二买点是指价格重新回到中枢内部后的买入机会。操作要点：1）确认价格已经回到中枢内；2）观察是否有支撑；3）结合其他技术指标确认。二买点相对安全，适合稳健投资者。",
            "category": "买卖点实战"
        },
        {
            "title": "三买点的风险控制",
            "content": "三买点是价格突破中枢上沿后的买入机会，风险相对较高。操作要点：1）确认有效突破；2）成交量配合；3）设置合理止损位；4）注意假突破的风险。三买点适合激进投资者。",
            "category": "买卖点实战"
        },
        {
            "title": "MACD背驰的实战应用",
            "content": "MACD背驰是判断趋势转折的重要工具。实战要点：1）观察MACD柱状图的变化；2）比较相邻两段走势的MACD面积；3）结合价格走势确认；4）注意背驰后的确认信号。MACD背驰准确率较高，但需要结合其他指标使用。",
            "category": "技术指标实战"
        },
        {
            "title": "中枢震荡的交易策略",
            "content": "在中枢震荡阶段，可以采用高抛低吸策略：1）在中枢上沿附近减仓或做空；2）在中枢下沿附近加仓或做多；3）严格控制仓位；4）等待明确的突破信号。中枢震荡期间要保持耐心，避免频繁交易。",
            "category": "中枢实战"
        },
        {
            "title": "趋势背驰的确认方法",
            "content": "趋势背驰的确认需要：1）至少两段同级别的走势进行比较；2）后一段走势创新高（低）但力度减弱；3）使用MACD、RSI等指标辅助确认；4）观察成交量的变化。趋势背驰是重要的转折信号，准确率较高。",
            "category": "背驰实战"
        },
        {
            "title": "线段划分的实战技巧",
            "content": "线段划分的实战技巧：1）严格按照缠论标准划分；2）注意线段的完整性；3）观察线段内部结构；4）结合成交量分析。正确的线段划分是后续分析的基础，需要多加练习。",
            "category": "线段实战"
        },
        {
            "title": "多周期共振分析",
            "content": "多周期共振分析可以提高成功率：1）同时观察日线、周线、月线；2）寻找多个周期的买卖点共振；3）以大周期为主，小周期为辅；4）注意不同周期的背驰情况。多周期共振的信号更加可靠。",
            "category": "综合分析"
        },
        {
            "title": "资金管理与仓位控制",
            "content": "缠论交易中的资金管理：1）根据买卖点级别确定仓位大小；2）一买点可以重仓，二买点中等仓位，三买点轻仓；3）严格执行止损；4）分批建仓和减仓。良好的资金管理是长期盈利的关键。",
            "category": "风险管理"
        }
    ]
    
    success_count = 0
    for knowledge in custom_knowledge:
        success = ai.add_knowledge(
            knowledge["title"], 
            knowledge["content"], 
            knowledge["category"]
        )
        if success:
            success_count += 1
    
    print(f"成功添加 {success_count}/{len(custom_knowledge)} 个知识点")
    return success_count > 0

def demonstrate_enhanced_analysis():
    """
    演示增强版AI分析的完整流程
    """
    print("=== 增强版AI分析演示 ===")
    
    # 1. 创建增强版AI分析器
    print("\n1. 初始化增强版AI分析器...")
    ai = AIAnalyseEnhanced("a", kb_name="demo_chanlun_kb")
    
    # 2. 查看初始知识库状态
    print("\n2. 初始知识库状态:")
    stats = ai.get_knowledge_stats()
    print(f"   总文档数: {stats['total_documents']}")
    print(f"   分类: {stats['categories']}")
    
    # 3. 添加自定义知识
    print("\n3. 添加自定义实战知识:")
    add_custom_knowledge_to_ai(ai)
    
    # 4. 查看更新后的知识库状态
    print("\n4. 更新后的知识库状态:")
    stats = ai.get_knowledge_stats()
    print(f"   总文档数: {stats['total_documents']}")
    print(f"   分类: {stats['categories']}")
    
    # 5. 测试不同类型的知识搜索
    print("\n5. 测试知识搜索功能:")
    
    search_tests = [
        ("一买点操作", "买卖点实战"),
        ("MACD背驰", "技术指标实战"),
        ("中枢震荡", "中枢实战"),
        ("资金管理", "风险管理")
    ]
    
    for query, category in search_tests:
        print(f"\n   搜索 '{query}' (限制分类: {category}):")
        results = ai.search_knowledge(query, top_k=2, category=category)
        for i, result in enumerate(results, 1):
            print(f"     {i}. {result['title']} (相似度: {result['similarity']:.3f})")
            print(f"        内容摘要: {result['content'][:60]}...")
    
    # 6. 演示知识增强提示词生成
    print("\n6. 演示知识增强提示词生成:")
    
    # 模拟不同的市场情况
    market_scenarios = [
        {
            "name": "下跌趋势中的买点机会",
            "queries": ["一买点", "背驰", "止损"]
        },
        {
            "name": "中枢震荡阶段",
            "queries": ["中枢震荡", "高抛低吸", "仓位控制"]
        },
        {
            "name": "突破上涨阶段",
            "queries": ["三买点", "突破确认", "风险控制"]
        }
    ]
    
    for scenario in market_scenarios:
        print(f"\n   场景: {scenario['name']}")
        print(f"   搜索关键词: {scenario['queries']}")
        
        # 搜索相关知识
        all_knowledge = []
        for query in scenario['queries']:
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
        unique_knowledge = unique_knowledge[:2]  # 限制为2个文档
        
        print(f"   找到相关知识: {len(unique_knowledge)} 个")
        for doc in unique_knowledge:
            print(f"     - {doc['title']} (相似度: {doc['similarity']:.3f})")
    
    # 7. 展示实际使用方法
    print("\n7. 实际使用方法示例:")
    print("""
   # 基础用法（不使用知识库）
   result = ai.analyse_with_knowledge('000001', '30m', use_knowledge=False)
   
   # 启用知识库增强
   result = ai.analyse_with_knowledge('000001', '30m', use_knowledge=True)
   
   # 限制知识库搜索分类
   result = ai.analyse_with_knowledge(
       '000001', '30m', 
       use_knowledge=True,
       knowledge_categories=['买卖点实战', '技术指标实战'],
       max_knowledge_docs=3
   )
   
   # 检查结果
   if result['ok']:
       print("AI分析结果:", result['msg'])
   else:
       print("分析失败:", result['msg'])
   """)
    
    print("\n=== 演示完成 ===")
    print("\n优势说明:")
    print("1. 知识库增强: 结合缠论理论知识，提供更专业的分析")
    print("2. 分类管理: 按照买卖点、技术指标、风险管理等分类组织知识")
    print("3. 智能搜索: 根据当前市场情况自动搜索相关知识")
    print("4. 可扩展性: 可以随时添加新的知识和经验")
    print("5. 个性化: 可以根据个人交易风格定制知识库")

def test_knowledge_search_performance():
    """
    测试知识搜索的性能和准确性
    """
    print("\n=== 知识搜索性能测试 ===")
    
    ai = AIAnalyseEnhanced("a", kb_name="performance_test_kb")
    
    # 添加测试知识
    add_custom_knowledge_to_ai(ai)
    
    # 测试不同的搜索查询
    test_queries = [
        "如何判断一买点",
        "MACD背驰信号",
        "中枢突破策略",
        "风险控制方法",
        "多周期分析",
        "仓位管理技巧"
    ]
    
    print(f"\n测试 {len(test_queries)} 个搜索查询:")
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{i}. 查询: '{query}'")
        results = ai.search_knowledge(query, top_k=3)
        
        if results:
            print(f"   找到 {len(results)} 个相关结果:")
            for j, result in enumerate(results, 1):
                print(f"     {j}. {result['title']} (相似度: {result['similarity']:.3f})")
        else:
            print("   未找到相关结果")
    
    print("\n=== 性能测试完成 ===")

if __name__ == "__main__":
    try:
        # 运行主要演示
        demonstrate_enhanced_analysis()
        
        # 运行性能测试
        test_knowledge_search_performance()
        
        print("\n" + "="*50)
        print("所有测试完成！")
        print("你现在可以开始使用增强版AI分析功能了。")
        print("="*50)
        
    except Exception as e:
        print(f"\n演示过程中出现错误: {e}")
        print("请检查环境配置和依赖包安装情况。")