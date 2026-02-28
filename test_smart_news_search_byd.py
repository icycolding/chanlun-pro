#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试智能新闻搜索功能 - 比亚迪股份
使用代码 KH.01211 和名称 比亚迪股份 搜索相关新闻
"""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "web" / "chanlun_chart" / "cl_app"))

# 切换到正确的工作目录
os.chdir(str(project_root / "web" / "chanlun_chart" / "cl_app"))

try:
    from smart_news_search import SmartNewsSearcher
    from news_vector_db import NewsVectorDB
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保项目路径正确，并且相关模块存在")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"Python路径: {sys.path}")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('test_byd_news_search.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

def print_separator(title: str):
    """打印分隔符"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def print_news_item(news_item: dict, index: int):
    """打印单条新闻信息"""
    metadata = news_item.get('metadata', {})
    title = metadata.get('title', '无标题')
    published_at = metadata.get('published_at', '未知时间')
    source = metadata.get('source', '未知来源')
    score = news_item.get('score', 0)
    
    print(f"\n[{index+1}] 标题: {title}")
    print(f"    发布时间: {published_at}")
    print(f"    来源: {source}")
    print(f"    相关度评分: {score:.4f}")

def print_news_detail(news_item: dict, index: int):
    """打印单条新闻的详细内容"""
    metadata = news_item.get('metadata', {})
    title = metadata.get('title', '无标题')
    # 尝试多个可能的内容字段
    content = (
        news_item.get('document') or  # 向量数据库返回的主要内容字段
        news_item.get('content') or 
        news_item.get('body') or 
        metadata.get('body') or 
        metadata.get('content') or 
        '无内容'
    )
    published_at = metadata.get('published_at', '未知时间')
    source = metadata.get('source', '未知来源')
    score = news_item.get('score', 0)
    
    # 格式化时间显示
    try:
        if published_at and published_at != '未知时间':
            from datetime import datetime
            dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            formatted_time = published_at
    except:
        formatted_time = published_at
    
    # 限制内容长度，避免输出过长
    max_content_length = 500
    if len(content) > max_content_length:
        content = content[:max_content_length] + "...[内容已截断]"
    
    print(f"\n{'='*60}")
    print(f"📰 新闻 #{index+1}")
    print(f"{'='*60}")
    print(f"📌 标题: {title}")
    print(f"🕒 发布时间: {formatted_time}")
    print(f"📡 新闻来源: {source}")
    print(f"⭐ 相关度评分: {score:.4f}")
    print(f"\n📄 新闻内容:")
    print(f"{'-'*40}")
    # 格式化内容，每行不超过80字符
    lines = content.split('\n')
    for line in lines:
        if len(line) <= 80:
            print(line)
        else:
            # 按80字符分行
            for i in range(0, len(line), 80):
                print(line[i:i+80])
    print(f"{'-'*40}")

