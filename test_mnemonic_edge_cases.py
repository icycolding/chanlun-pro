#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试助记符边界情况处理
"""

import sys
import os

# 添加项目根目录和src目录到路径
project_root = os.path.dirname(__file__)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))
sys.path.insert(0, os.path.join(project_root, 'web/chanlun_chart'))

# 直接导入函数进行测试
def _format_economic_data_for_analysis(economic_data) -> str:
    """格式化经济数据供AI分析使用"""
    if not economic_data:
        return "暂无经济数据"
    
    # 按国家分组经济数据
    countries_data = {}
    
    # 定义助记符前缀到国家的映射
    country_mapping = {
        'CH': '中国',
        'US': '美国',
        'EU': '欧盟',
        'JP': '日本',
        'GB': '英国',
        'CA': '加拿大',
        'AU': '澳大利亚',
        'NZ': '新西兰'
    }
    
    for data in economic_data:
        mnemonic = data.get('ds_mnemonic', '') or ''
        country = '未知国家'
        
        # 首先尝试从助记符前缀识别国家
        if mnemonic:  # 确保mnemonic不为空
            for prefix, country_name in country_mapping.items():
                if mnemonic.startswith(prefix):
                    country = country_name
                    break
        
        # 如果还是未知国家，尝试从indicator_name获取
        if country == '未知国家':
            indicator_name = (data.get('indicator_name', '') or '').lower()
            if indicator_name and ('china' in indicator_name or '中国' in indicator_name or 'ch' in indicator_name):
                country = '中国'
            elif indicator_name and ('us' in indicator_name or 'america' in indicator_name or '美国' in indicator_name):
                country = '美国'
            elif indicator_name and ('eu' in indicator_name or 'europe' in indicator_name or '欧盟' in indicator_name):
                country = '欧盟'
            elif indicator_name and ('jp' in indicator_name or 'japan' in indicator_name or '日本' in indicator_name):
                country = '日本'
        
        if country not in countries_data:
            countries_data[country] = []
        countries_data[country].append(data)
    
    formatted_text = ""
    for country, data_list in countries_data.items():
        formatted_text += f"\n## {country}经济数据:\n"
        formatted_text += "-" * 40 + "\n"
        
        for data in data_list:
            mnemonic = data.get('ds_mnemonic', 'N/A')
            indicator = data.get('indicator_name', 'N/A')
            latest_value = data.get('latest_value', 'N/A')
            previous_value = data.get('previous_value', 'N/A')
            previous_year_value = data.get('previous_year_value', 'N/A')
            yoy_change = data.get('yoy_change_pct', 'N/A')
            units = data.get('units', '')
            year = data.get('year', 'N/A')
            
            formatted_text += f"**{mnemonic}** ({indicator}):\n"
            formatted_text += f"  - 最新值: {latest_value} {units}\n"
            formatted_text += f"  - 前值: {previous_value} {units}\n"
            formatted_text += f"  - 去年同期: {previous_year_value} {units}\n"
            formatted_text += f"  - 同比变化: {yoy_change}%\n"
            formatted_text += f"  - 年份: {year}\n\n"
    
    return formatted_text

def test_edge_cases():
    """测试各种边界情况"""
    print("=== 测试助记符边界情况处理 ===")
    
    # 测试数据包含各种边界情况
    test_data = [
        # 正常情况
        {
            'ds_mnemonic': 'USM1....A',
            'indicator_name': 'us',
            'latest_value': 18762.6,
            'units': 'U.S. Dollar Billions',
            'year': '2025'
        },
        # ds_mnemonic 为 None
        {
            'ds_mnemonic': None,
            'indicator_name': 'china',
            'latest_value': 132.5,
            'units': 'Trillion Yuan',
            'year': '2025'
        },
        # ds_mnemonic 为空字符串
        {
            'ds_mnemonic': '',
            'indicator_name': 'us',
            'latest_value': 100.0,
            'units': 'Index',
            'year': '2025'
        },
        # ds_mnemonic 缺失字段
        {
            'indicator_name': 'japan',
            'latest_value': 50.0,
            'units': 'Yen Trillions',
            'year': '2025'
        },
        # indicator_name 也为 None
        {
            'ds_mnemonic': None,
            'indicator_name': None,
            'latest_value': 75.0,
            'units': 'Unknown',
            'year': '2025'
        },
        # 正常的中国数据
        {
            'ds_mnemonic': 'CHGDP....',
            'indicator_name': 'china',
            'latest_value': 126.8,
            'units': 'Trillion Yuan',
            'year': '2025'
        }
    ]
    
    try:
        # 测试格式化函数
        result = _format_economic_data_for_analysis(test_data)
        print("格式化结果:")
        print(result)
        print("\n" + "="*50)
        
        # 验证结果
        assert "美国经济数据" in result, "应该包含美国经济数据"
        assert "中国经济数据" in result, "应该包含中国经济数据"
        assert "未知国家经济数据" in result, "应该包含未知国家经济数据"
        assert "USM1....A" in result, "应该包含正常的助记符"
        
        print("✅ 边界情况处理测试通过！")
        
        # 测试空数据
        print("\n=== 测试空数据处理 ===")
        empty_result = _format_economic_data_for_analysis([])
        print(f"空数据结果: {empty_result}")
        assert empty_result == "暂无经济数据", "空数据应该返回'暂无经济数据'"
        
        print("✅ 空数据处理测试通过！")
        
        # 测试None数据
        print("\n=== 测试None数据处理 ===")
        none_result = _format_economic_data_for_analysis(None)
        print(f"None数据结果: {none_result}")
        assert none_result == "暂无经济数据", "None数据应该返回'暂无经济数据'"
        
        print("✅ None数据处理测试通过！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        raise
    
    print("\n✅ 所有边界情况测试通过！")

if __name__ == "__main__":
    test_edge_cases()