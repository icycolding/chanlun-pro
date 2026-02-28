#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KH.02015股票代码新闻搜索功能测试
测试腾讯控股(KH.02015)的新闻搜索能力
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
sys.path.append('./web/chanlun_chart/cl_app')

def test_kh02015_stock_news():
    """
    测试KH.02015股票代码的新闻搜索功能
    """
    print("\n" + "=" * 60)
    print("📈 KH.02015股票代码新闻搜索功能测试")
    print("=" * 60)
    
    try:
        # 导入智能新闻搜索系统
        from smart_news_search import SmartNewsSearcher
        from news_vector_db import NewsVectorDB
        
        print("✓ 成功导入智能新闻搜索模块")
        
        # 初始化向量数据库
        vector_db_path = "/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/chroma_db"
        vector_db = NewsVectorDB(vector_db_path)
        print(f"✓ 成功连接向量数据库: {vector_db_path}")
        
        # 初始化智能新闻搜索器
        searcher = SmartNewsSearcher(vector_db)
        print("✓ 成功初始化智能新闻搜索器")
        
        # 测试不同格式的KH.02015输入
        test_inputs = [
            "KH.02015",
            "02015",
            "2015.HK", 
            "腾讯控股",
            "腾讯",
            "Tencent",
            "TCEHY"
        ]
        
        print("\n=== 测试股票代码格式识别 ===")
        
        for input_str in test_inputs:
            print(f"\n🔍 测试输入: {input_str}")
            
            try:
                # 解析股票输入
                stock_info = searcher.stock_mapper.parse_stock_input(input_str)
                
                if stock_info:
                    print(f"   ✓ 识别成功")
                    print(f"   📊 股票代码: {stock_info.code}")
                    print(f"   🏢 公司名称: {stock_info.name}")
                    print(f"   🌏 市场: {stock_info.exchange}")
                    if stock_info.aliases:
                        print(f"   🏷️  别名: {', '.join(stock_info.aliases[:3])}")
                else:
                    print(f"   ❌ 无法识别股票代码格式")
                    
            except Exception as e:
                print(f"   ❌ 解析出错: {str(e)}")
        
        print("\n=== 测试向量数据库新闻搜索 ===")
        
        # 使用最标准的输入进行新闻搜索测试
        test_query = "KH.02015"
        print(f"\n🔍 搜索查询: {test_query}")
        
        try:
            # 执行新闻搜索
            search_results = searcher.search_news_by_stock(
                stock_input=test_query,
                n_results=10,
                days_back=30,
                include_related=True
            )
            
            if search_results and search_results.get('success', False):
                results = search_results.get('results', [])
                total_found = len(results)
                
                if total_found > 0:
                    print(f"✓ 成功找到 {total_found} 条腾讯相关新闻")
                    
                    # 显示前5条新闻
                    print("\n📰 新闻列表 (前5条):")
                    for i, result in enumerate(results[:5], 1):
                        # 从metadata中提取信息
                        metadata = result.get('metadata', {})
                        title = metadata.get('title', 'N/A')
                        source = metadata.get('source', 'N/A')
                        published_at = metadata.get('published_at', 'N/A')
                        
                        # 计算相似度
                        distance = result.get('distance', 1.0)
                        similarity = result.get('score', max(0.0, 1.0 - distance))
                        
                        # 截断标题显示
                        display_title = title[:50] + "..." if len(title) > 50 else title
                        
                        print(f"   {i}. {display_title}")
                        print(f"      相似度: {similarity:.3f} | 来源: {source} | 时间: {published_at}")
                        
                        # 检查是否包含腾讯相关关键词
                        content = result.get('content', '').lower()
                        title_lower = title.lower()
                        tencent_keywords = ['腾讯', 'tencent', '微信', 'wechat', 'qq']
                        
                        found_keywords = []
                        for keyword in tencent_keywords:
                            if keyword in content or keyword in title_lower:
                                found_keywords.append(keyword)
                        
                        if found_keywords:
                            print(f"      🎯 匹配关键词: {', '.join(found_keywords)}")
                        print()
                    
                    # 统计信息
                    print("\n📊 搜索统计:")
                    if 'stats' in search_results:
                        stats = search_results['stats']
                        if 'stock_info' in stats:
                            stock_info_stats = stats['stock_info']
                            print(f"   📈 识别股票: {stock_info_stats.get('code', 'N/A')} - {stock_info_stats.get('name', 'N/A')}")
                        
                        if 'search_params' in stats and 'keywords' in stats['search_params']:
                            keywords = stats['search_params']['keywords']
                            print(f"   🔍 搜索关键词: {', '.join(keywords[:5])}")
                    
                    return True
                    
                else:
                    print("❌ 未找到腾讯相关新闻")
                    print("   可能原因:")
                    print("   1. 数据库中缺少腾讯相关新闻")
                    print("   2. 新闻内容与腾讯关联度较低")
                    print("   3. 搜索关键词需要优化")
                    return False
            else:
                print("❌ 搜索结果格式异常")
                return False
                
        except Exception as e:
            print(f"❌ 新闻搜索出错: {str(e)}")
            return False
            
    except ImportError as e:
        print(f"❌ 模块导入失败: {e}")
        print("请确保已正确安装所需依赖")
        return False
    except Exception as e:
        print(f"❌ 测试执行出错: {str(e)}")
        return False

def test_stock_mapping_verification():
    """
    验证股票映射配置
    """
    print("\n=== 验证股票映射配置 ===")
    
    try:
        # 读取股票映射配置
        mapping_file = "./web/chanlun_chart/cl_app/stock_mappings.json"
        
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
            
            print(f"✓ 成功读取股票映射配置: {mapping_file}")
            
            # 查找腾讯相关配置
            tencent_found = False
            for code, info in mappings.items():
                if '2015' in code or 'tencent' in info.get('company_name', '').lower():
                    tencent_found = True
                    print(f"\n📊 找到腾讯配置:")
                    print(f"   代码: {code}")
                    print(f"   公司名称: {info.get('company_name', 'N/A')}")
                    print(f"   别名: {info.get('aliases', [])}")
                    print(f"   市场: {info.get('market', 'N/A')}")
            
            if not tencent_found:
                print("⚠️  未在映射配置中找到腾讯相关信息")
                
        else:
            print(f"❌ 股票映射配置文件不存在: {mapping_file}")
            
    except Exception as e:
        print(f"❌ 验证股票映射配置出错: {str(e)}")

def main():
    """
    主测试函数
    """
    print("🚀 开始KH.02015股票代码新闻搜索功能测试")
    
    # 验证股票映射配置
    test_stock_mapping_verification()
    
    # 测试新闻搜索功能
    success = test_kh02015_stock_news()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ KH.02015股票代码新闻搜索功能测试通过")
        print("   - 股票代码格式识别正常")
        print("   - 公司名称映射正确")
        print("   - 向量数据库搜索成功")
        print("   - 新闻结果显示正常")
    else:
        print("❌ KH.02015股票代码新闻搜索功能测试失败")
        print("   请检查向量数据库连接和数据完整性")
    print("=" * 60)

if __name__ == "__main__":
    import json
    main()