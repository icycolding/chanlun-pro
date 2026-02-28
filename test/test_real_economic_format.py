#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试真实经济数据格式化功能
使用用户提供的实际数据格式进行测试
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'web', 'chanlun_chart'))

from cl_app.news_vector_api import _format_economic_data_for_analysis, _get_indicator_type_from_mnemonic
import datetime

def test_real_economic_data_format():
    """测试真实经济数据格式化"""
    print("=== 测试真实经济数据格式化功能 ===")
    
    # 使用用户提供的真实数据格式
    real_economic_data = [
        {
            'latest_value_date': '2025-08-08 23:20:42.591940',
            'indicator_name': 'china',
            'ds_mnemonic': 'CHBPEXGS',
            'previous_value': 35078.428816,
            'previous_year_value': 35078.428816,
            'units': 'U.S. Dollar Hundreds of Millions',
            'id': 60,
            'latest_value': 37929.507173,
            'yoy_change_pct': 8.13,
            'previous_value_date': None,
            'year': '23',
            'source': 'excel_upload'
        },
        {
            'latest_value_date': '2025-08-08 23:20:42.591080',
            'indicator_name': 'china',
            'ds_mnemonic': 'CHCURBAL',
            'previous_value': 2633.82,
            'previous_year_value': 2633.824,
            'units': 'U.S. Dollar Hundreds of Millions',
            'id': 59,
            'latest_value': 4239.19,
            'yoy_change_pct': 60.95,
            'previous_value_date': None,
            'year': '23',
            'source': 'excel_upload'
        },
        {
            'latest_value_date': '2025-08-08 23:20:42.590400',
            'indicator_name': 'china',
            'ds_mnemonic': 'CHEXNGS.',
            'previous_value': 27346.7,
            'previous_year_value': 27346.7,
            'units': 'Chinese Yuan Hundreds of Millions',
            'id': 58,
            'latest_value': 38288.9,
            'yoy_change_pct': 40.01,
            'previous_value_date': None,
            'year': '23',
            'source': 'excel_upload'
        },
        {
            'latest_value_date': '2025-08-08 23:20:42.589138',
            'indicator_name': 'china',
            'ds_mnemonic': 'CHGOVBALA',
            'previous_value': -476.8,
            'previous_year_value': -504.7,
            'units': 'Chinese Yuan Billions',
            'id': 56,
            'latest_value': -1324.0,
            'yoy_change_pct': 162.33,
            'previous_value_date': None,
            'year': '2025',
            'source': 'excel_upload'
        },
        {
            'latest_value_date': '2025-08-08 23:20:42.587930',
            'indicator_name': 'china',
            'ds_mnemonic': 'CHIFATOTA',
            'previous_value': 191947.0,
            'previous_year_value': 245391.0,
            'units': 'Chinese Yuan Hundreds of Millions',
            'id': 54,
            'latest_value': 248654.0,
            'yoy_change_pct': 1.33,
            'previous_value_date': None,
            'year': '2025',
            'source': 'excel_upload'
        }
    ]
    
    print(f"输入数据数量: {len(real_economic_data)}")
    print("\n原始数据示例:")
    for i, data in enumerate(real_economic_data[:3], 1):
        print(f"{i}. {data['ds_mnemonic']}: {data['indicator_name']}")
    
    # 测试格式化功能
    formatted_result = _format_economic_data_for_analysis(real_economic_data)
    
    print("\n=== 格式化后的经济数据 ===")
    print(formatted_result)
    
    # 验证格式化结果
    print("\n=== 格式化验证 ===")
    print(f"包含中国数据: {'中国' in formatted_result}")
    print(f"包含CHBPEXGS: {'CHBPEXGS' in formatted_result}")
    print(f"包含CHCURBAL: {'CHCURBAL' in formatted_result}")
    print(f"包含最新值: {'最新值' in formatted_result}")
    print(f"包含前值: {'前值' in formatted_result}")
    print(f"包含去年同期: {'去年同期' in formatted_result}")
    print(f"包含同比变化: {'同比变化' in formatted_result}")
    print(f"包含单位信息: {'U.S. Dollar' in formatted_result}")
    
    # 测试指标类型推断
    print("\n=== 测试指标类型推断 ===")
    test_mnemonics = ['CHBPEXGS', 'CHCURBAL', 'CHEXNGS.', 'CHGOVBALA', 'CHIFATOTA']
    for mnemonic in test_mnemonics:
        indicator_type = _get_indicator_type_from_mnemonic(mnemonic)
        print(f"{mnemonic} -> {indicator_type}")
    
    print("\n✅ 真实经济数据格式化功能测试成功！")
    
    return formatted_result

def test_mixed_country_data():
    """测试混合国家数据"""
    print("\n=== 测试混合国家数据 ===")
    
    mixed_data = [
        {
            'ds_mnemonic': 'CHGDP',
            'indicator_name': 'china',
            'latest_value': 17734.1,
            'previous_value': 17500.0,
            'previous_year_value': 17200.0,
            'yoy_change_pct': 3.1,
            'units': '万亿人民币',
            'year': '2024'
        },
        {
            'ds_mnemonic': 'USGDP',
            'indicator_name': 'united states',
            'latest_value': 26854.6,
            'previous_value': 26700.0,
            'previous_year_value': 25462.7,
            'yoy_change_pct': 5.47,
            'units': '十亿美元',
            'year': '2024'
        },
        {
            'ds_mnemonic': 'UNKNOWN_INDICATOR',
            'indicator_name': 'unknown country',
            'latest_value': 100.0,
            'previous_value': 95.0,
            'previous_year_value': 90.0,
            'yoy_change_pct': 11.11,
            'units': '指数',
            'year': '2024'
        }
    ]
    
    result = _format_economic_data_for_analysis(mixed_data)
    print(result)
    
    # 验证
    print("\n验证结果:")
    print(f"包含中国数据: {'中国' in result}")
    print(f"包含美国数据: {'美国' in result}")
    print(f"包含未知国家数据: {'未知国家' in result}")
    
    print("✅ 混合国家数据测试成功！")

if __name__ == "__main__":
    try:
        # 测试真实数据格式化
        test_real_economic_data_format()
        
        # 测试混合国家数据
        test_mixed_country_data()
        
        print("\n🎉 所有测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()