#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试经济数据分析节点功能
"""

import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'web'))
sys.path.append(os.path.join(project_root, 'src'))

def test_economic_analysis_node():
    """
    测试经济数据分析节点
    """
    try:
        from chanlun_chart.cl_app.news_vector_api import _generate_ai_market_summary, _format_economic_data_for_analysis
        
        # 准备测试用的经济数据
        test_economic_data = [
            {
                'ds_mnemonic': 'US_GDP',
                'indicator_name': '美国GDP',
                'latest_value': 26854.6,
                'previous_value': 26700.0,
                'previous_year_value': 25462.7,
                'yoy_change_pct': 5.47,
                'units': '十亿美元',
                'year': 2024
            },
            {
                'ds_mnemonic': 'US_CPI',
                'indicator_name': '美国消费者价格指数',
                'latest_value': 3.2,
                'previous_value': 3.4,
                'previous_year_value': 6.5,
                'yoy_change_pct': -50.77,
                'units': '%',
                'year': 2024
            },
            {
                'ds_mnemonic': 'CN_GDP',
                'indicator_name': '中国GDP',
                'latest_value': 17734.1,
                'previous_value': 17500.0,
                'previous_year_value': 17200.0,
                'yoy_change_pct': 3.10,
                'units': '万亿人民币',
                'year': 2024
            },
            {
                'ds_mnemonic': 'CN_CPI',
                'indicator_name': '中国消费者价格指数',
                'latest_value': 0.2,
                'previous_value': 0.0,
                'previous_year_value': 2.1,
                'yoy_change_pct': -90.48,
                'units': '%',
                'year': 2024
            }
        ]
        
        # 准备测试用的新闻数据
        test_news = [
            {
                'title': '美联储暗示可能暂停加息',
                'body': '美联储主席鲍威尔在最新讲话中表示，考虑到通胀压力有所缓解，美联储可能会在下次会议上暂停加息。',
                'published_at': '2024-01-15 09:30:00',
                'source': '路透社'
            },
            {
                'title': '中国央行维持利率不变',
                'body': '中国人民银行今日宣布维持基准利率不变，但表示将继续实施稳健的货币政策。',
                'published_at': '2024-01-15 10:00:00',
                'source': '央行官网'
            }
        ]
        
        print("=== 测试经济数据格式化功能 ===")
        formatted_data = _format_economic_data_for_analysis(test_economic_data)
        print("格式化后的经济数据:")
        print(formatted_data)
        print("\n" + "="*60 + "\n")
        
        print("=== 测试完整工作流（包含经济数据分析节点） ===")
        print(f"测试经济数据数量: {len(test_economic_data)}")
        print(f"测试新闻数量: {len(test_news)}")
        
        # 测试完整工作流
        result = _generate_ai_market_summary(
            economic_data_list=test_economic_data,
            news_list=test_news, 
            current_market='fx', 
            current_code='USDCNY'
        )
        
        print(f"\n生成报告长度: {len(result)} 字符")
        print("\n=== 生成的完整报告 ===")
        print(result)
        
        # 检查报告是否包含经济数据分析
        success_indicators = [
            "经济数据分析" in result or "经济分析" in result,
            "美林时钟" in result,
            "两国经济" in result or "经济对比" in result,
            "汇率" in result,
            "GDP" in result or "CPI" in result
        ]
        
        print("\n=== 功能验证 ===")
        print(f"包含经济数据分析: {success_indicators[0]}")
        print(f"包含美林时钟分析: {success_indicators[1]}")
        print(f"包含两国经济对比: {success_indicators[2]}")
        print(f"包含汇率分析: {success_indicators[3]}")
        print(f"包含具体经济指标: {success_indicators[4]}")
        
        if all(success_indicators):
            print("\n✅ 经济数据分析节点测试成功！所有功能都正常工作。")
        else:
            print("\n⚠️  经济数据分析节点部分功能可能存在问题。")
            
        return True
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已安装所有依赖包。")
        return False
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("经济数据分析节点测试脚本")
    print("=" * 50)
    
    success = test_economic_analysis_node()
    
    if success:
        print("\n🎉 测试完成！")
    else:
        print("\n💥 测试失败，请检查错误信息。")
        sys.exit(1)