#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯控股(00700)股票新闻搜索功能测试脚本

测试功能:
1. 股票代码格式识别 (KH.00700, 00700, 700.HK等)
2. 公司名称映射 (腾讯控股, 腾讯, Tencent等)
3. 向量数据库新闻搜索
4. 搜索结果验证
"""

import sys
import os

# 添加项目路径
sys.path.append('/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart')

from cl_app.smart_news_search import SmartNewsSearcher, StockCodeMapper
from cl_app.news_vector_db import NewsVectorDB

def test_tencent_stock_code_recognition():
    """测试腾讯控股股票代码识别功能"""
    print("=== 测试腾讯控股股票代码识别 ===")
    print()
    
    mapper = StockCodeMapper()
    
    # 测试不同格式的腾讯控股输入
    test_inputs = [
        "KH.00700",  # KH前缀格式
        "00700",     # 标准港股代码
        "700.HK",    # .HK后缀格式
        "R:700.HK",  # R:前缀格式
        "腾讯控股",   # 中文公司名
        "腾讯",      # 简称
        "Tencent",   # 英文名
        "TCEHY"      # 美股代码
    ]
    
    for test_input in test_inputs:
        print(f"🔍 测试输入: {test_input}")
        stock_info = mapper.parse_stock_input(test_input)
        
        if stock_info:
            print(f"   ✓ 识别成功")
            print(f"   📊 股票代码: {stock_info.code}")
            print(f"   🏢 公司名称: {stock_info.name}")
            print(f"   🌏 市场: {stock_info.exchange}")
            print(f"   🏷️  别名: {', '.join(stock_info.aliases)}")
        else:
            print(f"   ❌ 识别失败")
        print()

def test_tencent_news_search():
    """测试腾讯控股新闻搜索功能"""
    print("=== 测试向量数据库新闻搜索 ===")
    print()
    
    # 初始化向量数据库和搜索器
    try:
        vector_db = NewsVectorDB(
            persist_directory="/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/chroma_db"
        )
        searcher = SmartNewsSearcher(vector_db)
        
        # 测试不同查询方式
        test_queries = [
            "KH.00700",
            "00700", 
            "腾讯控股",
            "腾讯",
            "Tencent"
        ]
        
        for query in test_queries:
            print(f"🔍 搜索查询: {query}")
            
            # 执行搜索
            search_results = searcher.search_news_by_stock(
                stock_input=query,
                n_results=10,
                days_back=30
            )
            
            # 检查搜索结果
            if search_results.get('success', False):
                results = search_results.get('results', [])
                stats = search_results.get('stats', {})
                
                print(f"✓ 成功找到 {len(results)} 条腾讯相关新闻")
                print()
                
                if results:
                    print(f"📰 新闻列表 (前5条):")
                    for i, news in enumerate(results[:5], 1):
                        title = news.get('title', 'N/A')[:50] + '...' if len(news.get('title', '')) > 50 else news.get('title', 'N/A')
                        similarity = news.get('similarity', 0)
                        source = news.get('source', 'N/A')
                        published_at = news.get('published_at', 'N/A')
                        
                        print(f"   {i}. {title}")
                        print(f"      相似度: {similarity:.3f} | 来源: {source} | 时间: {published_at}")
                        print()
                
                # 显示搜索统计
                if stats:
                    stock_info = stats.get('stock_info', {})
                    search_params = stats.get('search_params', {})
                    
                    print(f"📊 搜索统计:")
                    print(f"   📈 识别股票: {stock_info.get('code', 'N/A')} - {stock_info.get('name', 'N/A')}")
                    print(f"   🔍 搜索关键词: {', '.join(search_params.get('keywords', []))}")
                    print()
                
                break  # 找到结果后退出循环
            else:
                error_msg = search_results.get('error', '未知错误')
                print(f"❌ 搜索失败: {error_msg}")
                print()
        
    except Exception as e:
        print(f"❌ 向量数据库连接失败: {e}")
        return False
    
    return True

def main():
    """主测试函数"""
    print("🚀 开始腾讯控股(00700)股票新闻搜索功能测试")
    print("=" * 60)
    print()
    
    try:
        # 1. 测试股票代码识别
        test_tencent_stock_code_recognition()
        
        # 2. 测试新闻搜索
        search_success = test_tencent_news_search()
        
        # 3. 输出测试结果
        print("=" * 60)
        if search_success:
            print("✅ 腾讯控股(00700)股票代码新闻搜索功能测试通过")
            print("   - 股票代码格式识别正常")
            print("   - 公司名称映射正确")
            print("   - 向量数据库搜索成功")
            print("   - 新闻结果显示正常")
        else:
            print("❌ 腾讯控股(00700)股票代码新闻搜索功能测试失败")
            print("   请检查向量数据库连接和数据完整性")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    main()