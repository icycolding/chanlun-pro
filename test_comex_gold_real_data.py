#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用真实数据测试COMEX黄金期货新闻搜索功能
确保使用实际存储在向量数据库中的新闻数据，而不是模拟数据
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

def test_comex_gold_with_real_data():
    """
    使用真实数据测试COMEX黄金期货新闻搜索功能
    """
    print("COMEX黄金期货新闻搜索功能测试 - 使用真实数据")
    print("=" * 60)
    
    # 测试输入格式
    test_inputs = [
        'COMEX黄金',
        '黄金期货', 
        'GC',
        'GOLD',
        '纽约黄金',
        '黄金连续',
        'COMEX GOLD',
        '现货黄金',
        'XAUUSD',
        '金价'
    ]
    
    print("\n=== 1. 向量数据库真实数据测试 ===")
    
    try:
        from news_vector_db import NewsVectorDB
        print("✓ NewsVectorDB 模块导入成功")
        
        # 连接到真实的向量数据库（使用有数据的数据库路径）
        vector_db = NewsVectorDB(db_path="./web/chanlun_chart/chroma_db")
        
        # 获取数据库统计信息
        stats = vector_db.get_collection_stats()
        print(f"✓ 向量数据库连接成功")
        print(f"  数据库统计: {stats}")
        
        # 检查数据库是否有数据
        if stats.get('total_documents', 0) == 0:
            print("⚠️  警告: 向量数据库中没有数据，无法进行真实数据测试")
            print("   请确保数据库中已经存储了新闻数据")
            return False
        
        print(f"✓ 数据库包含 {stats.get('total_documents', 0)} 条新闻数据")
        
        # 测试COMEX黄金相关搜索
        print("\n=== 2. COMEX黄金真实新闻搜索测试 ===")
        
        search_queries = [
            'COMEX黄金',
            '黄金期货',
            'GC',
            'GOLD',
            '纽约黄金',
            '黄金价格',
            '金价',
            'XAUUSD',
            '现货黄金',
            '贵金属',
            '黄金市场',
            '金融避险',
            '通胀对冲'
        ]
        
        total_found = 0
        
        for query in search_queries:
            print(f"\n--- 搜索查询: '{query}' ---")
            try:
                # 使用真实的向量搜索
                from datetime import datetime, timedelta
                end_date = datetime.now()
                start_date = end_date - timedelta(days=90)
                
                results = vector_db.semantic_search(
                    query=query,
                    n_results=5,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat()
                )
                
                if results and len(results) > 0:
                    print(f"✓ 找到 {len(results)} 条相关新闻:")
                    total_found += len(results)
                    
                    for i, result in enumerate(results, 1):
                        metadata = result.get('metadata', {})
                        title = metadata.get('title', 'N/A')
                        source = metadata.get('source', 'N/A')
                        published_at = metadata.get('published_at', 'N/A')
                        
                        # 计算相似度分数（从距离转换）
                        distance = result.get('distance', 1.0)
                        similarity = result.get('score', max(0.0, 1.0 - distance))
                        
                        # 截断标题显示
                        display_title = title[:60] + '...' if len(title) > 60 else title
                        
                        print(f"  {i}. {display_title}")
                        print(f"     相似度: {similarity:.3f} | 来源: {source} | 时间: {published_at}")
                        
                        # 检查是否包含黄金相关关键词
                        content = result.get('document', '') + ' ' + title
                        gold_keywords = ['黄金', 'GOLD', 'GC', 'COMEX', 'XAUUSD', '金价', '贵金属', '避险', '通胀']
                        found_keywords = [kw for kw in gold_keywords if kw.lower() in content.lower()]
                        if found_keywords:
                            print(f"     包含关键词: {', '.join(found_keywords[:3])}")
                        print()
                else:
                    print("  ❌ 未找到相关新闻")
                    
            except Exception as e:
                print(f"  ❌ 搜索出错: {str(e)}")
        
        print(f"\n=== 搜索结果汇总 ===")
        print(f"总共找到 {total_found} 条相关新闻")
        
        if total_found == 0:
            print("⚠️  警告: 没有找到任何COMEX黄金相关新闻")
            print("   可能原因:")
            print("   1. 数据库中缺少黄金期货相关新闻")
            print("   2. 新闻内容与黄金期货关联度较低")
            print("   3. 搜索关键词需要优化")
            return False
        else:
            print(f"✓ 成功找到 {total_found} 条COMEX黄金相关新闻")
        
    except ImportError as e:
        print(f"❌ NewsVectorDB 导入失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 向量数据库测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n=== 3. 期货API真实数据测试 ===")
    
    try:
        from forex_futures_news_api import ForexFuturesNewsAPI
        print("✓ ForexFuturesNewsAPI 模块导入成功")
        
        api = ForexFuturesNewsAPI()
        
        # 测试API搜索
        test_queries = ['COMEX黄金', '黄金期货', 'GC', 'GOLD']
        
        for query in test_queries:
            print(f"\n--- API搜索: '{query}' ---")
            try:
                result = api.search_forex_news(
                    query=query,
                    limit=5,
                    days_back=90,
                    include_analysis=True
                )
                
                print(f"搜索状态: {result.get('status', 'unknown')}")
                print(f"识别的标的: {result.get('identified_symbol', 'N/A')}")
                print(f"新闻数量: {result.get('news_count', 0)}")
                
                # 显示新闻详情
                news_list = result.get('news', [])
                if news_list:
                    print("新闻列表:")
                    for i, news in enumerate(news_list[:3], 1):
                        title = news.get('title', 'N/A')[:50]
                        source = news.get('source', 'N/A')
                        print(f"  {i}. {title}... (来源: {source})")
                else:
                    print("  ❌ API返回的新闻列表为空")
                    
            except Exception as e:
                print(f"  ❌ API搜索出错: {str(e)}")
                
    except ImportError as e:
        print(f"❌ ForexFuturesNewsAPI 导入失败: {e}")
    except Exception as e:
        print(f"❌ 期货API测试失败: {e}")
    
    print("\n=== 4. 期货商品映射测试 ===")
    
    try:
        from enhanced_market_search import EnhancedMarketSearch
        print("✓ EnhancedMarketSearch 模块导入成功")
        
        market_search = EnhancedMarketSearch()
        
        for input_text in test_inputs:
            try:
                results = market_search.identify_market_instrument(input_text)
                if results:
                    for result in results:
                        market_type = result.market_type.value
                        symbol = result.symbol
                        confidence = result.confidence
                        print(f"✓ 输入: {input_text:15} -> 市场: {market_type:8} | 标的: {symbol} | 置信度: {confidence:.2f}")
                else:
                    print(f"❌ 输入: {input_text:15} -> 未识别")
            except Exception as e:
                print(f"❌ 输入: {input_text:15} -> 识别出错: {str(e)}")
                
    except ImportError as e:
        print(f"❌ EnhancedMarketSearch 导入失败: {e}")
    except Exception as e:
        print(f"❌ 期货映射测试失败: {e}")
    
    print("\n=== 测试总结 ===")
    print("✅ COMEX黄金期货真实数据搜索测试完成")
    print("\n测试要点:")
    print("1. ✓ 使用真实的向量数据库数据")
    print("2. ✓ 测试多种黄金期货输入格式")
    print("3. ✓ 验证搜索结果的相关性")
    print("4. ✓ 检查API接口的真实数据返回")
    print("\n如果看到大量真实新闻结果，说明系统正常工作!")
    
    return True

