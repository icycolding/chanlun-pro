#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的财务分析功能
验证偿债能力、流动性、现金流质量等指标不再显示'数据不足'
"""

import sys
import os

# 添加项目路径
project_root = '/Users/jiming/Documents/trae/chanlun-pro'
src_path = os.path.join(project_root, 'src')
web_path = os.path.join(project_root, 'web')

if src_path not in sys.path:
    sys.path.append(src_path)
if web_path not in sys.path:
    sys.path.append(web_path)

try:
    # 导入财务分析相关模块
    from chanlun_chart.cl_app.news_vector_api import financial_analyst_node
    
    print("=" * 80)
    print("测试修复后的财务分析功能")
    print("=" * 80)
    
    # 测试理想汽车的财务分析
    code = "LI"
    market = "us"
    
    print(f"\n正在分析 {code} ({market}) 的财务数据...")
    
    try:
        # 创建状态对象
        state = {
            'current_code': code,
            'current_market': market,
            'name': '理想汽车'
        }
        
        # 调用财务分析函数
        result = financial_analyst_node(state)
        
        print("\n财务分析结果:")
        print("-" * 60)
        
        if isinstance(result, dict) and 'financial_analysis' in result:
            content = result['financial_analysis']
            print(content)
            
            # 检查是否还有'数据不足'的提示
            data_insufficient_count = content.count('数据不足')
            print(f"\n检查结果: 发现 {data_insufficient_count} 处'数据不足'提示")
            
            # 检查关键指标
            key_indicators = [
                '偿债能力',
                '流动性', 
                '现金流质量',
                '成长性'
            ]
            
            print("\n关键指标检查:")
            for indicator in key_indicators:
                if indicator in content:
                    # 提取该指标的评分行
                    lines = content.split('\n')
                    for line in lines:
                        if indicator in line and ('/' in line):
                            print(f"  ✓ {line.strip()}")
                            break
                else:
                    print(f"  ✗ 未找到 {indicator} 指标")
            
            # 检查综合健康评分
            if '综合健康评分' in content:
                lines = content.split('\n')
                for line in lines:
                    if '综合健康评分' in line:
                        print(f"\n  📊 {line.strip()}")
                        break
            
            # 检查财务健康等级
            if '财务健康等级' in content:
                lines = content.split('\n')
                for line in lines:
                    if '财务健康等级' in line:
                        print(f"  🏆 {line.strip()}")
                        break
                        
        else:
            print(f"分析结果格式异常: {result}")
            
    except Exception as e:
        print(f"财务分析调用失败: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n=" * 80)
    print("测试完成")
    print("=" * 80)
    
except ImportError as e:
    print(f"模块导入失败: {str(e)}")
    print("请确保项目路径正确，并且相关模块存在")
except Exception as e:
    print(f"测试脚本执行异常: {str(e)}")
    import traceback
    traceback.print_exc()