def test_byd_news_search():
    """测试比亚迪新闻搜索"""
    print_separator("比亚迪股份新闻搜索测试")
    
    try:
        # 1. 初始化向量数据库
        logger.info("正在初始化向量数据库...")
        vector_db = NewsVectorDB()
        
        # 2. 创建智能新闻搜索器
        logger.info("正在创建智能新闻搜索器...")
        searcher = SmartNewsSearcher(vector_db)
        
        # 3. 测试参数
        test_cases = [
            {
                'input': 'KH.01211',
                'description': '使用港股代码 KH.01211'
            },
            {
                'input': '比亚迪股份',
                'description': '使用公司名称 比亚迪股份'
            },
            {
                'input': '01211',
                'description': '使用简化港股代码 01211'
            }
        ]
        
        all_results = []
        
        # 4. 执行搜索测试
        for i, test_case in enumerate(test_cases, 1):
            print_separator(f"测试 {i}: {test_case['description']}")
            
            stock_input = test_case['input']
            logger.info(f"开始搜索: {stock_input}")
            
            try:
                # 执行搜索
                result = searcher.search_news_by_stock(
                    stock_input=stock_input,
                    n_results=30,  # 增加搜索结果数量
                    days_back=60,  # 搜索最近60天
                    include_related=True
                )
                
                if result['success']:
                    stock_info = result['stock_info']
                    results = result['results']
                    stats = result['stats']
                    
                    print(f"✅ 搜索成功!")
                    print(f"📊 股票信息:")
                    print(f"   - 代码: {stock_info.code}")
                    print(f"   - 名称: {stock_info.name}")
                    print(f"   - 交易所: {stock_info.exchange}")
                    print(f"   - 市场类型: {stock_info.market_type}")
                    print(f"   - 原始输入: {stock_info.original_input}")
                    print(f"   - 别名: {stock_info.aliases}")
                    
                    print(f"\n📈 搜索结果统计:")
                    print(f"   - 总共找到: {len(results)} 条新闻")
                    
                    # 来源分布
                    sources = stats['final_stats']['sources']
                    print(f"\n📰 新闻来源分布:")
                    for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
                        print(f"   - {source}: {count} 条")
                    
                    # 日期范围
                    date_range = stats['final_stats']['date_range']
                    if date_range:
                        print(f"\n📅 新闻日期范围:")
                        print(f"   - 最早: {date_range.get('earliest', '未知')}")
                        print(f"   - 最晚: {date_range.get('latest', '未知')}")
                        print(f"   - 跨度: {date_range.get('total_days', 0)} 天")
                    
                    # 搜索详情
                    search_results = stats['search_results']
                    print(f"\n🔍 搜索执行详情:")
                    for search_key, search_info in search_results.items():
                        if 'error' not in search_info:
                            print(f"   - {search_key}: 查询'{search_info['query']}' 找到 {search_info['found']} 条")
                        else:
                            print(f"   - {search_key}: 查询'{search_info['query']}' 失败 - {search_info['error']}")
                    
                    # 显示前5条新闻
                    if results:
                        print(f"\n📋 前5条相关新闻:")
                        for idx, news in enumerate(results[:5]):
                            print_news_item(news, idx)
                    
                    all_results.extend(results)
                    
                else:
                    print(f"❌ 搜索失败: {result.get('error', '未知错误')}")
                    logger.error(f"搜索失败: {result.get('error', '未知错误')}")
                    
            except Exception as e:
                print(f"❌ 搜索过程中发生异常: {e}")
                logger.error(f"搜索异常: {e}", exc_info=True)
        
        # 5. 总结统计
        print_separator("总体统计结果")
        
        # 去重统计
        unique_results = []
        seen_ids = set()
        for result in all_results:
            result_id = result.get('id')
            if result_id and result_id not in seen_ids:
                unique_results.append(result)
                seen_ids.add(result_id)
        
        print(f"📊 总体搜索结果:")
        print(f"   - 总搜索结果: {len(all_results)} 条")
        print(f"   - 去重后结果: {len(unique_results)} 条")
        
        if unique_results:
            # 按时间排序显示最新的10条
            sorted_results = sorted(
                unique_results, 
                key=lambda x: x.get('metadata', {}).get('published_at', ''), 
                reverse=True
            )
            
            print(f"\n🕒 最新10条比亚迪相关新闻:")
            for idx, news in enumerate(sorted_results[:10]):
                print_news_item(news, idx)
            
            # 显示前10条新闻的详细内容
            print_separator("新闻详细内容 (前10条)")
            print(f"📖 以下是前10条新闻的详细内容:")
            
            for idx, news in enumerate(sorted_results[:10]):
                print_news_detail(news, idx)
        
        print(f"\n✅ 测试完成! 共找到 {len(unique_results)} 条关于比亚迪的新闻")
        print(f"📋 已显示前10条新闻的详细内容")
        
    except Exception as e:
        print(f"❌ 测试过程中发生严重错误: {e}")
        logger.error(f"测试失败: {e}", exc_info=True)
        return False
    
    return True

if __name__ == "__main__":
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    success = test_byd_news_search()
    
    print(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if success:
        print("\n🎉 测试成功完成!")
    else:
        print("\n💥 测试失败!")
        sys.exit(1)