#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的POST请求测试脚本
用于逐步调试财务数据POST请求问题
"""

import requests
import json
import base64
import os
from datetime import datetime

def test_economic_data_post():
    """
    测试经济数据POST请求（作为对照组）
    """
    print("\n=== 测试经济数据POST请求 ===")
    
    url = "http://localhost:9901/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    payload = {
        "data_type": "economic_data",
        "data": {
            "indicator_name": "测试指标",
            "latest_value": 100.5
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"请求失败: {e}")
        return False

def test_financials_minimal():
    """
    测试最小化的财务数据POST请求
    """
    print("\n=== 测试最小化财务数据POST请求 ===")
    
    url = "http://localhost:9901/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    # 创建一个很小的测试Excel文件的base64编码
    test_excel_data = b"\x50\x4b\x03\x04"  # 简单的测试数据
    excel_base64 = base64.b64encode(test_excel_data).decode('utf-8')
    
    payload = {
        "data_type": "company_financials",
        "company_code": "TEST",
        "company_name": "测试公司",
        "excel_base64_data": excel_base64
    }
    
    print(f"请求数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        print(f"响应内容: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"请求失败: {e}")
        return False

def test_financials_with_file_path():
    """
    测试使用文件路径的财务数据POST请求
    """
    print("\n=== 测试文件路径财务数据POST请求 ===")
    
    url = "http://localhost:9901/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    payload = {
        "data_type": "company_financials",
        "company_code": "LI",
        "company_name": "理想汽车",
        "excel_file_path": "company/理想汽车.xls",
        "excel_base64_data": "dummy"  # 提供一个假的base64数据
    }
    
    print(f"请求数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        print(f"响应内容: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"请求失败: {e}")
        return False

def main():
    print("🔍 开始逐步调试POST请求")
    print("=" * 50)
    
    # 测试1: 经济数据POST（对照组）
    success1 = test_economic_data_post()
    
    # 测试2: 最小化财务数据POST
    success2 = test_financials_minimal()
    
    # 测试3: 文件路径财务数据POST
    success3 = test_financials_with_file_path()
    
    print("\n" + "=" * 50)
    print("📊 测试结果汇总:")
    print(f"经济数据POST: {'✅ 成功' if success1 else '❌ 失败'}")
    print(f"最小化财务数据POST: {'✅ 成功' if success2 else '❌ 失败'}")
    print(f"文件路径财务数据POST: {'✅ 成功' if success3 else '❌ 失败'}")
    print("=" * 50)

if __name__ == "__main__":
    main()