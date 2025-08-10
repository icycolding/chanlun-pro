#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试EM和EK前缀的欧洲识别功能
验证经济数据格式化函数能正确识别EM、EK开头的助记符为欧洲
"""

# 复制相关函数进行测试
def _format_economic_data_for_analysis(economic_data):
    """
    格式化经济数据用于分析
    """
    if not economic_data:
        return "暂无经济数据"
    
    # 按国家分组经济数据
    countries_data = {}
    
    # 定义助记符前缀到国家的映射
    country_mapping = {
        'CH': '中国',
        'US': '美国',
        'EU': '欧盟',
        'EM': '欧洲',  # 欧洲经济数据助记符前缀
        'EK': '欧洲',  # 欧洲经济数据助记符前缀
        'JP': '日本',
        'UK': '英国',
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
            if indicator_name and ('cny' in indicator_name or '中国' in indicator_name or 'ch' in indicator_name):
                country = '中国'
            elif indicator_name and ('usd' in indicator_name or 'america' in indicator_name or '美国' in indicator_name):
                country = '美国'
            elif indicator_name and ('eur' in indicator_name or 'europe' in indicator_name or '欧盟' in indicator_name):
                country = '欧盟'
            elif indicator_name and ('jpy' in indicator_name or 'japan' in indicator_name or '日本' in indicator_name):
                country = '日本'
            elif indicator_name and ('gbp' in indicator_name or 'uk' in indicator_name or '英国' in indicator_name):
                country = '英国'
            elif indicator_name and ('cad' in indicator_name or 'canada' in indicator_name or '加拿大' in indicator_name):
                country = '加拿大'
            elif indicator_name and ('aud' in indicator_name or 'australia' in indicator_name or '澳大利亚' in indicator_name):
                country = '澳大利亚'
            elif indicator_name and ('nzd' in indicator_name or 'new zealand' in indicator_name or '新西兰' in indicator_name):
                country = '新西兰'
            else:
                country = '其他'
        
        if country not in countries_data:
            countries_data[country] = []
        
        # 格式化单个数据项
        formatted_item = {
            'indicator_name': data.get('indicator_name', '未知指标'),
            'value': data.get('value', 'N/A'),
            'date': data.get('date', 'N/A'),
            'mnemonic': mnemonic,
            'country': country
        }
        countries_data[country].append(formatted_item)
    
    return countries_data

def test_em_ek_europe_mapping():
    print("=== 测试EM和EK前缀的欧洲识别功能 ===")
    
    # 测试数据：包含EM和EK前缀的助记符
    test_economic_data = [
        {
            'ds_mnemonic': 'EMCPI001',
            'indicator_name': 'European CPI',
            'value': 2.5,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'EKGDP002',
            'indicator_name': 'European GDP',
            'value': 1.8,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'EMINF003',
            'indicator_name': 'European Inflation',
            'value': 2.1,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'EKUNEMP004',
            'indicator_name': 'European Unemployment',
            'value': 6.5,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'USRATE001',
            'indicator_name': 'US Interest Rate',
            'value': 5.25,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'CHCPI001',
            'indicator_name': 'China CPI',
            'value': 0.2,
            'date': '2024-01-01'
        }
    ]
    
    # 调用格式化函数
    result = _format_economic_data_for_analysis(test_economic_data)
    
    print("\n格式化结果:")
    for country, data_list in result.items():
        print(f"\n{country}:")
        for item in data_list:
            print(f"  - 助记符: {item['mnemonic']}, 指标: {item['indicator_name']}, 值: {item['value']}")
    
    # 验证结果
    print("\n=== 验证结果 ===")
    
    # 检查EM前缀是否被识别为欧洲
    europe_data = result.get('欧洲', [])
    em_data = [item for item in europe_data if item['mnemonic'].startswith('EM')]
    ek_data = [item for item in europe_data if item['mnemonic'].startswith('EK')]
    
    print(f"欧洲数据总数: {len(europe_data)}")
    print(f"EM前缀数据: {len(em_data)}")
    print(f"EK前缀数据: {len(ek_data)}")
    
    # 断言验证
    assert len(em_data) == 2, f"应该有2个EM前缀的数据，实际有{len(em_data)}个"
    assert len(ek_data) == 2, f"应该有2个EK前缀的数据，实际有{len(ek_data)}个"
    assert len(europe_data) == 4, f"欧洲数据总数应该是4，实际是{len(europe_data)}"
    
    # 验证具体的助记符
    em_mnemonics = [item['mnemonic'] for item in em_data]
    ek_mnemonics = [item['mnemonic'] for item in ek_data]
    
    assert 'EMCPI001' in em_mnemonics, "EMCPI001应该被识别为欧洲"
    assert 'EMINF003' in em_mnemonics, "EMINF003应该被识别为欧洲"
    assert 'EKGDP002' in ek_mnemonics, "EKGDP002应该被识别为欧洲"
    assert 'EKUNEMP004' in ek_mnemonics, "EKUNEMP004应该被识别为欧洲"
    
    # 验证其他国家的数据
    us_data = result.get('美国', [])
    china_data = result.get('中国', [])
    
    assert len(us_data) == 1, f"美国数据应该有1个，实际有{len(us_data)}个"
    assert len(china_data) == 1, f"中国数据应该有1个，实际有{len(china_data)}个"
    
    print("\n✅ 所有测试通过！")
    print("✅ EM前缀正确识别为欧洲")
    print("✅ EK前缀正确识别为欧洲")
    print("✅ 其他前缀识别正常")

def test_edge_cases():
    print("\n=== 测试边界情况 ===")
    
    # 测试边界情况
    edge_case_data = [
        {
            'ds_mnemonic': 'EM',  # 只有前缀
            'indicator_name': 'Short EM',
            'value': 1.0,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'EK',  # 只有前缀
            'indicator_name': 'Short EK',
            'value': 2.0,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'EMTEST',  # EM开头但不是标准格式
            'indicator_name': 'EM Test',
            'value': 3.0,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'EKTEST',  # EK开头但不是标准格式
            'indicator_name': 'EK Test',
            'value': 4.0,
            'date': '2024-01-01'
        },
        {
            'ds_mnemonic': 'NOTMATCH',  # 不匹配任何前缀
            'indicator_name': 'Unknown Indicator',  # 避免包含会被识别的关键词
            'value': 5.0,
            'date': '2024-01-01'
        }
    ]
    
    result = _format_economic_data_for_analysis(edge_case_data)
    
    print("\n边界情况结果:")
    for country, data_list in result.items():
        print(f"\n{country}:")
        for item in data_list:
            print(f"  - 助记符: {item['mnemonic']}, 指标: {item['indicator_name']}")
    
    # 验证边界情况
    europe_data = result.get('欧洲', [])
    other_data = result.get('其他', [])
    
    assert len(europe_data) == 4, f"欧洲数据应该有4个，实际有{len(europe_data)}个"
    assert len(other_data) == 1, f"其他数据应该有1个，实际有{len(other_data)}个"
    
    europe_mnemonics = [item['mnemonic'] for item in europe_data]
    assert 'EM' in europe_mnemonics, "单独的EM应该被识别为欧洲"
    assert 'EK' in europe_mnemonics, "单独的EK应该被识别为欧洲"
    assert 'EMTEST' in europe_mnemonics, "EMTEST应该被识别为欧洲"
    assert 'EKTEST' in europe_mnemonics, "EKTEST应该被识别为欧洲"
    
    other_mnemonics = [item['mnemonic'] for item in other_data]
    assert 'NOTMATCH' in other_mnemonics, "NOTMATCH应该被识别为其他"
    
    print("\n✅ 边界情况测试通过！")
    print("✅ 不匹配的助记符正确识别为其他类别")

if __name__ == '__main__':
    test_em_ek_europe_mapping()
    test_edge_cases()
    print("\n🎉 所有测试完成！EM和EK前缀欧洲识别功能正常工作。")