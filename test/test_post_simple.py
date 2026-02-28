#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的POST请求测试脚本
用于快速测试API端点的基本功能
"""

import requests
import json
from datetime import datetime

def test_economic_data_post():
    """
    测试经济数据POST请求
    """
    print("📊 测试经济数据POST请求")
    print("-" * 40)
    
    url = "http://localhost:9901/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    # 经济数据测试payload
    payload = {
        "data_type": "economic_data",
        "data": [
            {
                "indicator_name": "测试指标",
                "latest_value": 100.5,
                "latest_value_date": "2024-01-01T00:00:00Z",
                "units": "测试单位",
                "source": "测试来源"
            }
        ]
    }
    
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"\n状态码: {response.status_code}")
        print(f"响应: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ 经济数据POST成功!")
            return True
        else:
            print(f"\n❌ 经济数据POST失败")
            return False
            
    except Exception as e:
        print(f"\n❌ 请求异常: {e}")
        return False

def test_financials_post_minimal():
    """
    测试财务数据POST请求（最小化测试）
    """
    print("\n💼 测试财务数据POST请求（最小化）")
    print("-" * 40)
    
    url = "http://localhost:9901/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    # 财务数据测试payload（不包含实际Excel数据）
    payload = {
        "data_type": "company_financials",
        "company_code": "TEST",
        "company_name": "测试公司"
        # 故意不包含excel数据，测试错误处理
    }
    
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"\n状态码: {response.status_code}")
        print(f"响应: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 400:  # 预期的错误
                print(f"\n✅ 财务数据POST错误处理正常!")
                return True
            else:
                print(f"\n⚠️  意外的响应: {result}")
                return False
        else:
            print(f"\n❌ 财务数据POST失败")
            return False
            
    except Exception as e:
        print(f"\n❌ 请求异常: {e}")
        return False

def test_server_status():
    """
    测试服务器状态
    """
    print("🌐 测试服务器状态")
    print("-" * 40)
    
    try:
        response = requests.get("http://localhost:9901/", timeout=5)
        print(f"服务器状态: {response.status_code}")
        return response.status_code in [200, 404]  # 200或404都表示服务器在运行
    except Exception as e:
        print(f"❌ 服务器连接失败: {e}")
        return False

def main():
    print("🔧 POST请求调试工具 - 简化版")
    print("=" * 50)
    
    # 1. 测试服务器状态
    if not test_server_status():
        print("\n💡 请先启动Flask服务器")
        return
    
    # 2. 测试经济数据POST
    test_economic_data_post()
    
    # 3. 测试财务数据POST（最小化）
    test_financials_post_minimal()
    
    print("\n" + "=" * 50)
    print("🎯 测试完成")
    print("\n💡 如果需要测试完整的Excel上传，请运行:")
    print("   python debug_post_financials.py")

if __name__ == "__main__":
    main()