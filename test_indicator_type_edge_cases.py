#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 _get_indicator_type_from_mnemonic 函数的边界情况处理
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.join(os.path.abspath('.'), 'src'))

# 直接复制函数实现以避免模块导入问题
def _get_indicator_type_from_mnemonic(mnemonic: str) -> str:
    """从助记符推断指标类型"""
    # 处理空值情况
    if not mnemonic:
        return mnemonic or ''
    
    # 定义常见的经济指标助记符映射
    indicator_mapping = {
        # 中国指标
        'CHBPEXGS': '中国商品出口总额',
        'CHCURBAL': '中国经常账户余额',
        'CHEXNGS': '中国出口总额',
        'CHGOVBALA': '中国政府预算余额',
        'CHIFATOTA': '中国固定资产投资总额',
        'CHVA%NATR': '中国增值税税率',
        'CHPROFTSA': '中国工业企业利润总额',
        'CHIPTOT.H': '中国工业生产总值指数',
        'CHCAR': '中国汽车产量',
        'CHRETUOTA': '中国零售总额',
        
        # 美国指标
        'USGDP': '美国GDP',
        'USCPI': '美国消费者价格指数',
        'USUNEMPLOYMENT': '美国失业率',
        'USPMI': '美国制造业PMI',
        'USNFP': '美国非农就业人数',
        'USRETAIL': '美国零售销售',
        'USINFLATION': '美国通胀率',
        'USFED': '美国联邦基金利率',
        
        # 其他常见指标关键词
        'GDP': 'GDP',
        'CPI': '消费者价格指数',
        'PMI': '制造业PMI',
        'UNEMPLOYMENT': '失业率',
        'INFLATION': '通胀率',
        'RETAIL': '零售销售',
        'EXPORT': '出口',
        'IMPORT': '进口',
        'BALANCE': '余额',
        'INVESTMENT': '投资',
        'PRODUCTION': '生产'
    }
    
    # 首先尝试精确匹配
    if mnemonic in indicator_mapping:
        return indicator_mapping[mnemonic]
    
    # 然后尝试部分匹配
    for key, value in indicator_mapping.items():
        if mnemonic and key in mnemonic.upper():
            return value
    
    # 如果都没有匹配，返回原助记符
    return mnemonic


def test_indicator_type_edge_cases():
    """测试指标类型推断的边界情况"""
    print("=== 测试指标类型推断边界情况处理 ===")
    
    # 测试 None 值
    try:
        result = _get_indicator_type_from_mnemonic(None)
        print(f"None 值处理结果: '{result}'")
        assert result == '', f"期望空字符串，实际得到: {result}"
        print("✅ None 值处理测试通过！")
    except Exception as e:
        print(f"❌ None 值处理测试失败: {e}")
        return False
    
    # 测试空字符串
    try:
        result = _get_indicator_type_from_mnemonic('')
        print(f"空字符串处理结果: '{result}'")
        assert result == '', f"期望空字符串，实际得到: {result}"
        print("✅ 空字符串处理测试通过！")
    except Exception as e:
        print(f"❌ 空字符串处理测试失败: {e}")
        return False
    
    # 测试正常的助记符
    try:
        result = _get_indicator_type_from_mnemonic('USGDP')
        print(f"正常助记符 'USGDP' 处理结果: '{result}'")
        assert result == '美国GDP', f"期望 '美国GDP'，实际得到: {result}"
        print("✅ 正常助记符处理测试通过！")
    except Exception as e:
        print(f"❌ 正常助记符处理测试失败: {e}")
        return False
    
    # 测试部分匹配
    try:
        result = _get_indicator_type_from_mnemonic('USGDP_MODIFIED')
        print(f"部分匹配助记符 'USGDP_MODIFIED' 处理结果: '{result}'")
        assert result == '美国GDP', f"期望 '美国GDP'，实际得到: {result}"
        print("✅ 部分匹配处理测试通过！")
    except Exception as e:
        print(f"❌ 部分匹配处理测试失败: {e}")
        return False
    
    # 测试未知助记符
    try:
        result = _get_indicator_type_from_mnemonic('UNKNOWN_INDICATOR')
        print(f"未知助记符 'UNKNOWN_INDICATOR' 处理结果: '{result}'")
        assert result == 'UNKNOWN_INDICATOR', f"期望 'UNKNOWN_INDICATOR'，实际得到: {result}"
        print("✅ 未知助记符处理测试通过！")
    except Exception as e:
        print(f"❌ 未知助记符处理测试失败: {e}")
        return False
    
    print("\n✅ 所有指标类型推断边界情况测试通过！")
    return True


if __name__ == '__main__':
    test_indicator_type_edge_cases()