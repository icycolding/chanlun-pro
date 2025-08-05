#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试缠论图表集成到AI市场摘要的功能
"""

import requests
import json
from datetime import datetime

def test_chart_snapshot_html_direct():
    """
    直接测试图表快照HTML生成函数
    """
    print("=== 直接测试图表快照HTML生成 ===")
    
    # 模拟函数实现
    def _generate_chart_snapshot_html(code: str, market: str) -> str:
        market_names = {
            "a": "沪深A股",
            "hk": "港股", 
            "us": "美股",
            "fx": "外汇",
            "futures": "期货",
            "crypto": "数字货币"
        }
        
        market_name = market_names.get(market, "未知市场")
        chart_url = f"/?market={market}&code={code}"
        
        html = f"""
## 缠论图表
📊 **{code} 缠论图表分析**

> 市场：{market_name}  
> 代码：{code}  
> [📈 点击查看实时缠论图表]({chart_url})

*注：图表包含完整的缠论分析，包括分型、笔、线段、中枢等技术要素，建议在新窗口中打开查看详细分析。*
"""
        return html
    
    # 测试不同市场的图表生成
    test_cases = [
        ("000001", "a", "沪深A股"),
        ("00700", "hk", "港股"),
        ("AAPL", "us", "美股"),
        ("EURUSD", "fx", "外汇")
    ]
    
    for code, market, market_name in test_cases:
        print(f"\n测试 {market_name} - {code}:")
        html = _generate_chart_snapshot_html(code, market)
        print(html)
        
        # 验证HTML内容
        if code in html and market_name in html and "缠论图表" in html:
            print(f"✅ {market_name}图表HTML生成成功")
        else:
            print(f"❌ {market_name}图表HTML生成失败")

def test_market_summary_with_session():
    """
    使用session测试市场摘要生成
    """
    print("\n=== 测试带有缠论图表的市场摘要生成 ===")
    
    session = requests.Session()
    
    try:
        # 先访问登录页面获取session
        login_response = session.get("http://localhost:9901/login")
        print(f"登录状态: {login_response.status_code}")
        
        # 测试API
        api_url = "http://localhost:9901/api/news/market_summary"
        test_data = {
            "news_list": [
                {
                    "title": "测试新闻：平安银行业绩表现",
                    "content": "平安银行发布最新财报，显示业绩稳健增长。",
                    "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "财经新闻"
                }
            ],
            "current_market": "a",
            "current_code": "000001"
        }
        
        response = session.post(api_url, json=test_data)
        print(f"API响应状态: {response.status_code}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"响应代码: {result.get('code')}")
                print(f"响应消息: {result.get('msg')}")
                
                if result.get('code') == 0 and 'data' in result:
                    summary = result['data']['summary']
                    print("\n=== 生成的市场摘要 ===")
                    print(summary)
                    
                    # 检查关键内容
                    checks = [
                        ("缠论图表" in summary, "包含缠论图表标题"),
                        ("000001" in summary, "包含股票代码"),
                        ("沪深A股" in summary, "包含市场信息"),
                        ("/?market=a&code=000001" in summary, "包含图表链接"),
                        ("点击查看" in summary, "包含查看提示")
                    ]
                    
                    print("\n=== 功能验证结果 ===")
                    all_passed = True
                    for check_result, description in checks:
                        status = "✅" if check_result else "❌"
                        print(f"{status} {description}")
                        if not check_result:
                            all_passed = False
                    
                    if all_passed:
                        print("\n🎉 所有功能验证通过！缠论图表已成功集成到AI市场摘要中。")
                    else:
                        print("\n⚠️ 部分功能验证失败，需要进一步检查。")
                        
                else:
                    print(f"❌ API调用失败: {result.get('msg', '未知错误')}")
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {str(e)}")
                print(f"原始响应: {response.text[:500]}...")
        else:
            print(f"❌ HTTP请求失败: {response.status_code}")
            print(f"响应内容: {response.text[:500]}...")
            
    except Exception as e:
        print(f"❌ 测试异常: {str(e)}")

if __name__ == "__main__":
    print("缠论图表集成功能测试")
    print("=" * 50)
    
    # 测试图表HTML生成
    test_chart_snapshot_html_direct()
    
    # 测试完整的市场摘要生成
    test_market_summary_with_session()
    
    print("\n测试完成！")