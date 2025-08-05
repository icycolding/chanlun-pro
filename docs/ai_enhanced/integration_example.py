#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成示例：将增强版AI分析功能集成到现有缠论系统
演示如何在实际项目中使用知识库增强的AI分析
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.abspath('.')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from chanlun.tools.ai_analyse_enhanced import AIAnalyseEnhanced
from chanlun.tools.ai_analyse import AIAnalyse  # 原始AI分析类
import json
import time
from datetime import datetime

class EnhancedAnalysisService:
    """
    增强分析服务类
    提供统一的AI分析接口，支持原始分析和知识库增强分析
    """
    
    def __init__(self, market: str = "a", kb_name: str = "production_kb"):
        self.market = market
        
        # 初始化原始AI分析器
        self.original_ai = AIAnalyse(market)
        
        # 初始化增强版AI分析器
        self.enhanced_ai = AIAnalyseEnhanced(market, kb_name)
        
        # 初始化生产环境知识库
        self._init_production_knowledge()
    
    def _init_production_knowledge(self):
        """
        初始化生产环境的知识库
        """
        print("正在初始化生产环境知识库...")
        
        # 检查知识库是否已有内容
        stats = self.enhanced_ai.get_knowledge_stats()
        if stats['total_documents'] > 20:  # 假设已经有足够的知识
            print(f"知识库已初始化，包含 {stats['total_documents']} 个文档")
            return
        
        # 添加生产环境专用知识
        production_knowledge = [
            {
                "title": "A股市场特点与缠论应用",
                "content": "A股市场具有以下特点：1）散户占比较高，情绪化交易明显；2）政策影响较大；3）T+1交易制度。在应用缠论时需要注意：适当放宽背驰确认条件，重视政策面影响，合理设置止损位。",
                "category": "市场特点"
            },
            {
                "title": "盘中实时监控策略",
                "content": "盘中实时监控要点：1）关注关键价位的突破和回踩；2）观察成交量的配合情况；3）注意分时图的走势特征；4）结合大盘走势判断个股强弱。建议设置价格提醒，及时跟踪重要信号。",
                "category": "实时监控"
            },
            {
                "title": "止损止盈策略",
                "content": "止损止盈的设置原则：1）止损位设在关键支撑位下方；2）止盈位设在关键阻力位附近；3）根据买卖点级别调整止损幅度；4）采用移动止损保护利润。建议止损幅度：一买点3-5%，二买点5-8%，三买点8-10%。",
                "category": "风险控制"
            },
            {
                "title": "量价配合分析",
                "content": "量价配合的重要性：1）价涨量增为健康上涨；2）价涨量缩需要警惕；3）价跌量增为恐慌性下跌；4）价跌量缩为惜售。在缠论分析中，成交量可以作为背驰确认的重要辅助指标。",
                "category": "技术分析"
            },
            {
                "title": "板块轮动与个股选择",
                "content": "板块轮动规律：1）大盘企稳后，权重股先启动；2）随后热点板块轮动；3）最后是题材股补涨。个股选择要点：选择强势板块中的龙头股，关注基本面良好的个股，避免ST、退市风险股。",
                "category": "选股策略"
            },
            {
                "title": "情绪周期与市场节奏",
                "content": "市场情绪周期：绝望→希望→乐观→兴奋→贪婪→恐惧→绝望。在不同情绪阶段采用不同策略：绝望期逐步建仓，希望期加仓，乐观期减仓，兴奋期清仓。结合缠论买卖点，可以更精确地把握市场节奏。",
                "category": "市场心理"
            }
        ]
        
        success_count = 0
        for knowledge in production_knowledge:
            success = self.enhanced_ai.add_knowledge(
                knowledge["title"], 
                knowledge["content"], 
                knowledge["category"]
            )
            if success:
                success_count += 1
        
        print(f"成功添加 {success_count}/{len(production_knowledge)} 个生产环境知识点")
    
    def analyze_stock(self, code: str, frequency: str, 
                     use_enhanced: bool = True,
                     analysis_type: str = "comprehensive") -> dict:
        """
        分析股票
        
        Args:
            code: 股票代码
            frequency: 时间周期
            use_enhanced: 是否使用增强分析
            analysis_type: 分析类型 (comprehensive, trading, risk)
        
        Returns:
            dict: 分析结果
        """
        start_time = time.time()
        
        try:
            if use_enhanced:
                # 根据分析类型选择知识库分类
                categories = self._get_categories_by_type(analysis_type)
                
                result = self.enhanced_ai.analyse_with_knowledge(
                    code=code,
                    frequency=frequency,
                    use_knowledge=True,
                    knowledge_categories=categories,
                    max_knowledge_docs=3
                )
            else:
                # 使用原始分析
                result = self.original_ai.analyse(code, frequency)
            
            # 添加分析元信息
            result['analysis_time'] = datetime.now().isoformat()
            result['analysis_duration'] = round(time.time() - start_time, 2)
            result['analysis_type'] = 'enhanced' if use_enhanced else 'original'
            result['code'] = code
            result['frequency'] = frequency
            
            return result
            
        except Exception as e:
            return {
                'ok': False,
                'msg': f'分析过程中出现错误: {str(e)}',
                'analysis_time': datetime.now().isoformat(),
                'analysis_duration': round(time.time() - start_time, 2),
                'analysis_type': 'error',
                'code': code,
                'frequency': frequency
            }
    
    def _get_categories_by_type(self, analysis_type: str) -> list:
        """
        根据分析类型获取相关的知识库分类
        """
        category_mapping = {
            'comprehensive': None,  # 搜索所有分类
            'trading': ['买卖点实战', '技术分析', '实时监控'],
            'risk': ['风险控制', '市场心理', '止损策略'],
            'selection': ['选股策略', '板块分析', '市场特点']
        }
        
        return category_mapping.get(analysis_type, None)
    
    def batch_analyze(self, stock_list: list, frequency: str = "30m") -> dict:
        """
        批量分析股票
        
        Args:
            stock_list: 股票代码列表
            frequency: 时间周期
        
        Returns:
            dict: 批量分析结果
        """
        results = {
            'success': [],
            'failed': [],
            'summary': {
                'total': len(stock_list),
                'success_count': 0,
                'failed_count': 0,
                'start_time': datetime.now().isoformat()
            }
        }
        
        print(f"开始批量分析 {len(stock_list)} 只股票...")
        
        for i, code in enumerate(stock_list, 1):
            print(f"正在分析 {i}/{len(stock_list)}: {code}")
            
            result = self.analyze_stock(code, frequency, use_enhanced=True)
            
            if result['ok']:
                results['success'].append(result)
                results['summary']['success_count'] += 1
            else:
                results['failed'].append(result)
                results['summary']['failed_count'] += 1
            
            # 避免请求过于频繁
            time.sleep(1)
        
        results['summary']['end_time'] = datetime.now().isoformat()
        
        print(f"批量分析完成: 成功 {results['summary']['success_count']}, 失败 {results['summary']['failed_count']}")
        
        return results
    
    def compare_analysis_methods(self, code: str, frequency: str) -> dict:
        """
        比较原始分析和增强分析的结果
        
        Args:
            code: 股票代码
            frequency: 时间周期
        
        Returns:
            dict: 比较结果
        """
        print(f"正在比较分析方法: {code} {frequency}")
        
        # 原始分析
        original_result = self.analyze_stock(code, frequency, use_enhanced=False)
        
        # 增强分析
        enhanced_result = self.analyze_stock(code, frequency, use_enhanced=True)
        
        comparison = {
            'code': code,
            'frequency': frequency,
            'original': original_result,
            'enhanced': enhanced_result,
            'comparison_time': datetime.now().isoformat()
        }
        
        # 简单的结果比较
        if original_result['ok'] and enhanced_result['ok']:
            comparison['analysis'] = {
                'original_length': len(original_result['msg']),
                'enhanced_length': len(enhanced_result['msg']),
                'time_difference': enhanced_result['analysis_duration'] - original_result['analysis_duration']
            }
        
        return comparison
    
    def get_service_status(self) -> dict:
        """
        获取服务状态
        
        Returns:
            dict: 服务状态信息
        """
        kb_stats = self.enhanced_ai.get_knowledge_stats()
        
        return {
            'service_name': 'Enhanced Analysis Service',
            'market': self.market,
            'knowledge_base': {
                'total_documents': kb_stats['total_documents'],
                'categories': kb_stats['categories']
            },
            'status': 'active',
            'timestamp': datetime.now().isoformat()
        }

