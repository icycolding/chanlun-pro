#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangGraph工作流演示脚本
展示新的智能体工作流如何生成高质量的市场分析报告
"""

import sys
import os
import time

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
web_path = os.path.join(project_root, 'web')
if src_path not in sys.path:
    sys.path.append(src_path)
if web_path not in sys.path:
    sys.path.append(web_path)

def demo_workflow():
    """
    演示LangGraph工作流的完整执行过程
    """
    print("🚀 LangGraph智能体工作流演示")
    print("=" * 60)
    print("\n📋 工作流架构:")
    print("   宏观分析师 → 技术分析师 → 缠论专家 → 首席策略师")
    print("\n💡 核心优势:")
    print("   • 专注性: 每个节点专注单一任务")
    print("   • 逻辑性: 层层递进的分析链条")
    print("   • 可控性: 每步输出可见可调试")
    print("   • 扩展性: 易于添加新的分析节点")
    
    # 准备演示数据
    demo_news = [
        {
            'title': '美联储会议纪要显示鸽派倾向',
            'body': '最新公布的美联储会议纪要显示，多数委员认为当前利率水平已足够限制性，未来加息步伐可能放缓。市场对此反应积极，美股期货上涨。',
            'published_at': '2024-01-15 14:30:00',
            'source': 'Bloomberg'
        },
        {
            'title': '中国制造业PMI超预期回升',
            'body': '国家统计局公布的最新数据显示，中国制造业PMI指数升至51.2，超出市场预期的50.8，显示制造业活动继续扩张，经济复苏势头良好。',
            'published_at': '2024-01-15 09:00:00',
            'source': '国家统计局'
        },
        {
            'title': '科技巨头财报季开启，AI投资成焦点',
            'body': '随着财报季的到来，投资者密切关注科技巨头在人工智能领域的投资和收益情况。分析师预计AI相关收入将成为推动股价的关键因素。',
            'published_at': '2024-01-15 16:00:00',
            'source': 'CNBC'
        }
    ]
    
    print("\n📰 演示新闻数据:")
    for i, news in enumerate(demo_news, 1):
        print(f"   {i}. {news['title']}")
    
    print("\n⏳ 开始执行工作流...")
    print("-" * 60)
    
    try:
        from chanlun_chart.cl_app.news_vector_api import _generate_ai_market_summary
        
        # 记录开始时间
        start_time = time.time()
        
        # 执行工作流
        result = _generate_ai_market_summary(
            demo_news, 
            current_market='a', 
            current_code='000300'  # 沪深300指数
        )
        
        # 记录结束时间
        end_time = time.time()
        execution_time = end_time - start_time
        
        print("\n✅ 工作流执行完成！")
        print(f"⏱️  执行时间: {execution_time:.2f} 秒")
        print(f"📄 报告长度: {len(result)} 字符")
        
        print("\n" + "=" * 60)
        print("📊 生成的市场分析报告:")
        print("=" * 60)
        print(result)
        print("=" * 60)
        
        # 分析报告质量
        print("\n🔍 报告质量分析:")
        quality_checks = {
            "包含宏观分析": any(keyword in result for keyword in ["宏观", "央行", "货币政策", "经济"]),
            "包含技术分析": any(keyword in result for keyword in ["技术", "MACD", "指标", "波动"]),
            "包含缠论分析": "缠论" in result or "买卖点" in result,
            "包含具体策略": any(keyword in result for keyword in ["策略", "建议", "入场", "止损", "目标"]),
            "逻辑连贯性": "综合" in result or "整合" in result or "因此" in result,
            "风险提示": "风险" in result or "注意" in result or "警惕" in result
        }
        
        for check, passed in quality_checks.items():
            status = "✅" if passed else "❌"
            print(f"   {status} {check}: {'通过' if passed else '未通过'}")
        
        passed_count = sum(quality_checks.values())
        total_count = len(quality_checks)
        quality_score = (passed_count / total_count) * 100
        
        print(f"\n📈 整体质量评分: {quality_score:.1f}% ({passed_count}/{total_count})")
        
        if quality_score >= 80:
            print("🎉 报告质量优秀！")
        elif quality_score >= 60:
            print("👍 报告质量良好！")
        else:
            print("⚠️  报告质量需要改进。")
            
        return True
        
    except Exception as e:
        print(f"❌ 演示执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = demo_workflow()
    
    if success:
        print("\n🎊 演示完成！LangGraph工作流已成功集成到系统中。")
        print("\n💡 下一步建议:")
        print("   • 根据实际使用情况调整各节点的提示词")
        print("   • 添加更多专业分析节点（如期权分析、情绪分析等）")
        print("   • 实施更细粒度的错误处理和重试机制")
        print("   • 添加工作流执行的监控和日志记录")
    else:
        print("\n💥 演示失败，请检查系统配置。")
        sys.exit(1)