#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专门测试理想汽车相关新闻的语义搜索
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.append(src_path)

web_path = os.path.join(project_root, 'web')
if web_path not in sys.path:
    sys.path.append(web_path)

def test_lixiang_news_search():
    """
    测试理想汽车相关新闻搜索
    """
    try:
        # 导入向量数据库
        from chanlun_chart.cl_app.news_vector_db import NewsVectorDB
        
        print("🚗 理想汽车新闻搜索测试")
        print("=" * 50)
        
        # 初始化向量数据库
        vector_db = NewsVectorDB()
        
        # 测试多个相关关键词
        search_terms = [
            "理想汽车",
            "理想公司", 
            "Li Auto",
            "LI",
            "理想L9",
            "理想L8",
            "理想L7"
        ]
        
        # 设置时间范围（最近6个月）
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=180)
        
        print(f"📅 搜索时间范围: {start_date} 到 {end_date}")
        print(f"🔍 搜索关键词: {', '.join(search_terms)}")
        print()
        
        all_results = {}
        total_news_count = 0
        
        # 对每个关键词进行搜索
        for term in search_terms:
            print(f"🔎 搜索关键词: '{term}'")
            
            search_results = vector_db.semantic_search(
                query=term,
                n_results=100,  # 增加搜索结果数量
                keywords='',
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            if search_results:
                print(f"   ✅ 找到 {len(search_results)} 条相关新闻")
                all_results[term] = search_results
                total_news_count += len(search_results)
                
                # 显示前3条结果
                for i, result in enumerate(search_results[:3], 1):
                    metadata = result.get('metadata', {})
                    title = metadata.get('title', '无标题')
                    published_at = metadata.get('published_at', '未知时间')
                    print(f"     {i}. {title} ({published_at})")
            else:
                print(f"   ❌ 未找到相关新闻")
            print()
        
        # 汇总统计
        print("📊 搜索结果汇总")
        print("=" * 30)
        print(f"总搜索关键词数: {len(search_terms)}")
        print(f"有结果的关键词数: {len(all_results)}")
        print(f"总新闻条数: {total_news_count}")
        print()
        
        if all_results:
            # 合并所有结果并去重（基于news_id）
            unique_news = {}
            for term, results in all_results.items():
                for result in results:
                    news_id = result.get('metadata', {}).get('news_id')
                    if news_id and news_id not in unique_news:
                        unique_news[news_id] = result
            
            print(f"📈 去重后的唯一新闻数: {len(unique_news)}")
            print()
            
            # 显示最相关的10条新闻
            print("🏆 最相关的理想汽车新闻 (前10条):")
            print("-" * 50)
            
            sorted_news = list(unique_news.values())[:10]
            for i, result in enumerate(sorted_news, 1):
                metadata = result.get('metadata', {})
                content = result.get('content', '无内容')
                
                title = metadata.get('title', '无标题')
                published_at = metadata.get('published_at', '未知时间')
                source = metadata.get('source', '未知来源')
                
                print(f"{i:2d}. 标题: {title}")
                print(f"    时间: {published_at}")
                print(f"    来源: {source}")
                if content and content != '无内容':
                    print(f"    内容预览: {content[:150]}...")
                print()
            
            # 按来源统计
            sources = {}
            for result in unique_news.values():
                source = result.get('metadata', {}).get('source', '未知来源')
                sources[source] = sources.get(source, 0) + 1
            
            print("📰 新闻来源分布:")
            for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
                print(f"  {source}: {count} 条")
            
            # 按时间统计（按月）
            months = {}
            for result in unique_news.values():
                published_at = result.get('metadata', {}).get('published_at', '')
                if published_at:
                    try:
                        # 提取年月
                        month = published_at[:7]  # YYYY-MM
                        months[month] = months.get(month, 0) + 1
                    except:
                        pass
            
            if months:
                print("\n📅 新闻时间分布 (按月):")
                sorted_months = sorted(months.items(), key=lambda x: x[0], reverse=True)[:6]
                for month, count in sorted_months:
                    print(f"  {month}: {count} 条")
        
        else:
            print("❌ 所有关键词都未找到相关新闻")
            
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已正确安装相关依赖")
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_lixiang_news_search()