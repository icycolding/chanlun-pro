#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经济数据获取函数使用示例
展示如何使用 _get_economic_data_by_product 函数
"""

# 导入必要的模块
from typing import Dict, List, Optional, Any

def example_usage():
    """
    展示 _get_economic_data_by_product 函数的各种使用方式
    """
    
    print("=== 经济数据获取函数使用示例 ===")
    
    # 示例1: 获取外汇对 EURUSD 的经济数据
    print("\n示例1: 外汇对 EURUSD")
    product_info_forex = {
        'type': 'forex',
        'name': 'EUR/USD',
        'description': '欧元兑美元'
    }
    
    # 调用函数（这里只是示例，实际使用时需要导入真实函数）
    print("调用: _get_economic_data_by_product(product_info=product_info_forex, product_code='EURUSD')")
    print("预期结果: 获取欧元区(eur)和美国(us)的经济数据")
    
    # 示例2: 获取外汇对 GBPJPY 的经济数据
    print("\n示例2: 外汇对 GBPJPY")
    print("调用: _get_economic_data_by_product(product_info={'type': 'forex'}, product_code='GBPJPY')")
    print("预期结果: 获取英国(gbp)和日本(jpy)的经济数据")
    
    # 示例3: 获取外汇对 USDCNY 的经济数据
    print("\n示例3: 外汇对 USDCNY")
    print("调用: _get_economic_data_by_product(product_info={'type': '外汇'}, product_code='USDCNY')")
    print("预期结果: 获取美国(us)和中国(china)的经济数据")
    
    # 示例4: 非外汇产品，使用默认数据
    print("\n示例4: 股票产品")
    product_info_stock = {
        'type': 'stock',
        'name': 'Apple Inc.',
        'symbol': 'AAPL'
    }
    print("调用: _get_economic_data_by_product(product_info=product_info_stock, product_code='AAPL')")
    print("预期结果: 获取默认的美国(us)和中国(china)经济数据")
    
    # 示例5: 无产品信息，使用默认数据
    print("\n示例5: 无产品信息")
    print("调用: _get_economic_data_by_product()")
    print("预期结果: 获取默认的美国(us)和中国(china)经济数据")
    
    # 示例6: 自定义查询限制
    print("\n示例6: 自定义查询限制")
    print("调用: _get_economic_data_by_product(product_info={'type': 'forex'}, product_code='EURUSD', limit=500)")
    print("预期结果: 获取欧元区和美国的经济数据，每个国家最多500条")
    
    print("\n=== 支持的货币对映射 ===")
    currency_mapping = {
        'USD': 'us (美国)',
        'EUR': 'eur (欧元区)', 
        'GBP': 'gbp (英国)',
        'JPY': 'jpy (日本)',
        'CHF': 'chf (瑞士)',
        'CAD': 'cad (加拿大)',
        'AUD': 'aud (澳大利亚)',
        'NZD': 'nzd (新西兰)',
        'CNY': 'china (中国)',
        'CNH': 'china (中国离岸)',
        'HKD': 'hkd (香港)',
        'SGD': 'sgd (新加坡)'
    }
    
    for currency, country in currency_mapping.items():
        print(f"{currency} -> {country}")
    
    print("\n=== 函数特性 ===")
    print("1. 自动识别外汇产品类型")
    print("2. 从外汇对代码中提取基础货币和报价货币")
    print("3. 支持中英文产品类型识别")
    print("4. 提供默认的主要经济体数据")
    print("5. 异常处理和日志记录")
    print("6. 灵活的参数配置")

def integration_example():
    """
    展示如何在现有代码中集成使用
    """
    print("\n=== 集成使用示例 ===")
    
    # 原始代码（已被替换）
    print("\n原始代码:")
    print("""
    from chanlun.db import db
    economic_data_list1 = db.economic_data_query(indicator_name='us', limit=1000)
    economic_data_list1 = [item.__dict__ for item in economic_data_list1]
    economic_data_list2 = db.economic_data_query(indicator_name='china', limit=1000)
    economic_data_list2 = [item.__dict__ for item in economic_data_list2]
    economic_data_list = economic_data_list1 + economic_data_list2
    """)
    
    # 新的代码
    print("\n新的代码:")
    print("""
    # 使用新的函数获取经济数据，支持外汇对智能识别
    economic_data_list = _get_economic_data_by_product(
        product_info=product_info, 
        product_code=product_code, 
        limit=1000
    )
    """)
    
    print("\n优势:")
    print("1. 代码更简洁，从13行减少到5行")
    print("2. 支持外汇对自动识别")
    print("3. 更好的错误处理")
    print("4. 更灵活的配置")
    print("5. 统一的接口")

if __name__ == '__main__':
    example_usage()
    integration_example()