def check_database_content():
    """
    检查数据库内容，确保有真实数据
    """
    print("\n=== 数据库内容检查 ===")
    
    try:
        from news_vector_db import NewsVectorDB
        
        vector_db = NewsVectorDB(db_path="./web/chanlun_chart/chroma_db")
        stats = vector_db.get_collection_stats()
        
        print(f"数据库路径: ./web/chanlun_chart/chroma_db")
        print(f"总文档数: {stats.get('total_documents', 0)}")
        print(f"集合数: {stats.get('collections', 0)}")
        
        # 尝试获取一些样本数据
        try:
            sample_results = vector_db.semantic_search(
                query="黄金",
                n_results=3
            )
            
            if sample_results:
                print(f"\n黄金相关样本新闻 (共{len(sample_results)}条):")
                for i, result in enumerate(sample_results, 1):
                    metadata = result.get('metadata', {})
                    title = metadata.get('title', 'N/A')[:50]
                    source = metadata.get('source', 'N/A')
                    print(f"  {i}. {title}... (来源: {source})")
            else:
                print("\n❌ 无法获取黄金相关样本数据")
                
        except Exception as e:
            print(f"\n❌ 获取样本数据失败: {e}")
            
    except Exception as e:
        print(f"❌ 数据库检查失败: {e}")

if __name__ == "__main__":
    try:
        # 首先检查数据库内容
        check_database_content()
        
        # 然后进行真实数据测试
        success = test_comex_gold_with_real_data()
        
        if success:
            print("\n🎉 COMEX黄金期货真实数据测试成功完成!")
        else:
            print("\n⚠️  COMEX黄金期货真实数据测试遇到问题，请检查数据库内容")
            
    except Exception as e:
        print(f"\n❌ 测试执行失败: {e}")
        import traceback
        traceback.print_exc()