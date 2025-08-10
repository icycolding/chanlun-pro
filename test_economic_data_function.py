#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新的经济数据获取函数
验证外汇对识别和经济数据查询功能
"""

import sys
import os

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web')

# 模拟数据库查询结果
class MockEconomicData:
    def __init__(self, indicator_name, value, date):
        self.indicator_name = indicator_name
        self.value = value
        self.date = date
        self.id = 1
        
    def __dict__(self):
        return {
            'indicator_name': self.indicator_name,
            'value': self.value,
            'date': self.date,
            'id': self.id
        }

class MockDB:
    def economic_data_query(self, indicator_name, limit=1000):
        # 模拟返回不同国家的经济数据
        mock_data = [
            MockEconomicData(indicator_name, f"{indicator_name}_value_1", "2024-01-01"),
            MockEconomicData(indicator_name, f"{indicator_name}_value_2", "2024-01-02")
        ]
        return mock_data[:limit]

# 模拟数据库模块
class MockDBModule:
    def __init__(self):
        self.db = MockDB()

# 替换真实的数据库模块
sys.modules['chanlun.db'] = MockDBModule()

# 复制函数实现进行测试
def _get_economic_data_by_product(product_info=None, product_code=None, limit=1000):
    """
    根据产品信息获取相关的经济数据
    
    Args:
        product_info: 产品信息字典，包含产品类型等信息
        product_code: 产品代码，如 'EURUSD', 'GBPJPY' 等
        limit: 查询数据条数限制
        
    Returns:
        List[Dict]: 经济数据列表
    """
    from chanlun.db import db
    
    # 外汇货币对到国家/地区的映射
    currency_to_country = {
        'USD': 'us',
        'EUR': 'eur', 
        'GBP': 'gbp',
        'JPY': 'jpy',
        'CHF': 'chf',
        'CAD': 'cad',
        'AUD': 'aud',
        'NZD': 'nzd',
        'CNY': 'china',
        'CNH': 'china',
        'HKD': 'hkd',
        'SGD': 'sgd'
    }
    
    economic_data_list = []
    countries_to_query = set()
    
    # 判断是否为外汇产品
    is_forex = False
    if product_info:
        product_type = product_info.get('type', '').lower()
        is_forex = product_type in ['forex', 'currency', '外汇', '货币']
    
    # 如果是外汇产品，从产品代码中提取货币对
    if is_forex and product_code:
        # 处理常见的外汇对格式，如 EURUSD, GBPJPY 等
        if len(product_code) >= 6:
            base_currency = product_code[:3].upper()
            quote_currency = product_code[3:6].upper()
            
            # 添加对应的国家/地区到查询列表
            if base_currency in currency_to_country:
                countries_to_query.add(currency_to_country[base_currency])
            if quote_currency in currency_to_country:
                countries_to_query.add(currency_to_country[quote_currency])
    
    # 如果没有识别到外汇对或者不是外汇产品，使用默认的主要经济体
    if not countries_to_query:
        countries_to_query = {'us', 'china'}  # 默认查询美国和中国的经济数据
    
    # 查询每个国家/地区的经济数据
    for country in countries_to_query:
        try:
            country_data = db.economic_data_query(indicator_name=country, limit=limit)
            # 转换为字典格式
            country_data_dict = [item.__dict__() for item in country_data]
            economic_data_list.extend(country_data_dict)
        except Exception as e:
            print(f"查询 {country} 经济数据时出错: {e}")
            continue
    
    print(f"获取到 {len(economic_data_list)} 条经济数据，涉及国家/地区: {list(countries_to_query)}")
    return economic_data_list

def test_economic_data_function():
    print("=== 测试经济数据获取函数 ===")
    
    # 测试1: 默认情况（无产品信息）
    print("\n测试1: 默认情况")
    result1 = _get_economic_data_by_product()
    print(f"结果: 获取到 {len(result1)} 条数据")
    assert len(result1) > 0, "默认情况应该返回数据"
    
    # 测试2: 外汇产品 - EURUSD
    print("\n测试2: 外汇产品 EURUSD")
    product_info_forex = {'type': 'forex'}
    result2 = _get_economic_data_by_product(
        product_info=product_info_forex, 
        product_code='EURUSD'
    )
    print(f"结果: 获取到 {len(result2)} 条数据")
    # 应该包含EUR和USD对应的数据
    countries_found = set()
    for item in result2:
        countries_found.add(item['indicator_name'])
    print(f"涉及国家: {countries_found}")
    assert 'eur' in countries_found or 'us' in countries_found, "应该包含EUR或USD相关数据"
    
    # 测试3: 外汇产品 - GBPJPY
    print("\n测试3: 外汇产品 GBPJPY")
    result3 = _get_economic_data_by_product(
        product_info=product_info_forex, 
        product_code='GBPJPY'
    )
    print(f"结果: 获取到 {len(result3)} 条数据")
    countries_found = set()
    for item in result3:
        countries_found.add(item['indicator_name'])
    print(f"涉及国家: {countries_found}")
    assert 'gbp' in countries_found or 'jpy' in countries_found, "应该包含GBP或JPY相关数据"
    
    # 测试4: 外汇产品 - USDCNY
    print("\n测试4: 外汇产品 USDCNY")
    result4 = _get_economic_data_by_product(
        product_info=product_info_forex, 
        product_code='USDCNY'
    )
    print(f"结果: 获取到 {len(result4)} 条数据")
    countries_found = set()
    for item in result4:
        countries_found.add(item['indicator_name'])
    print(f"涉及国家: {countries_found}")
    assert 'us' in countries_found or 'china' in countries_found, "应该包含US或China相关数据"
    
    # 测试5: 非外汇产品
    print("\n测试5: 非外汇产品")
    product_info_stock = {'type': 'stock'}
    result5 = _get_economic_data_by_product(
        product_info=product_info_stock, 
        product_code='AAPL'
    )
    print(f"结果: 获取到 {len(result5)} 条数据")
    countries_found = set()
    for item in result5:
        countries_found.add(item['indicator_name'])
    print(f"涉及国家: {countries_found}")
    # 非外汇产品应该返回默认的美国和中国数据
    assert 'us' in countries_found and 'china' in countries_found, "非外汇产品应该返回默认的US和China数据"
    
    # 测试6: 外汇产品但代码格式不正确
    print("\n测试6: 外汇产品但代码格式不正确")
    result6 = _get_economic_data_by_product(
        product_info=product_info_forex, 
        product_code='EUR'  # 太短，不是标准外汇对格式
    )
    print(f"结果: 获取到 {len(result6)} 条数据")
    countries_found = set()
    for item in result6:
        countries_found.add(item['indicator_name'])
    print(f"涉及国家: {countries_found}")
    # 格式不正确时应该返回默认数据
    assert 'us' in countries_found and 'china' in countries_found, "格式不正确时应该返回默认数据"
    
    print("\n=== 所有测试通过! ===")

if __name__ == '__main__':
    test_economic_data_function()