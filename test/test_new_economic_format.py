#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新经济数据格式的处理
"""

import sys
import os

# 添加项目根目录和src目录到路径
project_root = os.path.dirname(__file__)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))
sys.path.insert(0, os.path.join(project_root, 'web/chanlun_chart'))

# 直接导入函数进行测试
def _get_indicator_type_from_mnemonic(mnemonic: str) -> str:
    """根据助记符推断指标类型"""
    # 中国指标映射
    china_indicators = {
        'CHGDP': 'GDP',
        'CHCPI': 'CPI消费者价格指数',
        'CHPPI': 'PPI生产者价格指数',
        'CHPMIM': 'PMI制造业',
        'CHPMIN': 'PMI非制造业',
        'CHBPEXGS': '贸易差额',
        'CHEXPORT': '出口总额',
        'CHIMPORT': '进口总额',
        'CHFXRES': '外汇储备',
        'CHIR': '利率',
        'CHUER': '失业率'
    }
    
    # 美国指标映射
    us_indicators = {
        'USGDP': 'GDP',
        'USCPI': 'CPI消费者价格指数',
        'USPPI': 'PPI生产者价格指数',
        'USPMIM': 'PMI制造业',
        'USPMIN': 'PMI服务业',
        'USTB': '贸易差额',
        'USEXPORT': '出口总额',
        'USIMPORT': '进口总额',
        'USFFR': '联邦基金利率',
        'USUER': '失业率',
        'USM1': 'M1货币供应量',
        'USM2': 'M2货币供应量'
    }
    
    # 移除助记符中的点号和其他特殊字符，提取核心部分
    clean_mnemonic = mnemonic.replace('.', '').replace('_', '')
    
    # 尝试匹配中国指标
    for key, value in china_indicators.items():
        if clean_mnemonic.startswith(key):
            return value
    
    # 尝试匹配美国指标
    for key, value in us_indicators.items():
        if clean_mnemonic.startswith(key):
            return value
    
    # 如果没有匹配到，返回原助记符
    return mnemonic

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
        mnemonic = data.get('ds_mnemonic', '')
        country = '未知国家'
        
        # 首先尝试从助记符前缀识别国家
        for prefix, country_name in country_mapping.items():
            if mnemonic.startswith(prefix):
                country = country_name
                break
        
        # 如果还是未知国家，尝试从indicator_name获取
        if country == '未知国家':
            indicator_name = data.get('indicator_name', '').lower()
            if 'china' in indicator_name or '中国' in indicator_name or 'ch' in indicator_name:
                country = '中国'
            elif 'us' in indicator_name or 'america' in indicator_name or '美国' in indicator_name:
                country = '美国'
            elif 'eu' in indicator_name or 'europe' in indicator_name or '欧盟' in indicator_name:
                country = '欧盟'
            elif 'jp' in indicator_name or 'japan' in indicator_name or '日本' in indicator_name:
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
            
            # 尝试从助记符推断指标类型
            indicator_type = _get_indicator_type_from_mnemonic(mnemonic)
            display_name = f"{indicator_type}" if indicator_type != mnemonic else mnemonic
            
            formatted_text += f"**{mnemonic}** ({display_name}):\n"
            formatted_text += f"  - 最新值: {latest_value} {units}\n"
            formatted_text += f"  - 前值: {previous_value} {units}\n"
            formatted_text += f"  - 去年同期: {previous_year_value} {units}\n"
            formatted_text += f"  - 同比变化: {yoy_change}%\n"
            formatted_text += f"  - 年份: {year}\n\n"
    
    return formatted_text

def test_new_economic_format():
    """测试新的经济数据格式"""
    print("=== 测试新经济数据格式处理 ===")
    
    # 用户提供的新数据格式
    test_data = [
        {
            '_sa_instance_state': None,  # 简化测试
            'latest_value_date': '2025-08-08 23:20:56.754968',
            'indicator_name': 'us',
            'ds_mnemonic': 'USM1....A',
            'previous_value': 18611.6,
            'previous_year_value': 17998.9,
            'units': 'U.S. Dollar Billions',
            'id': 119,
            'latest_value': 18762.6,
            'yoy_change_pct': 4.24,
            'previous_value_date': None,
            'year': '2025',
            'source': 'excel_upload'
        },
        # 添加一个中国数据进行对比测试
        {
            'indicator_name': 'china',
            'ds_mnemonic': 'CHGDP....',
            'previous_value': 126.8,
            'previous_year_value': 121.0,
            'units': 'Trillion Yuan',
            'latest_value': 132.5,
            'yoy_change_pct': 9.5,
            'year': '2025',
            'source': 'excel_upload'
        }
    ]
    
    # 测试格式化函数
    result = _format_economic_data_for_analysis(test_data)
    print("格式化结果:")
    print(result)
    print("\n" + "="*50)
    
    # 验证结果
    assert "美国经济数据" in result, "应该包含美国经济数据"
    assert "中国经济数据" in result, "应该包含中国经济数据"
    assert "USM1....A" in result, "应该包含助记符"
    assert "18762.6" in result, "应该包含最新值"
    assert "4.24%" in result, "应该包含同比变化"
    assert "U.S. Dollar Billions" in result, "应该包含单位"
    
    print("✅ 新经济数据格式处理测试通过！")
    
    # 测试指标类型推断
    print("\n=== 测试指标类型推断 ===")
    test_mnemonics = ['USM1....A', 'CHGDP....', 'USCPI....', 'CHCPI....']
    for mnemonic in test_mnemonics:
        indicator_type = _get_indicator_type_from_mnemonic(mnemonic)
        print(f"{mnemonic} -> {indicator_type}")
    
    print("\n✅ 所有测试通过！")

if __name__ == "__main__":
    test_new_economic_format()