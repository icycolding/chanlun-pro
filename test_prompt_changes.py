#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试财务分析提示词修改效果
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'web'))

def test_prompt_content():
    """
    测试提示词内容是否包含最新数据分析要求
    """
    try:
        # 读取修改后的文件内容
        with open('web/chanlun_chart/cl_app/news_vector_api.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        print("=" * 60)
        print("财务分析提示词修改验证测试")
        print("=" * 60)
        
        # 检查 _format_financial_data_for_analysis 函数的提示词修改
        print("\n1. 检查 _format_financial_data_for_analysis 函数提示词:")
        
        format_keywords = [
            "分析重点",
            "最新财务数据变动",
            "重点",
            "同比增长率",
            "环比增长率",
            "最新期数据"
        ]
        
        format_found = []
        for keyword in format_keywords:
            if keyword in content:
                format_found.append(keyword)
                print(f"  ✓ 找到关键词: {keyword}")
            else:
                print(f"  ✗ 未找到关键词: {keyword}")
        
        # 检查 financial_analyst_node 函数的提示词修改
        print("\n2. 检查 financial_analyst_node 函数提示词:")
        
        analyst_keywords = [
            "重要分析要求",
            "特别关注最新财务数据变动",
            "核心重点",
            "最新期财务表现",
            "输出格式要求",
            "优先展示最新期对比分析"
        ]
        
        analyst_found = []
        for keyword in analyst_keywords:
            if keyword in content:
                analyst_found.append(keyword)
                print(f"  ✓ 找到关键词: {keyword}")
            else:
                print(f"  ✗ 未找到关键词: {keyword}")
        
        # 总结测试结果
        print("\n" + "=" * 60)
        print("测试结果总结:")
        print(f"_format_financial_data_for_analysis 修改验证: {len(format_found)}/{len(format_keywords)} 关键词找到")
        print(f"financial_analyst_node 修改验证: {len(analyst_found)}/{len(analyst_keywords)} 关键词找到")
        
        if len(format_found) >= 4 and len(analyst_found) >= 4:
            print("\n✅ 提示词修改验证通过！财务分析功能已成功调整为重点分析最新数据变动。")
            return True
        else:
            print("\n⚠️  提示词修改可能不完整，请检查相关函数。")
            return False
            
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        return False

def test_prompt_structure():
    """
    测试提示词结构是否突出最新数据分析
    """
    try:
        with open('web/chanlun_chart/cl_app/news_vector_api.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        print("\n3. 检查提示词结构优化:")
        
        # 查找财务分析相关的提示词部分
        if "分析重点" in content and "重要分析要求" in content:
            print("  ✓ 提示词结构已优化，突出最新数据分析")
            return True
        else:
            print("  ✗ 提示词结构可能需要进一步优化")
            return False
            
    except Exception as e:
        print(f"结构测试过程中出现错误: {e}")
        return False

if __name__ == "__main__":
    print("开始测试财务分析提示词修改效果...\n")
    
    # 执行测试
    content_test = test_prompt_content()
    structure_test = test_prompt_structure()
    
    print("\n" + "=" * 60)
    print("最终测试结果:")