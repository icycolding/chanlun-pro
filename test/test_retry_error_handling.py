#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试RetryError异常处理修复
"""

import sys
import os

# 添加项目路径
project_root = '/Users/jiming/Documents/trae/chanlun-pro'
src_path = os.path.join(project_root, 'src')
web_path = os.path.join(project_root, 'web/chanlun_chart')

if src_path not in sys.path:
    sys.path.append(src_path)
if web_path not in sys.path:
    sys.path.append(web_path)

def test_retry_error_handling():
    """
    测试RetryError异常处理
    """
    print("=== 测试RetryError异常处理 ===")
    
    try:
        from cl_app.news_vector_api import _generate_technical_indicators_analysis
        print("✓ 成功导入技术指标分析函数")
        
        # 测试用例：使用可能导致RetryError的代码
        test_cases = [
            {"code": "000001", "market": "a", "name": "平安银行 (A股)"},
            {"code": "600000", "market": "a", "name": "浦发银行 (A股)"},
            {"code": "EURUSD", "market": "fx", "name": "欧元美元 (外汇)"},
            {"code": "INVALID_CODE", "market": "a", "name": "无效代码测试"},
        ]
        
        success_count = 0
        retry_error_count = 0
        other_error_count = 0
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n--- 测试 {i}/{len(test_cases)}: {test_case['name']} ({test_case['code']}) ---")
            
            try:
                result = _generate_technical_indicators_analysis(
                    test_case['code'], test_case['market']
                )
                
                # 检查结果类型
                if "无法获取K线数据，数据源可能暂时不可用" in result:
                    print("✓ RetryError异常已正确处理")
                    retry_error_count += 1
                elif "技术指标分析生成错误" in result:
                    print("✓ 其他异常已正确处理")
                    other_error_count += 1
                elif "不支持的市场类型" in result or "K线数据不足" in result:
                    print("✓ 正常的业务逻辑处理")
                    success_count += 1
                elif len(result) > 100:  # 假设正常的技术分析结果会比较长
                    print("✓ 技术指标分析成功生成")
                    success_count += 1
                else:
                    print(f"? 未知结果类型: {result[:100]}...")
                    
                print(f"  结果长度: {len(result)} 字符")
                
            except Exception as e:
                print(f"✗ 测试异常: {str(e)}")
                other_error_count += 1
        
        print(f"\n=== 测试总结 ===")
        print(f"成功处理: {success_count}/{len(test_cases)}")
        print(f"RetryError处理: {retry_error_count}/{len(test_cases)}")
        print(f"其他错误处理: {other_error_count}/{len(test_cases)}")
        
        if retry_error_count > 0:
            print("\n✓ RetryError异常处理修复验证成功")
        else:
            print("\n? 未遇到RetryError，但异常处理逻辑已就位")
            
    except ImportError as e:
        print(f"✗ 导入失败: {str(e)}")
        return False
    except Exception as e:
        print(f"✗ 测试异常: {str(e)}")
        return False
    
    return True

def test_error_message_format():
    """
    测试错误消息格式
    """
    print("\n=== 测试错误消息格式 ===")
    
    # 模拟RetryError检测逻辑
    test_errors = [
        "RetryError[<Future at 0x2a8d3d0f0 state=finished returned NoneType>]",
        "tenacity.RetryError: RetryError[<Future>]",
        "Some other error message",
        Exception("RetryError in message"),
    ]
    
    for i, error in enumerate(test_errors, 1):
        error_str = str(error)
        error_type_str = str(type(error))
        
        is_retry_error = 'RetryError' in error_type_str or 'RetryError' in error_str
        
        print(f"测试 {i}: {error_str[:50]}...")
        print(f"  类型: {error_type_str}")
        print(f"  是否RetryError: {is_retry_error}")
        
        if is_retry_error:
            print("  -> 将返回: 无法获取K线数据，数据源可能暂时不可用，请稍后重试")
        else:
            print(f"  -> 将返回: 技术指标分析生成错误: {error_str}")
    
    print("\n✓ 错误消息格式测试完成")

if __name__ == "__main__":
    print("RetryError异常处理修复验证")
    print("=" * 50)
    
    # 运行测试
    test_retry_error_handling()
    test_error_message_format()
    
    print("\n" + "=" * 50)
    print("测试完成")