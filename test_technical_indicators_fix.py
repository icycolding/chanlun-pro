#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标修复验证测试脚本

测试修复后的技术指标计算：
1. 布林带指标 - 修复std_dev参数错误
2. KDJ指标 - 修复m1/m2参数大小写错误
3. 威廉指标 - 暂时禁用未实现的功能

运行方式：
python test_technical_indicators_fix.py
"""

import sys
import os
import traceback
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/src')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app')

try:
    from cl_app.news_vector_api import _generate_technical_indicators_analysis
    print("✓ 成功导入技术指标分析模块")
except ImportError as e:
    print(f"✗ 导入模块失败: {e}")
    print("尝试简化测试...")
    _generate_technical_indicators_analysis = None

def test_technical_indicators():
    """
    测试技术指标计算修复
    """
    print("\n=== 技术指标修复验证测试 ===")
    
    if _generate_technical_indicators_analysis is None:
        print("⚠ 无法导入技术指标分析函数，跳过功能测试")
        return False
    
    # 测试用例
    test_cases = [
        {"code": "EURUSD", "market": "forex", "name": "欧元美元"},
        {"code": "GBPUSD", "market": "forex", "name": "英镑美元"},
        {"code": "USDJPY", "market": "forex", "name": "美元日元"},
    ]
    
    success_count = 0
    total_count = len(test_cases)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n--- 测试 {i}/{total_count}: {test_case['name']} ({test_case['code']}) ---")
        
        try:
            # 调用技术指标分析函数
            result = _generate_technical_indicators_analysis(
                code=test_case['code'],
                market=test_case['market']
            )
            
            if result and isinstance(result, str) and len(result) > 0:
                print("✓ 技术指标分析成功生成")
                
                # 检查是否包含预期的指标分析
                expected_indicators = [
                    "RSI相对强弱指标分析",
                    "布林带指标分析", 
                    "KDJ随机指标分析",
                    "威廉指标(WR)分析",
                    "移动平均线分析"
                ]
                
                missing_indicators = []
                for indicator in expected_indicators:
                    if indicator not in result:
                        missing_indicators.append(indicator)
                
                if not missing_indicators:
                    print("✓ 所有预期指标都已包含")
                else:
                    print(f"⚠ 缺少指标: {', '.join(missing_indicators)}")
                
                # 检查是否包含错误信息
                error_patterns = [
                    "unexpected keyword argument 'std_dev'",
                    "unexpected keyword argument 'm1'", 
                    "has no attribute 'idx_wr'",
                    "计算异常",
                    "计算失败"
                ]
                
                found_errors = []
                for pattern in error_patterns:
                    if pattern in result:
                        found_errors.append(pattern)
                
                if not found_errors:
                    print("✓ 未发现技术指标计算错误")
                    success_count += 1
                else:
                    print(f"✗ 发现错误: {', '.join(found_errors)}")
                
                # 显示部分结果内容
                print("\n--- 分析结果预览 ---")
                lines = result.split('\n')[:10]  # 显示前10行
                for line in lines:
                    if line.strip():
                        print(f"  {line}")
                if len(result.split('\n')) > 10:
                    print("  ... (更多内容)")
                    
            else:
                print("✗ 技术指标分析返回空结果")
                
        except Exception as e:
            print(f"✗ 技术指标分析异常: {str(e)}")
            print(f"异常详情: {traceback.format_exc()}")
    
    print(f"\n=== 测试总结 ===")
    print(f"成功: {success_count}/{total_count}")
    print(f"成功率: {success_count/total_count*100:.1f}%")
    
    if success_count == total_count:
        print("🎉 所有技术指标修复验证通过！")
        return True
    else:
        print("❌ 部分技术指标仍存在问题，需要进一步检查")
        return False

def test_specific_indicators():
    """
    测试特定指标的修复情况
    """
    print("\n=== 特定指标修复测试 ===")
    
    try:
        # 导入Strategy类进行直接测试
        from chanlun.backtesting.base import Strategy
        print("✓ 成功导入Strategy类")
        
        print("\n--- 测试布林带指标 (修复std_dev参数) ---")
        try:
            # 检查idx_boll方法的参数
            import inspect
            if hasattr(Strategy, 'idx_boll'):
                sig = inspect.signature(Strategy.idx_boll)
                params = list(sig.parameters.keys())
                print(f"idx_boll参数: {params}")
                if 'period' in params and 'std_dev' not in params:
                    print("✓ 布林带指标参数正确 (使用period，不使用std_dev)")
                else:
                    print("⚠ 布林带指标参数可能需要调整")
            else:
                print("✗ Strategy类中没有idx_boll方法")
        except Exception as e:
            print(f"✗ 布林带指标检查异常: {str(e)}")
        
        print("\n--- 测试KDJ指标 (修复M1/M2参数大小写) ---")
        try:
            if hasattr(Strategy, 'idx_kdj'):
                sig = inspect.signature(Strategy.idx_kdj)
                params = list(sig.parameters.keys())
                print(f"idx_kdj参数: {params}")
                if 'M1' in params and 'M2' in params:
                    print("✓ KDJ指标参数正确 (使用M1/M2大写)")
                elif 'm1' in params and 'm2' in params:
                    print("⚠ KDJ指标参数使用小写m1/m2，需要调整")
                else:
                    print("⚠ KDJ指标参数可能需要调整")
            else:
                print("✗ Strategy类中没有idx_kdj方法")
        except Exception as e:
            print(f"✗ KDJ指标检查异常: {str(e)}")
        
        print("\n--- 测试威廉指标 (确认已禁用) ---")
        try:
            # 确认Strategy类中确实没有idx_wr方法
            if hasattr(Strategy, 'idx_wr'):
                print("⚠ Strategy类中存在idx_wr方法，可能需要启用")
            else:
                print("✓ 确认Strategy类中没有idx_wr方法，已正确禁用")
        except Exception as e:
            print(f"✗ 威廉指标检查异常: {str(e)}")
            
    except ImportError as e:
        print(f"⚠ 无法导入Strategy类进行直接测试: {e}")
        print("将跳过特定指标测试")

def main():
    """
    主测试函数
    """
    print("技术指标修复验证测试")
    print("=" * 50)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 运行测试
    success = test_technical_indicators()
    test_specific_indicators()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 技术指标修复验证完成！所有测试通过。")
    else:
        print("❌ 技术指标修复验证完成，但存在问题需要解决。")
    
    return success

if __name__ == "__main__":
    main()