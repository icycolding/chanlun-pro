#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试使用文件路径的财务数据POST请求
"""

import requests
import json
from datetime import datetime

def test_financials_with_file_path():
    """
    测试使用文件路径的财务数据POST请求
    """
    print("💼 测试财务数据POST请求（使用文件路径）")
    print("-" * 50)
    
    url = "http://localhost:9901/api/economic/data"
    headers = {'Content-Type': 'application/json'}
    
    # 财务数据测试payload（使用文件路径）
    payload = {
        "data_type": "company_financials",
        "company_code": "LI",
        "company_name": "理想汽车",
        "excel_file_path": "company/理想汽车.xls",
        "excel_base64_data": ""  # 空的base64数据，让服务器使用文件路径
    }
    
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        print(f"\n⏰ 发送请求时间: {datetime.now().strftime('%H:%M:%S')}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"📈 响应状态码: {response.status_code}")
        print(f"⏱️  响应时间: {response.elapsed.total_seconds():.2f}秒")
        print(f"📄 响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                print(f"\n✅ 财务数据POST成功!")
                data = result.get('data', {})
                print(f"📊 处理记录数: {data.get('total_records', 0)}")
                print(f"📋 处理工作表: {data.get('processed_sheets', [])}")
                return True
            else:
                print(f"\n❌ 请求失败: {result.get('msg', '未知错误')}")
                return False
        else:
            print(f"\n❌ HTTP错误: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"\n❌ 请求异常: {e}")
        return False

def main():
    print("🔧 财务数据POST测试 - 文件路径版")
    print("=" * 50)
    
    # 测试使用文件路径的请求
    success = test_financials_with_file_path()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 测试完成 - 请求成功!")
    else:
        print("💔 测试完成 - 请求失败")
        print("\n💡 提示: 如果文件路径方式失败，可能需要使用base64编码方式")
    print("=" * 50)

if __name__ == "__main__":
    main()