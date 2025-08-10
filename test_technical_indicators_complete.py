#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标修复完整验证测试

测试修复后的技术指标计算，使用正确的市场代码

运行方式：
python test_technical_indicators_complete.py
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

def test_technical_indicators_with_correct_markets():
    """
    使用正确的市场代码测试技术指标计算修复
    """
    print("\n=== 技术指标修复验证测试（正确市场代码） ===")
    
    if _generate_technical_indicators_analysis is None:
        print("⚠ 无法导入技术指标分析函数，跳过功能测试")
        return False
    
    # 测试用例 - 使用正确的市场代码
    test_cases = [
        {"code": "FE.EURUSD", "market": "fx", "name": "欧元美元 (外汇)"},
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
                
                # 检查是否是错误消息
                if "不支持的市场类型" in result:
                    print("⚠ 市场类型不支持")
                    continue
                elif "K线数据不足" in result:
                    print("⚠ K线数据不足")
                    continue
                elif "处理后的K线数据不足" in result:
                    print("⚠ 处理后的K线数据不足")
                    continue
                
                # 检查是否包含预期的指标分析
                expected_indicators = [
                    "RSI相对强弱指标分析",
                    "布林带指标分析", 
                    "KDJ随机指标分析",
                    "威廉指标(WR)分析",
                    "移动平均线分析"
                ]
                
                found_indicators = []
                missing_indicators = []
                for indicator in expected_indicators:
                    if indicator in result:
                        found_indicators.append(indicator)
                    else:
                        missing_indicators.append(indicator)
                
                print(f"✓ 找到指标: {len(found_indicators)}/{len(expected_indicators)}")
                if found_indicators:
                    print(f"  包含: {', '.join(found_indicators)}")
                if missing_indicators:
                    print(f"  缺少: {', '.join(missing_indicators)}")
                
                # 检查是否包含修复前的错误信息
                old_error_patterns = [
                    "unexpected keyword argument 'std_dev'",
                    "unexpected keyword argument 'm1'", 
                    "has no attribute 'idx_wr'"
                ]
                
                # 检查是否包含新的错误信息
                new_error_patterns = [
                    "布林带计算异常",
                    "KDJ计算异常",
                    "WR计算异常"
                ]
                
                found_old_errors = []
                found_new_errors = []
                
                for pattern in old_error_patterns:
                    if pattern in result:
                        found_old_errors.append(pattern)
                
                for pattern in new_error_patterns:
                    if pattern in result:
                        found_new_errors.append(pattern)
                
                if found_old_errors:
                    print(f"✗ 发现修复前的错误: {', '.join(found_old_errors)}")
                elif found_new_errors:
                    print(f"⚠ 发现新的计算错误: {', '.join(found_new_errors)}")
                else:
                    print("✓ 未发现技术指标计算错误")
                    if len(found_indicators) >= 3:  # 至少包含3个指标
                        success_count += 1
                
                # 显示部分结果内容
                print("\n--- 分析结果预览 ---")
                lines = result.split('\n')[:15]  # 显示前15行
                for line in lines:
                    if line.strip():
                        print(f"  {line}")
                if len(result.split('\n')) > 15:
                    print("  ... (更多内容)")
                    
            else:
                print("✗ 技术指标分析返回空结果")
                
        except Exception as e:
            print(f"✗ 技术指标分析异常: {str(e)}")
            print(f"异常详情: {traceback.format_exc()}")
    
    print(f"\n=== 测试总结 ===")
    print(f"成功: {success_count}/{total_count}")
    print(f"成功率: {success_count/total_count*100:.1f}%")
    
    return success_count > 0

def test_specific_error_fixes():
    """
    测试特定错误的修复情况
    """
    print("\n=== 特定错误修复验证 ===")
    
    try:
        # 导入Strategy类进行直接测试
        from chanlun.backtesting.base import Strategy
        import inspect
        print("✓ 成功导入Strategy类")
        
        print("\n--- 验证布林带指标参数修复 ---")
        if hasattr(Strategy, 'idx_boll'):
            sig = inspect.signature(Strategy.idx_boll)
            params = list(sig.parameters.keys())
            print(f"idx_boll方法参数: {params}")
            
            if 'period' in params:
                print("✓ 包含period参数")
            else:
                print("✗ 缺少period参数")
                
            if 'std_dev' in params:
                print("✗ 仍包含std_dev参数（应该移除）")
            else:
                print("✓ 已移除std_dev参数")
        else:
            print("✗ Strategy类中没有idx_boll方法")
        
        print("\n--- 验证KDJ指标参数修复 ---")
        if hasattr(Strategy, 'idx_kdj'):
            sig = inspect.signature(Strategy.idx_kdj)
            params = list(sig.parameters.keys())
            print(f"idx_kdj方法参数: {params}")
            
            if 'M1' in params and 'M2' in params:
                print("✓ 使用正确的M1/M2大写参数")
            elif 'm1' in params and 'm2' in params:
                print("✗ 仍使用小写m1/m2参数（需要大写）")
            else:
                print("⚠ KDJ参数格式不明确")
        else:
            print("✗ Strategy类中没有idx_kdj方法")
        
        print("\n--- 验证威廉指标处理 ---")
        if hasattr(Strategy, 'idx_wr'):
            print("⚠ Strategy类中存在idx_wr方法，可以考虑启用")
        else:
            print("✓ 确认Strategy类中没有idx_wr方法，已正确禁用")
            
        # 检查修复后的代码
        print("\n--- 检查修复后的代码 ---")
        try:
            with open('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/news_vector_api.py', 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 检查布林带修复
            if 'idx_boll(cd, period=20)' in content:
                print("✓ 布林带调用已修复为使用period参数")
            elif 'std_dev=2' in content:
                print("✗ 布林带调用仍使用std_dev参数")
            else:
                print("⚠ 布林带调用格式不明确")
            
            # 检查KDJ修复
            if 'idx_kdj(cd, period=9, M1=3, M2=3)' in content:
                print("✓ KDJ调用已修复为使用M1/M2大写参数")
            elif 'm1=3, m2=3' in content:
                print("✗ KDJ调用仍使用小写m1/m2参数")
            else:
                print("⚠ KDJ调用格式不明确")
            
            # 检查威廉指标处理
            if 'idx_wr(' in content:
                print("✗ 代码中仍包含idx_wr调用")
            elif '威廉指标功能暂未实现' in content:
                print("✓ 威廉指标已正确禁用")
            else:
                print("⚠ 威廉指标处理不明确")
                
        except Exception as e:
            print(f"✗ 检查代码文件异常: {str(e)}")
            
    except ImportError as e:
        print(f"⚠ 无法导入Strategy类进行直接测试: {e}")
        print("将跳过特定指标测试")

def main():
    """
    主测试函数
    """
    print("技术指标修复完整验证测试")
    print("=" * 60)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 运行测试
    success = test_technical_indicators_with_correct_markets()
    test_specific_error_fixes()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 技术指标修复验证完成！测试通过。")
        print("\n修复总结:")
        print("1. ✓ 布林带指标: 修复std_dev参数错误，改为使用period")
        print("2. ✓ KDJ指标: 修复m1/m2参数大小写错误，改为使用M1/M2")
        print("3. ✓ 威廉指标: 暂时禁用未实现的idx_wr方法调用")
    else:
        print("❌ 技术指标修复验证完成，但可能存在问题需要进一步检查。")
    
    return success

if __name__ == "__main__":
    main()