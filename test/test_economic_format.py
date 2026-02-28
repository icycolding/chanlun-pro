#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试经济数据格式化功能
"""

import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'web'))
sys.path.append(os.path.join(project_root, 'src'))

def test_economic_data_formatting():
    """
    测试经济数据格式化功能
    """
    try:
        from chanlun_chart.cl_app.news_vector_api import _format_economic_data_for_analysis
        
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
            },
            {
                'ds_mnemonic': 'US_UNEMPLOYMENT',
                'indicator_name': '美国失业率',
                'latest_value': 3.7,
                'previous_value': 3.8,
                'previous_year_value': 3.5,
                'yoy_change_pct': 5.71,
                'units': '%',
                'year': 2024
            },
            {
                'ds_mnemonic': 'CN_PMI',
                'indicator_name': '中国制造业PMI',
                'latest_value': 50.2,
                'previous_value': 49.8,
                'previous_year_value': 50.1,
                'yoy_change_pct': 0.20,
                'units': '指数',
                'year': 2024
            }
        ]
        
        print("=== 测试经济数据格式化功能 ===")
        print(f"输入数据数量: {len(test_economic_data)}")
        print("\n原始数据示例:")
        for i, data in enumerate(test_economic_data[:2]):
            print(f"{i+1}. {data['ds_mnemonic']}: {data['indicator_name']}")
        
        # 测试格式化功能
        formatted_data = _format_economic_data_for_analysis(test_economic_data)
        
        print("\n=== 格式化后的经济数据 ===")
        print(formatted_data)
        
        # 验证格式化结果
        success_checks = [
            "US经济数据" in formatted_data,
            "CN经济数据" in formatted_data,
            "GDP" in formatted_data,
            "CPI" in formatted_data,
            "最新值" in formatted_data,
            "前值" in formatted_data,
            "去年同期" in formatted_data,
            "同比变化" in formatted_data
        ]
        
        print("\n=== 格式化验证 ===")
        print(f"包含美国数据: {success_checks[0]}")
        print(f"包含中国数据: {success_checks[1]}")
        print(f"包含GDP指标: {success_checks[2]}")
        print(f"包含CPI指标: {success_checks[3]}")
        print(f"包含最新值: {success_checks[4]}")
        print(f"包含前值: {success_checks[5]}")
        print(f"包含去年同期: {success_checks[6]}")
        print(f"包含同比变化: {success_checks[7]}")
        
        if all(success_checks):
            print("\n✅ 经济数据格式化功能测试成功！")
        else:
            print("\n⚠️  经济数据格式化功能存在问题。")
        
        # 测试空数据情况
        print("\n=== 测试空数据情况 ===")
        empty_result = _format_economic_data_for_analysis([])
        print(f"空数据结果: {empty_result}")
        
        if empty_result == "暂无经济数据":
            print("✅ 空数据处理正确")
        else:
            print("⚠️  空数据处理可能有问题")
            
        return True
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("经济数据格式化功能测试")
    print("=" * 50)
    
    success = test_economic_data_formatting()
    
    if success:
        print("\n🎉 测试完成！")
    else:
        print("\n💥 测试失败，请检查错误信息。")
        sys.exit(1)