def demo_integration():
    """
    演示集成使用
    """
    print("=== 增强分析服务集成演示 ===")
    
    # 1. 初始化服务
    print("\n1. 初始化增强分析服务...")
    service = EnhancedAnalysisService("a", "demo_production_kb")
    
    # 2. 查看服务状态
    print("\n2. 服务状态:")
    status = service.get_service_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    
    # 3. 单股分析示例
    print("\n3. 单股分析示例:")
    
    # 注意：这里使用模拟分析，实际使用时需要配置AI API
    print("   注意：以下为模拟分析流程，实际使用需要配置AI API密钥")
    
    test_stocks = ['000001', '000002', '600000']
    
    for stock in test_stocks[:1]:  # 只测试第一只股票
        print(f"\n   分析股票: {stock}")
        
        # 模拟不同类型的分析
        analysis_types = ['trading', 'risk']
        
        for analysis_type in analysis_types:
            print(f"     分析类型: {analysis_type}")
            
            # 这里只演示参数构建，不实际调用AI
            categories = service._get_categories_by_type(analysis_type)
            print(f"     使用知识库分类: {categories}")
            
            # 搜索相关知识示例
            if categories:
                for category in categories[:1]:  # 只测试第一个分类
                    results = service.enhanced_ai.search_knowledge(
                        "分析策略", top_k=2, category=category
                    )
                    print(f"     在分类 '{category}' 中找到 {len(results)} 个相关知识")
    
    # 4. 批量分析示例
    print("\n4. 批量分析示例:")
    print("   注意：实际批量分析需要有效的AI API配置")
    print(f"   待分析股票: {test_stocks}")
    print("   分析周期: 30m")
    print("   预计耗时: 约 3-5 分钟")
    
    # 5. 方法比较示例
    print("\n5. 分析方法比较:")
    print("   原始分析: 基于缠论数据直接生成提示词")
    print("   增强分析: 融合知识库内容的智能提示词")
    print("   预期效果: 增强分析提供更专业、更有针对性的建议")
    
    print("\n=== 集成演示完成 ===")
    
    # 6. 使用建议
    print("\n使用建议:")
    print("1. 生产环境中建议使用增强分析")
    print("2. 定期更新知识库内容")
    print("3. 根据实际需求选择分析类型")
    print("4. 合理设置批量分析的频率")
    print("5. 结合其他技术指标进行综合判断")

if __name__ == "__main__":
    try:
        demo_integration()
    except Exception as e:
        print(f"演示过程中出现错误: {e}")
        print("请检查环境配置和依赖包安装情况。")