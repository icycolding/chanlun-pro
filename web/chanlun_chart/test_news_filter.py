#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试新闻筛选功能
"""

import sys
import os
import requests
import json
from datetime import datetime

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'web', 'chanlun_chart'))

def test_news_filter_function():
    """
    直接测试新闻筛选函数
    """
    print("\n=== 测试新闻筛选函数 ===")
    
    try:
        # 导入筛选函数
        from cl_app.news_vector_api import _filter_financial_news
        
        # 创建测试新闻数据
        test_news = [
            {
                'title': '美联储加息决议公布，美元汇率大涨',
                'content': '美联储宣布加息25个基点，美元兑欧元汇率上涨1.2%',
                'body': '央行货币政策对外汇市场产生重大影响',
                'category': 'finance',
                'source': 'Reuters'
            },
            {
                'title': '苹果公司发布新款iPhone',
                'content': '苹果公司今日发布了最新的iPhone 15系列手机',
                'body': '新手机配备了更先进的摄像头和处理器',
                'category': 'technology',
                'source': 'TechNews'
            },
            {
                'title': '中国股市今日收盘上涨2.5%',
                'content': '上证指数收盘报3250点，涨幅2.5%，成交量放大',
                'body': '银行股和科技股领涨，市场情绪乐观',
                'category': 'stock',
                'source': 'Financial Times'
            },
            {
                'title': '好莱坞明星获得奥斯卡奖',
                'content': '著名演员在昨晚的奥斯卡颁奖典礼上获得最佳男主角奖',
                'body': '这是他第一次获得奥斯卡奖项',
                'category': 'entertainment',
                'source': 'Entertainment Weekly'
            },
            {
                'title': 'Bitcoin价格突破50000美元',
                'content': '比特币价格今日突破50000美元大关，创近期新高',
                'body': '加密货币市场整体上涨，以太坊也涨幅明显',
                'category': 'crypto',
                'source': 'CoinDesk'
            },
            {
                'title': '足球世界杯决赛结果',
                'content': '世界杯决赛昨晚结束，阿根廷队夺得冠军',
                'body': '梅西终于实现了世界杯冠军的梦想',
                'category': 'sports',
                'source': 'ESPN'
            },
            {
                'title': '美国国债收益率上升至4.5%',
                'content': '10年期美国国债收益率升至4.5%，创15年新高',
                'body': '债券市场受到通胀预期和加息影响',
                'category': 'bond',
                'source': 'Bloomberg'
            },
            {
                'title': '天气预报：明日有雨',
                'content': '气象部门预报明日将有中到大雨',
                'body': '市民出行请注意携带雨具',
                'category': 'weather',
                'source': 'Weather Channel'
            }
        ]
        
        print(f"原始新闻数量: {len(test_news)}")
        print("\n原始新闻列表:")
        for i, news in enumerate(test_news, 1):
            print(f"{i}. {news['title']} ({news['category']})")
        
        # 执行筛选
        filtered_news = _filter_financial_news(test_news)
        
        print(f"\n筛选后新闻数量: {len(filtered_news)}")
        print("\n筛选后新闻列表:")
        for i, news in enumerate(filtered_news, 1):
            print(f"{i}. {news['title']} ({news['category']})")
        
        # 验证筛选结果
        expected_financial_news = [
            '美联储加息决议公布，美元汇率大涨',
            '中国股市今日收盘上涨2.5%',
            'Bitcoin价格突破50000美元',
            '美国国债收益率上升至4.5%'
        ]
        
        filtered_titles = [news['title'] for news in filtered_news]
        
        print("\n=== 筛选结果验证 ===")
        success_count = 0
        for expected_title in expected_financial_news:
            if expected_title in filtered_titles:
                print(f"✅ 正确保留: {expected_title}")
                success_count += 1
            else:
                print(f"❌ 错误过滤: {expected_title}")
        
        # 检查是否错误保留了非金融新闻
        non_financial_titles = [
            '苹果公司发布新款iPhone',
            '好莱坞明星获得奥斯卡奖',
            '足球世界杯决赛结果',
            '天气预报：明日有雨'
        ]
        
        for non_financial_title in non_financial_titles:
            if non_financial_title in filtered_titles:
                print(f"❌ 错误保留: {non_financial_title}")
            else:
                print(f"✅ 正确过滤: {non_financial_title}")
                success_count += 1
        
        total_tests = len(expected_financial_news) + len(non_financial_titles)
        print(f"\n筛选准确率: {success_count}/{total_tests} ({success_count/total_tests*100:.1f}%)")
        
        return success_count == total_tests
        
    except Exception as e:
        print(f"测试筛选函数失败: {str(e)}")
        return False

def test_daily_news_summary_api():
    """
    测试每日新闻总结API
    """
    print("\n=== 测试每日新闻总结API ===")
    
    # API配置
    base_url = "http://127.0.0.1:9900"
    api_url = f"{base_url}/api/news/daily_summary"
    
    # 测试数据
    test_data = {
        "days": 1
    }
    
    try:
        print(f"发送请求到: {api_url}")
        print(f"请求数据: {json.dumps(test_data, indent=2)}")
        
        # 发送请求
        response = requests.post(
            api_url,
            json=test_data,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"响应结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            if result.get('code') == 0:
                data = result.get('data', {})
                summary = data.get('summary', '')
                news_count = data.get('news_count', 0)
                
                print(f"\n✅ API调用成功")
                print(f"📊 处理新闻数量: {news_count}")
                print(f"📝 总结长度: {len(summary)} 字符")
                print(f"📄 总结预览: {summary[:200]}...")
                
                return True
            else:
                print(f"❌ API返回错误: {result.get('msg')}")
                return False
        else:
            print(f"❌ HTTP请求失败: {response.status_code}")
            print(f"响应内容: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败: 请确保Web服务器正在运行 (python run_web.py)")
        return False
    except Exception as e:
        print(f"❌ 测试API失败: {str(e)}")
        return False

def main():
    """
    主测试函数
    """
    print("🧪 新闻筛选功能测试")
    print("=" * 50)
    
    # 测试筛选函数
    filter_test_passed = test_news_filter_function()
    
    # 测试API（可选）
    print("\n" + "=" * 50)
    print("💡 提示: 如果要测试API，请先启动Web服务器:")
    print("   cd /Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart")
    print("   python run_web.py")
    
    user_input = input("\n是否测试API? (y/n): ").strip().lower()
    if user_input == 'y':
        api_test_passed = test_daily_news_summary_api()
    else:
        api_test_passed = True
        print("跳过API测试")
    
    # 总结测试结果
    print("\n" + "=" * 50)
    print("📋 测试结果总结:")
    print(f"🔍 筛选函数测试: {'✅ 通过' if filter_test_passed else '❌ 失败'}")
    print(f"🌐 API测试: {'✅ 通过' if api_test_passed else '❌ 失败'}")
    
    if filter_test_passed and api_test_passed:
        print("\n🎉 所有测试通过！新闻筛选功能工作正常。")
    else:
        print("\n⚠️  部分测试失败，请检查相关功能。")

if __name__ == "__main__":
    main()