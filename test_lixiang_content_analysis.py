#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析理想汽车相关新闻的内容质量
检查搜索结果是否真的与理想汽车相关
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

def analyze_lixiang_content():
    """
    分析理想汽车相关新闻的内容质量
    """
    try:
        # 导入向量数据库
        from chanlun_chart.cl_app.news_vector_db import NewsVectorDB
        
        print("🔍 理想汽车新闻内容质量分析")
        print("=" * 50)
        
        # 初始化向量数据库
        vector_db = NewsVectorDB()
        
        # 理想汽车相关关键词
        lixiang_keywords = [
            "理想汽车", "理想公司", "Li Auto", "LI", 
            "理想L9", "理想L8", "理想L7", "理想ONE",
            "李想", "理想智造"
        ]
        
        # 设置时间范围（最近3个月）
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=90)
        
        print(f"📅 分析时间范围: {start_date} 到 {end_date}")
        print(f"🎯 理想汽车关键词: {', '.join(lixiang_keywords)}")
        print()
        
        # 搜索理想汽车相关新闻
        search_results = vector_db.semantic_search(
            query="理想汽车",
            n_results=200,
            keywords='',
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat()
        )
        
        if not search_results:
            print("❌ 未找到任何相关新闻")
            return
        
        print(f"📊 初步搜索结果: {len(search_results)} 条新闻")
        print()
        
        # 分析每条新闻的相关性
        relevant_news = []
        irrelevant_news = []
        
        print("🔎 正在分析新闻内容相关性...")
        
        for i, result in enumerate(search_results):
            metadata = result.get('metadata', {})
            content = result.get('content', '')
            title = metadata.get('title', '')
            
            # 检查标题和内容中是否包含理想汽车关键词
            text_to_check = f"{title} {content}".lower()
            
            is_relevant = False
            matched_keywords = []
            
            for keyword in lixiang_keywords:
                if keyword.lower() in text_to_check:
                    is_relevant = True
                    matched_keywords.append(keyword)
            
            news_info = {
                'index': i + 1,
                'title': title,
                'content': content[:200] + '...' if len(content) > 200 else content,
                'published_at': metadata.get('published_at', '未知时间'),
                'source': metadata.get('source', '未知来源'),
                'matched_keywords': matched_keywords,
                'news_id': metadata.get('news_id', '未知ID')
            }
            
            if is_relevant:
                relevant_news.append(news_info)
            else:
                irrelevant_news.append(news_info)
        
        # 输出分析结果
        print(f"✅ 真正相关的新闻: {len(relevant_news)} 条")
        print(f"❌ 不相关的新闻: {len(irrelevant_news)} 条")
        print(f"📈 相关性比例: {len(relevant_news)/len(search_results)*100:.1f}%")
        print()
        
        # 显示真正相关的新闻
        if relevant_news:
            print("🎯 真正相关的理想汽车新闻:")
            print("-" * 60)
            
            for i, news in enumerate(relevant_news[:10], 1):
                print(f"{i:2d}. 标题: {news['title']}")
                print(f"    时间: {news['published_at']}")
                print(f"    来源: {news['source']}")
                print(f"    匹配关键词: {', '.join(news['matched_keywords'])}")
                if news['content'] and news['content'] != '无内容...':
                    print(f"    内容预览: {news['content']}")
                print()
        
        # 显示一些不相关的新闻作为对比
        if irrelevant_news:
            print("❓ 不相关新闻示例 (前5条):")
            print("-" * 40)
            
            for i, news in enumerate(irrelevant_news[:5], 1):
                print(f"{i}. 标题: {news['title']}")
                print(f"   时间: {news['published_at']}")
                if news['content'] and news['content'] != '无内容...':
                    print(f"   内容预览: {news['content'][:100]}...")
                print()
        
        # 关键词匹配统计
        if relevant_news:
            keyword_stats = {}
            for news in relevant_news:
                for keyword in news['matched_keywords']:
                    keyword_stats[keyword] = keyword_stats.get(keyword, 0) + 1
            
            print("📊 关键词匹配统计:")
            for keyword, count in sorted(keyword_stats.items(), key=lambda x: x[1], reverse=True):
                print(f"  {keyword}: {count} 次")
            print()
        
        # 时间分布分析
        if relevant_news:
            time_stats = {}
            for news in relevant_news:
                published_at = news['published_at']
                if published_at and published_at != '未知时间':
                    try:
                        date = published_at.split('T')[0]  # 提取日期部分
                        time_stats[date] = time_stats.get(date, 0) + 1
                    except:
                        pass
            
            if time_stats:
                print("📅 相关新闻时间分布 (最近10天):")
                sorted_dates = sorted(time_stats.items(), key=lambda x: x[0], reverse=True)[:10]
                for date, count in sorted_dates:
                    print(f"  {date}: {count} 条")
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已正确安装相关依赖")
    except Exception as e:
        print(f"❌ 分析过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_lixiang_content()