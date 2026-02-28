#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能新闻搜索API测试脚本

测试所有API端点的功能:
1. 智能新闻搜索
2. 股票代码解析
3. 快速搜索
4. 系统统计
5. 健康检查
"""

import requests
import json
import time
from typing import Dict, Any

# API基础URL
BASE_URL = "http://localhost:5001/api/smart_news"

def test_api_endpoint(method: str, url: str, data: Dict[Any, Any] = None, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    测试API端点的通用函数
    
    Args:
        method: HTTP方法 (GET, POST)
        url: API端点URL
        data: POST请求的JSON数据
        params: GET请求的查询参数
    
    Returns:
        包含响应信息的字典
    """
    try:
        print(f"\n🔍 测试 {method} {url}")
        if data:
            print(f"📤 请求数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
        if params:
            print(f"📤 查询参数: {params}")
        
        start_time = time.time()
        
        if method.upper() == 'POST':
            response = requests.post(url, json=data, timeout=30)
        else:
            response = requests.get(url, params=params, timeout=30)
        
        end_time = time.time()
        response_time = (end_time - start_time) * 1000  # 转换为毫秒
        
        print(f"⏱️  响应时间: {response_time:.2f}ms")
        print(f"📊 状态码: {response.status_code}")
        
        try:
            response_data = response.json()
            print(f"📥 响应数据: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
            
            return {
                'success': response.status_code == 200,
                'status_code': response.status_code,
                'response_time': response_time,
                'data': response_data
            }
        except json.JSONDecodeError:
            print(f"❌ 响应不是有效的JSON: {response.text}")
            return {
                'success': False,
                'status_code': response.status_code,
                'response_time': response_time,
                'error': 'Invalid JSON response'
            }
    
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求异常: {e}")
        return {
            'success': False,
            'error': str(e)
        }

def test_health_check():
    """
    测试健康检查API
    """
    print("\n" + "="*50)
    print("🏥 测试健康检查API")
    print("="*50)
    
    result = test_api_endpoint('GET', f"{BASE_URL}/health")
    
    if result['success']:
        print("✅ 健康检查测试通过")
        return True
    else:
        print("❌ 健康检查测试失败")
        return False

def test_stats_api():
    """
    测试系统统计API
    """
    print("\n" + "="*50)
    print("📊 测试系统统计API")
    print("="*50)
    
    result = test_api_endpoint('GET', f"{BASE_URL}/stats")
    
    if result['success']:
        data = result['data']['data']
        print(f"✅ 统计信息获取成功:")
        print(f"   📰 总新闻数: {data.get('total_news', 0)}")
        print(f"   🏢 支持股票数: {data.get('supported_stocks', 0)}")
        print(f"   🌍 支持市场: {data.get('supported_markets', [])}")
        return True
    else:
        print("❌ 系统统计测试失败")
        return False

def test_parse_stock_api():
    """
    测试股票代码解析API
    """
    print("\n" + "="*50)
    print("🔍 测试股票代码解析API")
    print("="*50)
    
    test_cases = [
        "R:2015.HK",
        "2015.HK", 
        "2015",
        "理想汽车",
        "AAPL",
        "苹果",
        "000001",
        "平安银行"
    ]
    
    success_count = 0
    
    for stock_input in test_cases:
        print(f"\n🧪 测试输入: {stock_input}")
        
        result = test_api_endpoint(
            'POST', 
            f"{BASE_URL}/parse_stock",
            data={'stock_input': stock_input}
        )
        
        if result['success']:
            stock_info = result['data']['data']
            print(f"✅ 解析成功: {stock_info['name']} ({stock_info['code']})")
            success_count += 1
        else:
            print(f"❌ 解析失败: {result['data'].get('error', '未知错误')}")
    
    print(f"\n📊 股票代码解析测试结果: {success_count}/{len(test_cases)} 成功")
    return success_count > 0

def test_quick_search_api():
    """
    测试快速搜索API
    """
    print("\n" + "="*50)
    print("⚡ 测试快速搜索API")
    print("="*50)
    
    test_cases = [
        {
            'stock_input': '理想汽车',
            'params': {'n_results': 5, 'days_back': 15}
        },
        {
            'stock_input': '2015.HK',
            'params': {'n_results': 3, 'days_back': 7}
        },
        {
            'stock_input': 'AAPL',
            'params': {'n_results': 5, 'days_back': 10}
        }
    ]
    
    success_count = 0
    
    for test_case in test_cases:
        stock_input = test_case['stock_input']
        params = test_case['params']
        
        print(f"\n🧪 测试快速搜索: {stock_input}")
        
        result = test_api_endpoint(
            'GET',
            f"{BASE_URL}/quick_search/{stock_input}",
            params=params
        )
        
        if result['success']:
            data = result['data']['data']
            total_found = data.get('total_found', 0)
            print(f"✅ 快速搜索成功，找到 {total_found} 条新闻")
            success_count += 1
        else:
            print(f"❌ 快速搜索失败: {result['data'].get('error', '未知错误')}")
    
    print(f"\n📊 快速搜索测试结果: {success_count}/{len(test_cases)} 成功")
    return success_count > 0

def test_search_api():
    """
    测试智能新闻搜索API
    """
    print("\n" + "="*50)
    print("🔍 测试智能新闻搜索API")
    print("="*50)
    
    test_cases = [
        {
            'stock_input': 'R:2015.HK',
            'n_results': 10,
            'days_back': 30,
            'include_related': True
        },
        {
            'stock_input': '理想汽车',
            'n_results': 15,
            'days_back': 15,
            'include_related': True
        },
        {
            'stock_input': 'AAPL',
            'n_results': 8,
            'days_back': 20,
            'include_related': False
        },
        {
            'stock_input': '000001',
            'n_results': 5,
            'days_back': 10,
            'include_related': True
        }
    ]
    
    success_count = 0
    
    for test_case in test_cases:
        print(f"\n🧪 测试搜索: {test_case['stock_input']}")
        
        result = test_api_endpoint(
            'POST',
            f"{BASE_URL}/search",
            data=test_case
        )
        
        if result['success']:
            data = result['data']['data']
            stock_info = data.get('stock_info', {})
            total_found = data.get('total_found', 0)
            
            print(f"✅ 搜索成功:")
            print(f"   🏢 公司: {stock_info.get('name', 'N/A')} ({stock_info.get('code', 'N/A')})")
            print(f"   📰 找到新闻: {total_found} 条")
            print(f"   🏛️ 交易所: {stock_info.get('exchange', 'N/A')}")
            
            success_count += 1
        else:
            print(f"❌ 搜索失败: {result['data'].get('error', '未知错误')}")
    
    print(f"\n📊 智能搜索测试结果: {success_count}/{len(test_cases)} 成功")
    return success_count > 0

def test_error_handling():
    """
    测试错误处理
    """
    print("\n" + "="*50)
    print("⚠️  测试错误处理")
    print("="*50)
    
    error_test_cases = [
        {
            'name': '空请求体',
            'method': 'POST',
            'url': f"{BASE_URL}/search",
            'data': None
        },
        {
            'name': '缺少必需参数',
            'method': 'POST',
            'url': f"{BASE_URL}/search",
            'data': {'n_results': 10}
        },
        {
            'name': '无效的结果数量',
            'method': 'POST',
            'url': f"{BASE_URL}/search",
            'data': {'stock_input': '理想汽车', 'n_results': 200}
        },
        {
            'name': '不存在的端点',
            'method': 'GET',
            'url': f"{BASE_URL}/nonexistent",
            'data': None
        }
    ]
    
    success_count = 0
    
    for test_case in error_test_cases:
        print(f"\n🧪 测试错误情况: {test_case['name']}")
        
        result = test_api_endpoint(
            test_case['method'],
            test_case['url'],
            data=test_case['data']
        )
        
        # 错误处理测试期望返回错误状态
        if not result['success'] and result.get('status_code', 0) >= 400:
            print(f"✅ 错误处理正确")
            success_count += 1
        else:
            print(f"❌ 错误处理异常")
    
    print(f"\n📊 错误处理测试结果: {success_count}/{len(error_test_cases)} 成功")
    return success_count > 0

def run_performance_test():
    """
    运行性能测试
    """
    print("\n" + "="*50)
    print("⚡ 性能测试")
    print("="*50)
    
    test_data = {
        'stock_input': '理想汽车',
        'n_results': 20,
        'days_back': 30,
        'include_related': True
    }
    
    response_times = []
    success_count = 0
    
    print("🔄 执行10次搜索请求...")
    
    for i in range(10):
        print(f"\n📍 第 {i+1} 次请求")
        
        result = test_api_endpoint(
            'POST',
            f"{BASE_URL}/search",
            data=test_data
        )
        
        if result['success']:
            response_times.append(result['response_time'])
            success_count += 1
            print(f"✅ 请求成功，响应时间: {result['response_time']:.2f}ms")
        else:
            print(f"❌ 请求失败")
    
    if response_times:
        avg_time = sum(response_times) / len(response_times)
        min_time = min(response_times)
        max_time = max(response_times)
        
        print(f"\n📊 性能测试结果:")
        print(f"   ✅ 成功率: {success_count}/10 ({success_count*10}%)")
        print(f"   ⏱️  平均响应时间: {avg_time:.2f}ms")
        print(f"   ⚡ 最快响应时间: {min_time:.2f}ms")
        print(f"   🐌 最慢响应时间: {max_time:.2f}ms")
        
        return avg_time < 5000  # 期望平均响应时间小于5秒
    else:
        print("❌ 性能测试失败，没有成功的请求")
        return False

def main():
    """
    主测试函数
    """
    print("🚀 智能新闻搜索API测试开始")
    print("="*60)
    
    # 等待API服务启动
    print("⏳ 等待API服务启动...")
    time.sleep(2)
    
    test_results = []
    
    # 执行各项测试
    test_results.append(('健康检查', test_health_check()))
    test_results.append(('系统统计', test_stats_api()))
    test_results.append(('股票代码解析', test_parse_stock_api()))
    test_results.append(('快速搜索', test_quick_search_api()))
    test_results.append(('智能搜索', test_search_api()))
    test_results.append(('错误处理', test_error_handling()))
    test_results.append(('性能测试', run_performance_test()))
    
    # 汇总测试结果
    print("\n" + "="*60)
    print("📊 测试结果汇总")
    print("="*60)
    
    passed_tests = 0
    total_tests = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name:15} : {status}")
        if result:
            passed_tests += 1
    
    print(f"\n🎯 总体结果: {passed_tests}/{total_tests} 测试通过 ({passed_tests/total_tests*100:.1f}%)")
    
    if passed_tests == total_tests:
        print("🎉 所有测试通过！智能新闻搜索API功能正常")
    else:
        print("⚠️  部分测试失败，请检查API实现")
    
    return passed_tests == total_tests

if __name__ == '__main__':
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏹️  测试被用户中断")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ 测试过程中发生异常: {e}")
        exit(1)