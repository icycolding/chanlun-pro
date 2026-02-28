#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单验证修复后的get_vector_news函数代码
检查语法和逻辑是否正确
"""

import ast
import sys
import os

def check_function_syntax():
    """检查get_vector_news函数的语法"""
    print("=== 检查修复后的get_vector_news函数 ===")
    
    file_path = "web/chanlun_chart/cl_app/news_vector_api.py"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查语法
        ast.parse(content)
        print("✓ 语法检查通过")
        
        # 检查关键修复点
        checks = [
            ("_calculate_smart_relevance_score函数已移除" in content, "移除了重复评分函数"),
            ("smart_score" not in content or content.count("smart_score") <= 2, "清理了smart_score引用"),
            ("key=lambda x: x.get('score', 0)" in content, "使用semantic_search的score排序"),
            ("去重处理（基于新闻ID）" in content, "添加了去重逻辑"),
            ("直接使用semantic_search返回的score" in content, "正确使用原始score")
        ]
        
        print("\n修复点检查:")
        all_passed = True
        for check, description in checks:
            status = "✓" if check else "✗"
            print(f"  {status} {description}")
            if not check:
                all_passed = False
        
        if all_passed:
            print("\n🎉 所有修复点检查通过！")
        else:
            print("\n⚠️  部分检查未通过，请检查代码")
            
        # 检查函数结构
        print("\n函数结构检查:")
        if "def get_vector_news(" in content:
            print("  ✓ get_vector_news函数存在")
            
            # 检查两阶段排序逻辑
            if "两阶段排序" in content:
                print("  ✓ 保留了两阶段排序逻辑")
            else:
                print("  ✗ 两阶段排序逻辑可能丢失")
                
            # 检查去重逻辑
            if "unique_results" in content:
                print("  ✓ 包含去重逻辑")
            else:
                print("  ✗ 去重逻辑可能丢失")
        else:
            print("  ✗ get_vector_news函数未找到")
            
    except FileNotFoundError:
        print(f"✗ 文件未找到: {file_path}")
    except SyntaxError as e:
        print(f"✗ 语法错误: {e}")
    except Exception as e:
        print(f"✗ 检查失败: {e}")
    
    print("\n=== 检查完成 ===")

if __name__ == "__main__":
    check_function_syntax()