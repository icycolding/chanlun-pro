#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试LangGraph工作流的新闻分析功能
"""

import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
web_path = os.path.join(project_root, 'web')
if src_path not in sys.path:
    sys.path.append(src_path)
if web_path not in sys.path:
    sys.path.append(web_path)

def test_langgraph_workflow():
    """
    测试LangGraph工作流
    """
    try:
        # 导入新闻分析API
        from chanlun_chart.cl_app.news_vector_api import _generate_ai_market_summary
        
        # 准备测试数据
        test_news = [
            {
                'title': '央行宣布降准0.5个百分点',
                'body': '中国人民银行今日宣布，为支持实体经济发展，决定于近期下调金融机构存款准备金率0.5个百分点，释放长期资金约1万亿元。',
                'published_at': '2024-01-15 10:00:00',
                'source': '央行官网'
            },
            {
                'title': '美联储暗示可能暂停加息',
                'body': '美联储主席鲍威尔在最新讲话中表示，考虑到通胀压力有所缓解，美联储可能会在下次会议上暂停加息。',
                'published_at': '2024-01-15 09:30:00',
                'source': '路透社'
            },
            {
                'title': '科技股集体上涨，AI概念持续火热',
                'body': '受人工智能技术突破消息影响，科技股今日集体上涨，其中AI相关概念股涨幅居前。',
                'published_at': '2024-01-15 11:00:00',
                'source': '财经网'
            }
        ]
        
        print("=== 开始测试LangGraph工作流 ===")
        print(f"测试新闻数量: {len(test_news)}")
        
        # 测试1: 不指定具体标的
        print("\n--- 测试1: 基础工作流（无具体标的） ---")
        result1 = _generate_ai_market_summary(test_news)
        print(f"结果长度: {len(result1)} 字符")
        print(f"结果预览: {result1[:200]}...")
        
        # 测试2: 指定A股标的
        print("\n--- 测试2: 指定A股标的工作流 ---")
        result2 = _generate_ai_market_summary(test_news, current_market='a', current_code='000001')
        print(f"结果长度: {len(result2)} 字符")
        print(f"结果预览: {result2[:200]}...")
        
        # 检查结果是否包含预期的节点输出
        print("\n--- 工作流验证 ---")
        success_indicators = [
            "宏观分析" in result2 or "宏观" in result2,
            "技术分析" in result2 or "技术指标" in result2,
            "缠论" in result2,
            "策略" in result2 or "建议" in result2
        ]
        
        print(f"包含宏观分析: {success_indicators[0]}")
        print(f"包含技术分析: {success_indicators[1]}")
        print(f"包含缠论分析: {success_indicators[2]}")
        print(f"包含策略建议: {success_indicators[3]}")
        
        if all(success_indicators):
            print("\n✅ LangGraph工作流测试成功！所有节点都正常工作。")
        else:
            print("\n⚠️  LangGraph工作流部分功能可能存在问题。")
            
        return True
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已安装所有依赖包，特别是LangGraph相关包。")
        return False
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("LangGraph工作流测试脚本")
    print("=" * 50)
    
    success = test_langgraph_workflow()
    
    if success:
        print("\n🎉 测试完成！")
    else:
        print("\n💥 测试失败，请检查错误信息。")
        sys.exit(1)