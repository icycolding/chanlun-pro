#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试经济数据API的POST payload格式支持
验证包装格式：{"source": "excel_upload", "data": [...]}
"""

import requests
import json
import sys
import os

# 添加项目路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from chanlun.db import db

def test_post_payload_format():
    """
    测试POST请求的payload格式支持
    """
    print("=== 测试经济数据API POST payload格式支持 ===")
    
    # 测试数据
    economic_data_list = [
        {
            "indicator_name": "GDP增长率",
            "latest_value": 6.8,
            "latest_value_date": "2024-01-15T00:00:00Z",
            "previous_value": 6.5,
            "previous_value_date": "2023-12-15T00:00:00Z",
            "year": 2024,
            "units": "%",
            "ds_mnemonic": "GDP_GROWTH_TEST"
        },
        {
            "indicator_name": "通胀率",
            "latest_value": 2.1,
            "latest_value_date": "2024-01-15T00:00:00Z",
            "year": 2024,
            "units": "%",
            "ds_mnemonic": "INFLATION_TEST"
        }
    ]
    
    # 清理可能存在的测试数据
    print("\n1. 清理测试数据...")
    try:
        db.economic_data_delete("GDP_GROWTH_TEST")
        db.economic_data_delete("INFLATION_TEST")
        print("测试数据清理完成")
    except Exception as e:
        print(f"清理测试数据时出错: {e}")
    
    # 测试包装格式的POST请求
    base_url = "http://127.0.0.1:9901"
    url = f"{base_url}/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    # 用户使用的payload格式
    payload = {
        "source": "excel_upload",
        "data": economic_data_list
    }
    
    print(f"\n2. 测试包装格式POST请求...")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"\n响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ POST请求成功!")
            print(f"处理结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"\n❌ POST请求失败: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"\n❌ 请求异常: {e}")
        print("请确保Flask应用正在运行 (python web/chanlun_chart/app.py)")
        return False
    
    # 验证数据是否正确插入
    print("\n3. 验证数据插入...")
    try:
        # 查询插入的数据
        gdp_data = db.economic_data_get_by_mnemonic("GDP_GROWTH_TEST")
        inflation_data = db.economic_data_get_by_mnemonic("INFLATION_TEST")
        
        if gdp_data and inflation_data:
            print(f"✅ 数据插入验证成功!")
            print(f"GDP数据: {gdp_data}")
            print(f"通胀数据: {inflation_data}")
            
            # 验证source字段是否正确设置
            if gdp_data and gdp_data.source == 'excel_upload':
                print(f"✅ Source字段设置正确: {gdp_data.source}")
            else:
                print(f"❌ Source字段设置错误: {gdp_data.source if gdp_data else 'None'}")
        else:
            print(f"❌ 数据插入验证失败")
            return False
            
    except Exception as e:
        print(f"❌ 验证数据时出错: {e}")
        return False
    
    # 清理测试数据
    print("\n4. 清理测试数据...")
    try:
        db.economic_data_delete("GDP_GROWTH_TEST")
        db.economic_data_delete("INFLATION_TEST")
        print("测试数据清理完成")
    except Exception as e:
        print(f"清理测试数据时出错: {e}")
    
    print("\n=== 测试完成 ===")
    return True

if __name__ == "__main__":
    success = test_post_payload_format()
    if success:
        print("\n🎉 所有测试通过!")
    else:
        print("\n💥 测试失败!")
        sys.exit(1)