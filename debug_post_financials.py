#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务数据POST请求调试脚本
用于测试向/api/economic/data端点发送company_financials类型数据
"""

import requests
import json
import base64
import os
import sys
from datetime import datetime

def encode_excel_to_base64(file_path):
    """
    将Excel文件编码为base64字符串
    """
    try:
        with open(file_path, 'rb') as f:
            excel_data = f.read()
        return base64.b64encode(excel_data).decode('utf-8')
    except Exception as e:
        print(f"❌ 编码Excel文件失败: {e}")
        return None

def test_post_financials(server_url="http://localhost:9901", excel_file_path=None):
    """
    测试财务数据POST请求
    """
    print("=" * 60)
    print("🚀 开始测试财务数据POST请求")
    print("=" * 60)
    
    # 构建API端点URL
    api_url = f"{server_url}/api/economic/data"
    print(f"📡 API端点: {api_url}")
    
    # 设置请求头
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'FinancialDataDebugger/1.0'
    }
    print(f"📋 请求头: {json.dumps(headers, indent=2, ensure_ascii=False)}")
    
    # 检查Excel文件
    if not excel_file_path:
        excel_file_path = "company/理想汽车.xls"
    
    if not os.path.exists(excel_file_path):
        print(f"❌ Excel文件不存在: {excel_file_path}")
        print("请确保文件路径正确，或者提供正确的文件路径")
        return False
    
    print(f"📁 Excel文件路径: {excel_file_path}")
    print(f"📊 文件大小: {os.path.getsize(excel_file_path)} bytes")
    
    # 编码Excel文件
    print("\n🔄 正在编码Excel文件...")
    excel_base64 = encode_excel_to_base64(excel_file_path)
    if not excel_base64:
        return False
    
    print(f"✅ Excel文件编码成功，base64长度: {len(excel_base64)} 字符")
    
    # 构建请求数据
    payload = {
        "data_type": "company_financials",
        "company_code": "LI",
        "company_name": "理想汽车",
        "excel_file_path": excel_file_path,
        "excel_base64_data": excel_base64
    }
    
    print("\n📦 请求数据结构:")
    # 显示payload但不显示完整的base64数据（太长了）
    display_payload = payload.copy()
    if len(display_payload["excel_base64_data"]) > 100:
        display_payload["excel_base64_data"] = display_payload["excel_base64_data"][:100] + "...(truncated)"
    print(json.dumps(display_payload, indent=2, ensure_ascii=False))
    
    # 发送POST请求
    print("\n🌐 发送POST请求...")
    try:
        print(f"⏰ 请求时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        response = requests.post(
            api_url, 
            headers=headers, 
            json=payload, 
            timeout=30  # 30秒超时
        )
        
        print(f"📈 响应状态码: {response.status_code}")
        print(f"📋 响应头: {dict(response.headers)}")
        print(f"⏱️  响应时间: {response.elapsed.total_seconds():.2f}秒")
        
        # 分析响应内容
        print("\n📄 响应内容:")
        try:
            if response.text:
                print(f"原始响应: {response.text[:1000]}{'...' if len(response.text) > 1000 else ''}")
                
                # 尝试解析JSON
                if response.headers.get('content-type', '').startswith('application/json'):
                    result = response.json()
                    print("\n🔍 解析后的JSON响应:")
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                    
                    # 分析响应结果
                    if result.get('code') == 0:
                        print("\n✅ 请求成功!")
                        data = result.get('data', {})
                        print(f"📊 处理记录数: {data.get('total_records', 0)}")
                        print(f"📋 处理工作表: {data.get('processed_sheets', [])}")
                        return True
                    else:
                        print(f"\n❌ 请求失败: {result.get('msg', '未知错误')}")
                        return False
                else:
                    print("\n⚠️  响应不是JSON格式")
                    return False
            else:
                print("\n⚠️  响应内容为空")
                return False
                
        except json.JSONDecodeError as e:
            print(f"\n❌ JSON解析失败: {e}")
            print(f"原始响应内容: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("\n❌ 请求超时 (30秒)")
        return False
    except requests.exceptions.ConnectionError:
        print(f"\n❌ 连接失败，请检查服务器是否运行在 {server_url}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"\n❌ 请求异常: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 未知错误: {e}")
        return False

def test_server_connectivity(server_url="http://localhost:9901"):
    """
    测试服务器连通性
    """
    print("\n🔍 测试服务器连通性...")
    try:
        response = requests.get(f"{server_url}/", timeout=5)
        print(f"✅ 服务器连通性正常 (状态码: {response.status_code})")
        return True
    except Exception as e:
        print(f"❌ 服务器连通性测试失败: {e}")
        return False

def main():
    """
    主函数
    """
    print("🎯 财务数据POST请求调试工具")
    print("=" * 60)
    
    # 解析命令行参数
    server_url = "http://localhost:9901"
    excel_file = None
    
    if len(sys.argv) > 1:
        server_url = sys.argv[1]
    if len(sys.argv) > 2:
        excel_file = sys.argv[2]
    
    print(f"🌐 服务器地址: {server_url}")
    
    # 测试服务器连通性
    if not test_server_connectivity(server_url):
        print("\n💡 提示:")
        print("1. 请确保Flask应用正在运行")
        print("2. 检查服务器地址是否正确")
        print("3. 检查防火墙设置")
        return
    
    # 执行POST测试
    success = test_post_financials(server_url, excel_file)
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 测试完成 - 请求成功!")
    else:
        print("💔 测试完成 - 请求失败")
        print("\n🔧 调试建议:")
        print("1. 检查Flask应用日志")
        print("2. 确认API端点路径正确")
        print("3. 验证请求数据格式")
        print("4. 检查数据库连接")
        print("5. 确认Excel文件格式正确")
    print("=" * 60)

if __name__ == "__main__":
    main()