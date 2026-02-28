#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能新闻搜索系统测试脚本

测试功能:
1. 股票代码解析和映射
2. 新闻搜索功能
3. 多种输入格式的支持
4. 搜索结果的准确性和相关性
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.append(str(Path(__file__).parent.parent.parent))
sys.path.append(str(Path(__file__).parent))

from news_vector_db import NewsVectorDB
from smart_news_search import SmartNewsSearcher, StockCodeMapper, search_stock_news

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_stock_code_mapping():
    """测试股票代码映射功能"""
    print("\n" + "="*60)
    print("🧪 测试股票代码映射功能")
    print("="*60)
    
    mapper = StockCodeMapper()
    
    # 测试用例
    test_cases = [
        "R:2015.HK",  # 理想汽车 - 完整格式
        "2015.HK",    # 理想汽车 - 标准港股格式
        "2015",       # 理想汽车 - 简化格式
        "02015",      # 理想汽车 - 5位格式
        "理想汽车",    # 理想汽车 - 中文名称
        "Li Auto",    # 理想汽车 - 英文名称
        "0700",       # 腾讯控股
        "00700",      # 腾讯控股 - 5位格式
        "腾讯",       # 腾讯控股 - 简化中文名
        "TSLA",       # 特斯拉 - 美股
        "特斯拉",      # 特斯拉 - 中文名
        "AAPL",       # 苹果 - 美股
        "000001",     # 平安银行 - A股
        "INVALID",    # 无效输入
        "",           # 空输入
    ]
    
    for i, test_input in enumerate(test_cases, 1):
        print(f"\n📝 测试 {i}: '{test_input}'")
        try:
            stock_info = mapper.parse_stock_input(test_input)
            if stock_info:
                print(f"  ✅ 解析成功:")
                print(f"     代码: {stock_info.code}")
                print(f"     名称: {stock_info.name}")
                print(f"     交易所: {stock_info.exchange}")
                print(f"     市场: {stock_info.market_type}")
                print(f"     别名: {stock_info.aliases[:3]}...")  # 只显示前3个别名
            else:
                print(f"  ❌ 解析失败: 无法识别股票代码或公司名称")
        except Exception as e:
            print(f"  💥 解析异常: {e}")

def test_news_search():
    """测试新闻搜索功能"""
    print("\n" + "="*60)
    print("🔍 测试新闻搜索功能")
    print("="*60)
    
    try:
        # 初始化向量数据库
        print("📊 初始化向量数据库...")
        vector_db = NewsVectorDB()
        
        # 检查数据库状态
        if vector_db.collection is None:
            print("❌ 向量数据库未初始化，跳过新闻搜索测试")
            return
        
        # 获取数据库统计信息
        try:
            total_count = vector_db.collection.count()
            print(f"📈 数据库中共有 {total_count} 条新闻数据")
            
            if total_count == 0:
                print("⚠️ 数据库为空，跳过新闻搜索测试")
                return
        except Exception as e:
            print(f"⚠️ 无法获取数据库统计信息: {e}")
        
        # 创建智能搜索器
        searcher = SmartNewsSearcher(vector_db)
        
        # 测试搜索用例
        search_test_cases = [
            {
                "input": "R:2015.HK",
                "description": "理想汽车 - 完整股票代码格式",
                "expected_keywords": ["理想汽车", "Li Auto"]
            },
            {
                "input": "理想汽车",
                "description": "理想汽车 - 中文公司名称",
                "expected_keywords": ["理想汽车", "Li Auto"]
            },
            {
                "input": "腾讯",
                "description": "腾讯控股 - 简化中文名",
                "expected_keywords": ["腾讯", "Tencent"]
            },
            {
                "input": "TSLA",
                "description": "特斯拉 - 美股代码",
                "expected_keywords": ["特斯拉", "Tesla"]
            }
        ]
        
        for i, test_case in enumerate(search_test_cases, 1):
            print(f"\n🔍 搜索测试 {i}: {test_case['description']}")
            print(f"   输入: '{test_case['input']}'")
            
            try:
                # 执行搜索
                result = searcher.search_news_by_stock(
                    stock_input=test_case['input'],
                    n_results=10,
                    days_back=30,
                    include_related=True
                )
                
                if result['success']:
                    print(f"   ✅ 搜索成功: 找到 {result['total_found']} 条相关新闻")
                    
                    # 显示股票信息
                    stock_info = result['stock_info']
                    print(f"   📊 股票信息: {stock_info.name} ({stock_info.code})")
                    
                    # 显示搜索统计
                    stats = result['stats']
                    search_results = stats.get('search_results', {})
                    for search_type, search_info in search_results.items():
                        if 'found' in search_info:
                            print(f"   📈 {search_type}: {search_info['found']} 条结果")
                    
                    # 显示前几条新闻标题
                    if result['results']:
                        print(f"   📰 前3条新闻标题:")
                        for j, news in enumerate(result['results'][:3], 1):
                            title = news.get('metadata', {}).get('title', '无标题')[:50]
                            score = news.get('score', 0)
                            print(f"      {j}. {title}... (相关度: {score:.3f})")
                    
                    # 分析新闻来源
                    final_stats = stats.get('final_stats', {})
                    sources = final_stats.get('sources', {})
                    if sources:
                        print(f"   📊 新闻来源分布: {dict(list(sources.items())[:3])}")
                    
                else:
                    print(f"   ❌ 搜索失败: {result.get('error', '未知错误')}")
                    
            except Exception as e:
                print(f"   💥 搜索异常: {e}")
                logger.exception(f"搜索测试异常: {test_case['input']}")
    
    except Exception as e:
        print(f"💥 新闻搜索测试初始化失败: {e}")
        logger.exception("新闻搜索测试异常")

