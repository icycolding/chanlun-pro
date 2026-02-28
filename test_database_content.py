#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查向量数据库中的新闻内容
分析数据库中是否包含理想汽车相关的新闻
"""

import sys
import os
from datetime import datetime, timedelta
import re

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.append(src_path)

web_path = os.path.join(project_root, 'web')
if web_path not in sys.path:
    sys.path.append(web_path)

def check_database_content():
    """
    检查向量数据库中的新闻内容
    """
    try:
        # 导入向量数据库
        from chanlun_chart.cl_app.news_vector_db import NewsVectorDB
        
        print("🔍 向量数据库内容检查")
        print("=" * 50)
        
        # 初始化向量数据库
        vector_db = NewsVectorDB()
        
        # 获取数据库统计信息
        try:
            collection = vector_db.collection
            total_count = collection.count()
            print(f"📊 数据库总新闻数: {total_count}")
        except Exception as e:
            print(f"❌ 无法获取数据库统计信息: {e}")
            return
        
        # 测试不同的搜索策略
        search_strategies = [
            {"name": "理想汽车", "query": "理想汽车", "n_results": 50},
            {"name": "Li Auto", "query": "Li Auto", "n_results": 50},
            {"name": "理想", "query": "理想", "n_results": 50},
            {"name": "LI", "query": "LI", "n_results": 50},
            {"name": "李想", "query": "李想", "n_results": 50},
            {"name": "汽车", "query": "汽车", "n_results": 20},
            {"name": "电动车", "query": "电动车", "n_results": 20},
        ]
        
        # 设置时间范围（最近6个月）
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=180)
        
        print(f"📅 搜索时间范围: {start_date} 到 {end_date}")
        print()
        
        all_results = {}
        
        for strategy in search_strategies:
            print(f"🔎 测试搜索策略: {strategy['name']}")
            
            try:
                search_results = vector_db.semantic_search(
                    query=strategy['query'],
                    n_results=strategy['n_results'],
                    keywords='',
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat()
                )
                
                result_count = len(search_results) if search_results else 0
                print(f"  📊 搜索结果数: {result_count}")
                
                if search_results:
                    # 分析前几条结果
                    relevant_count = 0
                    sample_titles = []
                    
                    for result in search_results[:10]:
                        metadata = result.get('metadata', {})
                        title = metadata.get('title', '')
                        content = result.get('content', '')
                        
                        sample_titles.append(title)
                        
                        # 检查是否与理想汽车相关
                        text_to_check = f"{title} {content}".lower()
                        lixiang_keywords = ['理想汽车', '理想公司', 'li auto', '理想l9', '理想l8', '理想l7', '理想one', '李想']
                        
                        for keyword in lixiang_keywords:
                            if keyword.lower() in text_to_check:
                                relevant_count += 1
                                break
                    
                    print(f"  🎯 理想汽车相关: {relevant_count}/{min(10, result_count)}")
                    
                    # 显示样本标题
                    if sample_titles:
                        print(f"  📰 样本标题:")
                        for i, title in enumerate(sample_titles[:3], 1):
                            print(f"    {i}. {title[:80]}{'...' if len(title) > 80 else ''}")
                    
                    all_results[strategy['name']] = {
                        'count': result_count,
                        'relevant': relevant_count,
                        'titles': sample_titles[:5]
                    }
                else:
                    print(f"  ❌ 无搜索结果")
                    all_results[strategy['name']] = {'count': 0, 'relevant': 0, 'titles': []}
                
            except Exception as e:
                print(f"  ❌ 搜索失败: {e}")
                all_results[strategy['name']] = {'count': 0, 'relevant': 0, 'titles': []}
            
            print()
        
        # 汇总分析
        print("📈 搜索策略汇总:")
        print("-" * 60)
        
        total_searches = len(search_strategies)
        successful_searches = sum(1 for r in all_results.values() if r['count'] > 0)
        total_results = sum(r['count'] for r in all_results.values())
        total_relevant = sum(r['relevant'] for r in all_results.values())
        
        print(f"成功搜索策略: {successful_searches}/{total_searches}")
        print(f"总搜索结果数: {total_results}")
        print(f"理想汽车相关结果: {total_relevant}")
        
        if total_results > 0:
            print(f"相关性比例: {total_relevant/total_results*100:.1f}%")
        
        print()
        
        # 详细结果表
        print("📊 详细搜索结果:")
        print(f"{'策略':<10} {'结果数':<8} {'相关数':<8} {'相关率':<8}")
        print("-" * 40)
        
        for name, result in all_results.items():
            count = result['count']
            relevant = result['relevant']
            rate = f"{relevant/count*100:.1f}%" if count > 0 else "0.0%"
            print(f"{name:<10} {count:<8} {relevant:<8} {rate:<8}")
        
        # 如果找到相关结果，显示详细信息
        if total_relevant > 0:
            print("\n🎯 找到的理想汽车相关新闻:")
            print("-" * 50)
            
            for strategy_name, result in all_results.items():
                if result['relevant'] > 0:
                    print(f"\n策略 '{strategy_name}' 的相关结果:")
                    # 这里需要重新搜索来获取详细信息
                    try:
                        detailed_results = vector_db.semantic_search(
                            query=strategy_name,
                            n_results=10,
                            keywords='',
                            start_date=start_date.isoformat(),
                            end_date=end_date.isoformat()
                        )
                        
                        if detailed_results:
                            for i, result in enumerate(detailed_results[:3], 1):
                                metadata = result.get('metadata', {})
                                title = metadata.get('title', '')
                                content = result.get('content', '')
                                published_at = metadata.get('published_at', '未知时间')
                                source = metadata.get('source', '未知来源')
                                
                                # 检查是否真的相关
                                text_to_check = f"{title} {content}".lower()
                                lixiang_keywords = ['理想汽车', '理想公司', 'li auto', '理想l9', '理想l8', '理想l7', '理想one', '李想']
                                
                                is_relevant = False
                                for keyword in lixiang_keywords:
                                    if keyword.lower() in text_to_check:
                                        is_relevant = True
                                        break
                                
                                if is_relevant:
                                    print(f"  {i}. {title}")
                                    print(f"     时间: {published_at}")
                                    print(f"     来源: {source}")
                                    if content:
                                        print(f"     内容: {content[:100]}...")
                                    print()
                    except Exception as e:
                        print(f"     获取详细信息失败: {e}")
        else:
            print("\n❌ 数据库中似乎没有理想汽车相关的新闻")
            print("建议检查:")
            print("1. 数据源是否包含理想汽车新闻")
            print("2. 数据导入是否正确")
            print("3. 搜索算法是否需要优化")
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已正确安装相关依赖")
    except Exception as e:
        print(f"❌ 检查过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database_content()