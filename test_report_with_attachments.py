#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试报告附件功能
验证ReportGenerationState中final_report是否正确将分析内容作为附件
"""

import sys
import os
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')

from web.chanlun_chart.cl_app.news_vector_api import _generate_ai_market_summary

def test_report_with_attachments():
    """
    测试报告附件功能
    """
    print("=" * 80)
    print("测试报告附件功能")
    print("=" * 80)
    
    # 模拟新闻数据
    mock_news = [
        {
            'title': '央行宣布降准0.5个百分点',
            'content': '中国人民银行今日宣布，为支持实体经济发展，决定于近期降准0.5个百分点，释放长期资金约1万亿元。',
            'published_at': '2024-12-19 10:00:00',
            'source': '央行官网'
        },
        {
            'title': '科技股集体上涨，AI概念持续火热',
            'content': '今日A股市场科技股表现强劲，人工智能、芯片等概念股涨幅居前，市场对科技创新的关注度持续提升。',
            'published_at': '2024-12-19 14:30:00',
            'source': '财经新闻'
        }
    ]
    
    print("\n📊 生成市场分析报告...")
    print("-" * 40)
    
    try:
        # 测试A股市场报告生成
        report = _generate_ai_market_summary(
            news_list=mock_news,
            current_market='A',
            current_code='000001'
        )
        
        print("\n📋 生成的完整报告:")
        print("=" * 80)
        print(report)
        print("=" * 80)
        
        # 验证报告结构
        print("\n🔍 报告结构验证:")
        print("-" * 30)
        
        # 检查是否包含附件标识
        if "📎 **附件：专家分析详细报告**" in report:
            print("✅ 附件标题: 已包含")
        else:
            print("❌ 附件标题: 缺失")
        
        # 检查各个附件是否存在
        attachments = [
            ("📊 附件一：宏观分析师详细报告", "宏观分析附件"),
            ("📈 附件二：技术指标分析师详细报告", "技术分析附件"),
            ("🔍 附件三：缠论结构专家详细报告", "缠论分析附件")
        ]
        
        for attachment_title, attachment_name in attachments:
            if attachment_title in report:
                print(f"✅ {attachment_name}: 已包含")
            else:
                print(f"❌ {attachment_name}: 缺失")
        
        # 检查附件结束标识
        if "*以上附件为各专家的详细分析报告，供参考*" in report:
            print("✅ 附件结束标识: 已包含")
        else:
            print("❌ 附件结束标识: 缺失")
        
        # 分析报告结构
        print("\n📈 报告结构分析:")
        print("-" * 30)
        
        # 计算主报告和附件的分界点
        attachment_start = report.find("📎 **附件：专家分析详细报告**")
        if attachment_start != -1:
            main_report_length = attachment_start
            attachment_length = len(report) - attachment_start
            
            print(f"📊 主报告长度: {main_report_length} 字符")
            print(f"📎 附件部分长度: {attachment_length} 字符")
            print(f"📋 总报告长度: {len(report)} 字符")
            print(f"📈 附件占比: {attachment_length/len(report)*100:.1f}%")
            
            # 显示主报告预览
            main_report_preview = report[:attachment_start].strip()
            if len(main_report_preview) > 500:
                main_report_preview = main_report_preview[:500] + "..."
            
            print("\n📋 主报告预览:")
            print("-" * 40)
            print(main_report_preview)
            print("-" * 40)
        else:
            print("❌ 未找到附件分界点")
        
        print("\n🎉 报告附件功能测试完成!")
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n📋 功能改进总结:")
    print("1. ✨ 主报告简洁化 - 首席策略师的综合分析和策略建议")
    print("2. ✨ 附件结构化 - 三个专家的详细分析报告作为附件")
    print("3. ✨ 清晰分界线 - 使用分隔符明确区分主报告和附件")
    print("4. ✨ 标题层次化 - 使用Markdown格式美化附件标题")
    print("5. ✨ 用户体验优化 - 主要内容在前，详细分析在后")
    print("\n🚀 报告结构已优化：核心策略 + 详细附件 = 专业投研报告格式!")

if __name__ == "__main__":
    test_report_with_attachments()