def test_convenience_function():
    """测试便捷搜索函数"""
    print("\n" + "="*60)
    print("🚀 测试便捷搜索函数")
    print("="*60)
    
    try:
        # 初始化向量数据库
        vector_db = NewsVectorDB()
        
        if vector_db.collection is None:
            print("❌ 向量数据库未初始化，跳过便捷函数测试")
            return
        
        # 测试便捷函数
        test_input = "理想汽车"
        print(f"🔍 使用便捷函数搜索: '{test_input}'")
        
        result = search_stock_news(
            stock_input=test_input,
            vector_db=vector_db,
            n_results=5,
            days_back=15
        )
        
        if result['success']:
            print(f"✅ 便捷函数搜索成功: 找到 {result['total_found']} 条相关新闻")
            
            # 显示简化的结果信息
            if result['results']:
                print(f"📰 新闻标题预览:")
                for i, news in enumerate(result['results'][:2], 1):
                    title = news.get('metadata', {}).get('title', '无标题')[:60]
                    print(f"  {i}. {title}...")
        else:
            print(f"❌ 便捷函数搜索失败: {result.get('error', '未知错误')}")
            
    except Exception as e:
        print(f"💥 便捷函数测试异常: {e}")
        logger.exception("便捷函数测试异常")

def performance_test():
    """性能测试"""
    print("\n" + "="*60)
    print("⚡ 性能测试")
    print("="*60)
    
    try:
        vector_db = NewsVectorDB()
        
        if vector_db.collection is None:
            print("❌ 向量数据库未初始化，跳过性能测试")
            return
        
        searcher = SmartNewsSearcher(vector_db)
        
        # 性能测试用例
        test_cases = ["理想汽车", "腾讯", "TSLA", "2015"]
        
        print(f"🏃‍♂️ 开始性能测试，测试 {len(test_cases)} 个搜索查询...")
        
        start_time = datetime.now()
        
        for i, test_input in enumerate(test_cases, 1):
            case_start = datetime.now()
            
            result = searcher.search_news_by_stock(
                stock_input=test_input,
                n_results=10,
                days_back=30
            )
            
            case_end = datetime.now()
            case_duration = (case_end - case_start).total_seconds()
            
            status = "✅" if result['success'] else "❌"
            found = result.get('total_found', 0)
            
            print(f"  {status} 测试 {i}: '{test_input}' - {found} 条结果 - {case_duration:.2f}s")
        
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        avg_duration = total_duration / len(test_cases)
        
        print(f"\n📊 性能测试结果:")
        print(f"   总耗时: {total_duration:.2f}s")
        print(f"   平均耗时: {avg_duration:.2f}s/查询")
        print(f"   查询速度: {1/avg_duration:.1f} 查询/秒")
        
    except Exception as e:
        print(f"💥 性能测试异常: {e}")
        logger.exception("性能测试异常")

def main():
    """主测试函数"""
    print("🚀 智能新闻搜索系统测试开始")
    print(f"⏰ 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # 1. 测试股票代码映射
        test_stock_code_mapping()
        
        # 2. 测试新闻搜索
        test_news_search()
        
        # 3. 测试便捷函数
        test_convenience_function()
        
        # 4. 性能测试
        performance_test()
        
        print("\n" + "="*60)
        print("🎉 所有测试完成!")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n⚠️ 测试被用户中断")
    except Exception as e:
        print(f"\n💥 测试过程中发生异常: {e}")
        logger.exception("主测试函数异常")

if __name__ == "__main__":
    main()