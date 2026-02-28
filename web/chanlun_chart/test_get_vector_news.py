#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的get_vector_news函数
验证是否能正确从向量数据库获取新闻并返回正文内容
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 设置环境变量
os.environ.setdefault('FLASK_ENV', 'development')

try:
    # 尝试直接导入函数
    from cl_app.news_vector_api import get_vector_news
    print("✅ 成功导入get_vector_news函数")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("尝试手动设置路径...")
    
    # 手动添加更多路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(project_root, 'src'))
    sys.path.insert(0, os.path.join(project_root, 'web', 'chanlun_chart'))
    
    try:
        from cl_app.news_vector_api import get_vector_news
        print("✅ 手动设置路径后成功导入")
    except ImportError as e2:
        print(f"❌ 仍然导入失败: {e2}")
        print("\n尝试查看可用的模块...")
        
        # 检查cl_app目录
        cl_app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cl_app')
        if os.path.exists(cl_app_path):
            print(f"cl_app目录存在: {cl_app_path}")
            files = os.listdir(cl_app_path)
            print(f"cl_app目录内容: {files}")
            
            # 检查news_vector_api.py文件
            news_api_file = os.path.join(cl_app_path, 'news_vector_api.py')
            if os.path.exists(news_api_file):
                print(f"news_vector_api.py文件存在")
                
                # 尝试直接执行文件来测试函数
                print("\n尝试直接测试函数...")
                exec(open(news_api_file).read())
                
        sys.exit(1)

import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_get_vector_news():
    """
    测试get_vector_news函数
    """
    print("=" * 60)
    print("测试get_vector_news函数")
    print("=" * 60)
    
    # 测试用例1: 港股比亚迪
    print("\n1. 测试港股比亚迪 (KH.01211)")
    try:
        results = get_vector_news(code="KH.01211", market="hk", days=7, n_results=5)
        print(f"搜索结果数量: {len(results)}")
        
        if results:
            print("\n前3条新闻详情:")
            for i, news in enumerate(results[:3], 1):
                print(f"\n--- 新闻 {i} ---")
                print(f"ID: {news.get('id', 'N/A')}")
                print(f"标题: {news.get('metadata', {}).get('title', 'N/A')[:100]}...")
                print(f"来源: {news.get('metadata', {}).get('source', 'N/A')}")
                print(f"发布时间: {news.get('metadata', {}).get('published_at', 'N/A')}")
                print(f"评分: {news.get('score', 'N/A')}")
                
                # 检查正文内容
                document = news.get('document', '')
                if document:
                    print(f"✅ 正文长度: {len(document)} 字符")
                    print(f"正文预览: {document[:200]}...")
                else:
                    print("❌ 警告: 正文内容为空!")
        else:
            print("❌ 未找到相关新闻")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试用例2: 外汇EURUSD
    print("\n\n2. 测试外汇EURUSD (FE.EURUSD)")
    try:
        results = get_vector_news(code="FE.EURUSD", market="fx", days=3, n_results=3)
        print(f"搜索结果数量: {len(results)}")
        
        if results:
            print("\n新闻详情:")
            for i, news in enumerate(results, 1):
                print(f"\n--- 新闻 {i} ---")
                print(f"ID: {news.get('id', 'N/A')}")
                print(f"标题: {news.get('metadata', {}).get('title', 'N/A')[:80]}...")
                
                # 检查正文内容
                document = news.get('document', '')
                if document:
                    print(f"✅ 正文长度: {len(document)} 字符")
                    print(f"正文预览: {document[:150]}...")
                else:
                    print("❌ 警告: 正文内容为空!")
        else:
            print("❌ 未找到相关新闻")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

def validate_news_format(news_list):
    """
    验证新闻数据格式是否正确
    """
    print("\n验证新闻数据格式:")
    
    required_fields = ['id', 'document', 'metadata']
    
    for i, news in enumerate(news_list[:2], 1):  # 只检查前2条
        print(f"\n新闻 {i} 格式检查:")
        
        for field in required_fields:
            if field in news:
                print(f"✅ {field}: 存在")
                if field == 'document' and news[field]:
                    print(f"   正文长度: {len(news[field])} 字符")
                elif field == 'metadata' and isinstance(news[field], dict):
                    metadata_keys = list(news[field].keys())
                    print(f"   元数据字段: {metadata_keys[:5]}...")
            else:
                print(f"❌ {field}: 缺失")

if __name__ == "__main__":
    test_get_vector_news()