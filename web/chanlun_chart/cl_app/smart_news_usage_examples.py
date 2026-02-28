#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能新闻搜索系统使用示例

展示如何使用智能新闻搜索系统的各种功能:
1. 直接使用Python模块
2. 通过API接口调用
3. 批量处理示例
4. 集成到现有系统
"""

import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

# 添加当前目录到Python路径
sys.path.append(str(Path(__file__).parent))

try:
    from news_vector_db import NewsVectorDB
    from smart_news_search import SmartNewsSearcher, StockCodeMapper, search_stock_news
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请确保相关模块文件存在于当前目录")
    sys.exit(1)

def example_1_direct_module_usage():
    """
    示例1: 直接使用Python模块
    """
    print("\n" + "="*60)
    print("📚 示例1: 直接使用Python模块")
    print("="*60)
    
    try:
        # 初始化组件
        print("🔧 初始化智能新闻搜索系统...")
        vector_db = NewsVectorDB()
        searcher = SmartNewsSearcher(vector_db)
        mapper = StockCodeMapper()
        
        # 测试股票代码解析
        print("\n🔍 测试股票代码解析:")
        test_inputs = ["R:2015.HK", "理想汽车", "AAPL", "000001"]
        
        for stock_input in test_inputs:
            stock_info = mapper.parse_stock_input(stock_input)
            if stock_info:
                print(f"  ✅ {stock_input} -> {stock_info.name} ({stock_info.code})")
            else:
                print(f"  ❌ {stock_input} -> 无法识别")
        
        # 测试新闻搜索
        print("\n📰 测试新闻搜索:")
        result = searcher.search_news_by_stock(
            stock_input="理想汽车",
            n_results=5,
            days_back=15
        )
        
        if result['success']:
            print(f"  ✅ 搜索成功，找到 {result['total_found']} 条新闻")
            print(f"  🏢 公司: {result['stock_info'].name}")
            print(f"  📊 搜索统计: {result['stats']}")
            
            # 显示前3条新闻标题
            if result['results']:
                print("  📑 前3条新闻:")
                for i, news in enumerate(result['results'][:3], 1):
                    title = news.get('title', '无标题')[:50] + '...' if len(news.get('title', '')) > 50 else news.get('title', '无标题')
                    print(f"    {i}. {title}")
        else:
            print(f"  ❌ 搜索失败: {result.get('error', '未知错误')}")
        
        print("\n✅ 直接模块使用示例完成")
        
    except Exception as e:
        print(f"❌ 示例1执行失败: {e}")

def example_2_api_usage():
    """
    示例2: 通过API接口调用
    """
    print("\n" + "="*60)
    print("🌐 示例2: 通过API接口调用")
    print("="*60)
    
    base_url = "http://localhost:5001/api/smart_news"
    
    try:
        # 健康检查
        print("🏥 检查API服务状态...")
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("  ✅ API服务正常")
        else:
            print("  ❌ API服务异常")
            return
        
        # 股票代码解析API
        print("\n🔍 测试股票代码解析API:")
        parse_data = {"stock_input": "R:2015.HK"}
        response = requests.post(f"{base_url}/parse_stock", json=parse_data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            stock_info = result['data']
            print(f"  ✅ 解析成功: {stock_info['name']} ({stock_info['code']})")
        else:
            print(f"  ❌ 解析失败: {response.status_code}")
        
        # 智能搜索API
        print("\n📰 测试智能搜索API:")
        search_data = {
            "stock_input": "理想汽车",
            "n_results": 10,
            "days_back": 20,
            "include_related": True
        }
        response = requests.post(f"{base_url}/search", json=search_data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            data = result['data']
            print(f"  ✅ 搜索成功，找到 {data['total_found']} 条新闻")
            print(f"  🏢 公司: {data['stock_info']['name']}")
        else:
            print(f"  ❌ 搜索失败: {response.status_code}")
        
        # 快速搜索API
        print("\n⚡ 测试快速搜索API:")
        params = {"n_results": 5, "days_back": 10}
        response = requests.get(f"{base_url}/quick_search/AAPL", params=params, timeout=15)
        
        if response.status_code == 200:
            result = response.json()
            data = result['data']
            print(f"  ✅ 快速搜索成功，找到 {data['total_found']} 条新闻")
        else:
            print(f"  ❌ 快速搜索失败: {response.status_code}")
        
        print("\n✅ API调用示例完成")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API调用失败: {e}")
        print("💡 请确保API服务正在运行 (python smart_news_api.py)")

def example_3_batch_processing():
    """
    示例3: 批量处理示例
    """
    print("\n" + "="*60)
    print("📦 示例3: 批量处理示例")
    print("="*60)
    
    try:
        # 初始化搜索器
        vector_db = NewsVectorDB()
        searcher = SmartNewsSearcher(vector_db)
        
        # 批量搜索的股票列表
        stock_list = [
            "理想汽车",
            "2015.HK", 
            "AAPL",
            "苹果",
            "000001",
            "平安银行",
            "TSLA",
            "特斯拉"
        ]
        
        print(f"🔄 批量处理 {len(stock_list)} 个股票...")
        
        batch_results = []
        
        for i, stock_input in enumerate(stock_list, 1):
            print(f"\n📍 处理第 {i}/{len(stock_list)} 个: {stock_input}")
            
            try:
                result = searcher.search_news_by_stock(
                    stock_input=stock_input,
                    n_results=5,
                    days_back=15,
                    include_related=False  # 批量处理时关闭相关搜索以提高速度
                )
                
                if result['success']:
                    batch_results.append({
                        'input': stock_input,
                        'company': result['stock_info'].name,
                        'code': result['stock_info'].code,
                        'news_count': result['total_found'],
                        'success': True
                    })
                    print(f"  ✅ 成功: {result['stock_info'].name} - {result['total_found']} 条新闻")
                else:
                    batch_results.append({
                        'input': stock_input,
                        'error': result.get('error', '未知错误'),
                        'success': False
                    })
                    print(f"  ❌ 失败: {result.get('error', '未知错误')}")
            
            except Exception as e:
                batch_results.append({
                    'input': stock_input,
                    'error': str(e),
                    'success': False
                })
                print(f"  ❌ 异常: {e}")
        
        # 汇总批量处理结果
        print("\n📊 批量处理结果汇总:")
        successful = [r for r in batch_results if r['success']]
        failed = [r for r in batch_results if not r['success']]
        
        print(f"  ✅ 成功: {len(successful)}/{len(batch_results)}")
        print(f"  ❌ 失败: {len(failed)}/{len(batch_results)}")
        
        if successful:
            total_news = sum(r['news_count'] for r in successful)
            print(f"  📰 总新闻数: {total_news}")
            print(f"  📈 平均每股新闻数: {total_news/len(successful):.1f}")
        
        # 保存批量处理结果
        output_file = f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(batch_results, f, ensure_ascii=False, indent=2)
        print(f"\n💾 结果已保存到: {output_file}")
        
        print("\n✅ 批量处理示例完成")
        
    except Exception as e:
        print(f"❌ 示例3执行失败: {e}")

def example_4_integration_example():
    """
    示例4: 集成到现有系统
    """
    print("\n" + "="*60)
    print("🔗 示例4: 集成到现有系统")
    print("="*60)
    
    class NewsAnalysisSystem:
        """
        模拟的新闻分析系统，展示如何集成智能新闻搜索
        """
        
        def __init__(self):
            self.vector_db = NewsVectorDB()
            self.searcher = SmartNewsSearcher(self.vector_db)
            self.mapper = StockCodeMapper()
        
        def analyze_stock_sentiment(self, stock_input: str, days_back: int = 7) -> Dict[str, Any]:
            """
            分析股票相关新闻的情感倾向
            """
            print(f"🔍 分析股票 {stock_input} 的新闻情感...")
            
            # 搜索相关新闻
            result = self.searcher.search_news_by_stock(
                stock_input=stock_input,
                n_results=20,
                days_back=days_back
            )
            
            if not result['success']:
                return {
                    'success': False,
                    'error': result.get('error', '搜索失败')
                }
            
            # 模拟情感分析 (实际应用中会使用NLP模型)
            news_list = result['results']
            positive_keywords = ['上涨', '增长', '利好', '突破', '创新', '盈利', '成功']
            negative_keywords = ['下跌', '亏损', '风险', '危机', '下滑', '失败', '问题']
            
            sentiment_scores = []
            for news in news_list:
                title = news.get('title', '')
                content = news.get('content', '')
                text = title + ' ' + content
                
                positive_count = sum(1 for keyword in positive_keywords if keyword in text)
                negative_count = sum(1 for keyword in negative_keywords if keyword in text)
                
                if positive_count > negative_count:
                    sentiment_scores.append(1)  # 正面
                elif negative_count > positive_count:
                    sentiment_scores.append(-1)  # 负面
                else:
                    sentiment_scores.append(0)  # 中性
            
            # 计算整体情感
            if sentiment_scores:
                avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
                positive_ratio = sentiment_scores.count(1) / len(sentiment_scores)
                negative_ratio = sentiment_scores.count(-1) / len(sentiment_scores)
                neutral_ratio = sentiment_scores.count(0) / len(sentiment_scores)
            else:
                avg_sentiment = 0
                positive_ratio = negative_ratio = neutral_ratio = 0
            
            return {
                'success': True,
                'stock_info': {
                    'name': result['stock_info'].name,
                    'code': result['stock_info'].code
                },
                'analysis_period': f'{days_back}天',
                'total_news': len(news_list),
                'sentiment_analysis': {
                    'overall_score': avg_sentiment,
                    'positive_ratio': positive_ratio,
                    'negative_ratio': negative_ratio,
                    'neutral_ratio': neutral_ratio
                },
                'recommendation': self._get_recommendation(avg_sentiment)
            }
        
        def _get_recommendation(self, sentiment_score: float) -> str:
            """
            根据情感分数给出建议
            """
            if sentiment_score > 0.3:
                return "积极关注"
            elif sentiment_score < -0.3:
                return "谨慎观望"
            else:
                return "中性观察"
        
        def compare_stocks(self, stock_list: List[str], days_back: int = 7) -> Dict[str, Any]:
            """
            比较多个股票的新闻情感
            """
            print(f"📊 比较 {len(stock_list)} 个股票的新闻情感...")
            
            comparison_results = []
            
            for stock in stock_list:
                analysis = self.analyze_stock_sentiment(stock, days_back)
                if analysis['success']:
                    comparison_results.append({
                        'stock': stock,
                        'name': analysis['stock_info']['name'],
                        'code': analysis['stock_info']['code'],
                        'sentiment_score': analysis['sentiment_analysis']['overall_score'],
                        'news_count': analysis['total_news'],
                        'recommendation': analysis['recommendation']
                    })
            
            # 按情感分数排序
            comparison_results.sort(key=lambda x: x['sentiment_score'], reverse=True)
            
            return {
                'success': True,
                'comparison_results': comparison_results,
                'analysis_period': f'{days_back}天',
                'best_sentiment': comparison_results[0] if comparison_results else None,
                'worst_sentiment': comparison_results[-1] if comparison_results else None
            }
    
    try:
        # 创建分析系统实例
        analysis_system = NewsAnalysisSystem()
        
        # 单股票情感分析
        print("\n📈 单股票情感分析示例:")
        sentiment_result = analysis_system.analyze_stock_sentiment("理想汽车", days_back=10)
        
        if sentiment_result['success']:
            print(f"  🏢 公司: {sentiment_result['stock_info']['name']}")
            print(f"  📰 新闻数量: {sentiment_result['total_news']}")
            print(f"  😊 正面比例: {sentiment_result['sentiment_analysis']['positive_ratio']:.1%}")
            print(f"  😞 负面比例: {sentiment_result['sentiment_analysis']['negative_ratio']:.1%}")
            print(f"  😐 中性比例: {sentiment_result['sentiment_analysis']['neutral_ratio']:.1%}")
            print(f"  💡 建议: {sentiment_result['recommendation']}")
        else:
            print(f"  ❌ 分析失败: {sentiment_result.get('error')}")
        
        # 多股票比较
        print("\n📊 多股票情感比较示例:")
        comparison_stocks = ["理想汽车", "AAPL", "000001"]
        comparison_result = analysis_system.compare_stocks(comparison_stocks, days_back=7)
        
        if comparison_result['success']:
            print("  📋 比较结果 (按情感分数排序):")
            for i, stock in enumerate(comparison_result['comparison_results'], 1):
                print(f"    {i}. {stock['name']} - 分数: {stock['sentiment_score']:.2f} - {stock['recommendation']}")
            
            if comparison_result['best_sentiment']:
                best = comparison_result['best_sentiment']
                print(f"  🏆 最佳情感: {best['name']} (分数: {best['sentiment_score']:.2f})")
        else:
            print("  ❌ 比较失败")
        
        print("\n✅ 系统集成示例完成")
        
    except Exception as e:
        print(f"❌ 示例4执行失败: {e}")

def main():
    """
    主函数，运行所有示例
    """
    print("🚀 智能新闻搜索系统使用示例")
    print("="*60)
    print("本示例展示了智能新闻搜索系统的各种使用方法")
    print("包括直接模块调用、API接口、批量处理和系统集成")
    
    try:
        # 运行所有示例
        example_1_direct_module_usage()
        example_2_api_usage()
        example_3_batch_processing()
        example_4_integration_example()
        
        print("\n" + "="*60)
        print("🎉 所有使用示例执行完成！")
        print("="*60)
        print("\n💡 使用建议:")
        print("1. 对于简单的单次查询，使用直接模块调用")
        print("2. 对于Web应用集成，使用API接口")
        print("3. 对于大量数据处理，使用批量处理方法")
        print("4. 对于复杂业务逻辑，参考系统集成示例")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  示例执行被用户中断")
    except Exception as e:
        print(f"\n\n❌ 示例执行过程中发生异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()