#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试向量数据库语义搜索功能
查询理想公司相关新闻数量
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

def test_semantic_search():
    """
    测试语义搜索功能
    """
    try:
        # 导入向量数据库
        from chanlun_chart.cl_app.news_vector_db import NewsVectorDB
        
        print("🔍 开始测试向量数据库语义搜索功能")
        print("=" * 50)
        
        # 初始化向量数据库
        vector_db = NewsVectorDB()
        
        # 设置查询参数
        name = "理想公司"
        n_results = 50  # 查询最多50条结果
        
        # 设置时间范围（最近30天）
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        
        print(f"📊 查询参数:")
        print(f"   查询关键词: {name}")
        print(f"   结果数量限制: {n_results}")
        print(f"   时间范围: {start_date} 到 {end_date}")
        print()
        
        # 执行语义搜索
        print("🚀 正在执行语义搜索...")
        search_results = vector_db.semantic_search(
            query=name,
            n_results=n_results,
            keywords='',
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat()
        )
        
        # 分析搜索结果
        if search_results:
            print(f"✅ 搜索完成！找到 {len(search_results)} 条相关新闻")
            print()
            
            # 显示前10条结果的详细信息
            print("📰 前10条搜索结果:")
            print("-" * 50)
            
            for i, result in enumerate(search_results[:10], 1):
                # 获取新闻内容和元数据
                content = result.get('content', '无内容')
                metadata = result.get('metadata', {})
                
                title = metadata.get('title', '无标题')
                published_at = metadata.get('published_at', '未知时间')
                source = metadata.get('source', '未知来源')
                
                print(f"{i:2d}. 标题: {title}")
                print(f"    时间: {published_at}")
                print(f"    来源: {source}")
                print(f"    内容预览: {content[:100]}...")
                print()
            
            # 统计分析
            print("📈 统计分析:")
            print("-" * 30)
            
            # 按来源统计
            sources = {}
            for result in search_results:
                source = result.get('metadata', {}).get('source', '未知来源')
                sources[source] = sources.get(source, 0) + 1
            
            print("按来源分布:")
            for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
                print(f"  {source}: {count} 条")
            
            # 按日期统计
            dates = {}
            for result in search_results:
                published_at = result.get('metadata', {}).get('published_at', '')
                if published_at:
                    try:
                        date = published_at.split(' ')[0]  # 提取日期部分
                        dates[date] = dates.get(date, 0) + 1
                    except:
                        pass
            
            if dates:
                print("\n按日期分布 (最近5天):")
                sorted_dates = sorted(dates.items(), key=lambda x: x[0], reverse=True)[:5]
                for date, count in sorted_dates:
                    print(f"  {date}: {count} 条")
            
        else:
            print("❌ 未找到相关新闻")
            
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已正确安装相关依赖")
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_semantic_search()