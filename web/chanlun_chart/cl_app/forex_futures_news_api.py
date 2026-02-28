#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外汇和期货专用新闻搜索API
提供统一的外汇和期货新闻搜索接口
"""

from flask import Flask, request, jsonify
from typing import Dict, List, Optional, Any
import logging
from datetime import datetime, timedelta
import json

# 导入自定义模块
from enhanced_market_search import EnhancedMarketSearch, MarketType
from semantic_search_optimizer import SemanticSearchOptimizer
from forex_currency_mapping import forex_mapper
from futures_commodity_mapping import futures_mapper

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ForexFuturesNewsAPI:
    """外汇和期货新闻搜索API"""
    
    def __init__(self, vector_db=None):
        self.market_search = EnhancedMarketSearch()
        self.semantic_optimizer = SemanticSearchOptimizer()
        self.vector_db = vector_db
        self.forex_mapper = forex_mapper
        self.futures_mapper = futures_mapper
    
    def search_forex_news(self, query: str, **kwargs) -> Dict[str, Any]:
        """搜索外汇相关新闻"""
        try:
            # 参数解析
            limit = kwargs.get('limit', 50)
            days_back = kwargs.get('days_back', 30)
            include_analysis = kwargs.get('include_analysis', True)
            
            # 优化搜索查询
            search_context = self.semantic_optimizer.optimize_search_query(
                query, MarketType.FOREX
            )
            
            # 如果未识别到具体货币对，尝试从查询中提取
            if search_context.symbol == "UNKNOWN":
                forex_pairs = self.forex_mapper.identify_forex_pair(query)
                if forex_pairs:
                    search_context.symbol = forex_pairs[0]
            
            # 执行新闻搜索
            news_results = self._search_news_with_context(
                search_context, limit, days_back
            )
            
            # 生成分析报告
            analysis = None
            if include_analysis and news_results:
                analysis = self._generate_forex_analysis(
                    search_context, news_results
                )
            
            return {
                'success': True,
                'market_type': 'forex',
                'symbol': search_context.symbol,
                'query_optimization': {
                    'primary_keywords': search_context.primary_keywords,
                    'secondary_keywords': search_context.secondary_keywords,
                    'context_keywords': search_context.context_keywords
                },
                'news_count': len(news_results),
                'news_results': news_results,
                'analysis': analysis,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"外汇新闻搜索失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def search_futures_news(self, query: str, **kwargs) -> Dict[str, Any]:
        """搜索期货相关新闻"""
        try:
            # 参数解析
            limit = kwargs.get('limit', 50)
            days_back = kwargs.get('days_back', 30)
            include_analysis = kwargs.get('include_analysis', True)
            include_seasonal = kwargs.get('include_seasonal', True)
            
            # 优化搜索查询
            search_context = self.semantic_optimizer.optimize_search_query(
                query, MarketType.FUTURES
            )
            
            # 如果未识别到具体合约，尝试从查询中提取
            if search_context.symbol == "UNKNOWN":
                futures_contracts = self.futures_mapper.identify_futures_contract(query)
                if futures_contracts:
                    search_context.symbol = futures_contracts[0]
            
            # 执行新闻搜索
            news_results = self._search_news_with_context(
                search_context, limit, days_back
            )
            
            # 生成分析报告
            analysis = None
            if include_analysis and news_results:
                analysis = self._generate_futures_analysis(
                    search_context, news_results, include_seasonal
                )
            
            return {
                'success': True,
                'market_type': 'futures',
                'symbol': search_context.symbol,
                'query_optimization': {
                    'primary_keywords': search_context.primary_keywords,
                    'secondary_keywords': search_context.secondary_keywords,
                    'context_keywords': search_context.context_keywords
                },
                'news_count': len(news_results),
                'news_results': news_results,
                'analysis': analysis,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"期货新闻搜索失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def search_multi_market_news(self, query: str, **kwargs) -> Dict[str, Any]:
        """多市场新闻搜索"""
        try:
            # 使用增强搜索引擎识别所有可能的市场工具
            search_results = self.market_search.identify_market_instrument(query)
            
            if not search_results:
                return {
                    'success': False,
                    'error': '未能识别有效的市场工具',
                    'timestamp': datetime.now().isoformat()
                }
            
            # 按市场类型分组搜索
            all_results = {}
            
            for result in search_results:
                market_type = result.market_type.value
                
                if market_type == 'forex':
                    forex_results = self.search_forex_news(
                        f"{result.symbol} {result.name_cn}", **kwargs
                    )
                    all_results['forex'] = forex_results
                    
                elif market_type == 'futures':
                    futures_results = self.search_futures_news(
                        f"{result.symbol} {result.name_cn}", **kwargs
                    )
                    all_results['futures'] = futures_results
            
            return {
                'success': True,
                'identified_instruments': [{
                    'market_type': result.market_type.value,
                    'symbol': result.symbol,
                    'name': result.name_cn,
                    'confidence': result.confidence
                } for result in search_results],
                'results_by_market': all_results,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"多市场新闻搜索失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def _search_news_with_context(self, search_context, limit: int, days_back: int) -> List[Dict]:
        """使用搜索上下文执行新闻搜索"""
        if not self.vector_db:
            logger.warning("向量数据库未配置，返回模拟数据")
            return self._generate_mock_news(search_context, limit)
        
        try:
            # 构建搜索查询
            expanded_terms = self.semantic_optimizer.expand_search_terms(search_context)
            search_query = ' '.join(expanded_terms[:10])  # 限制搜索词数量
            
            # 执行向量搜索
            raw_results = self.vector_db.semantic_search(
                query=search_query,
                limit=limit * 2,  # 获取更多结果用于过滤
                days_back=days_back
            )
            
            # 计算相关性得分并过滤
            scored_results = []
            for result in raw_results:
                content = result.get('content', '') + ' ' + result.get('title', '')
                relevance_score = self.semantic_optimizer.calculate_relevance_score(
                    content, search_context
                )
                
                if relevance_score > 0.5:  # 相关性阈值
                    result['relevance_score'] = relevance_score
                    scored_results.append(result)
            
            # 按相关性排序
            scored_results.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            # 过滤排除关键词
            filtered_results = []
            for result in scored_results:
                content = result.get('content', '') + ' ' + result.get('title', '')
                if not any(exclude_word in content for exclude_word in search_context.exclude_keywords):
                    filtered_results.append(result)
            
            return filtered_results[:limit]
            
        except Exception as e:
            logger.error(f"新闻搜索执行失败: {e}")
            return []
    
    def _generate_mock_news(self, search_context, limit: int) -> List[Dict]:
        """生成模拟新闻数据"""
        mock_news = []
        
        for i in range(min(limit, 5)):
            mock_news.append({
                'title': f'{search_context.symbol} 相关新闻 {i+1}',
                'content': f'这是关于 {search_context.symbol} 的模拟新闻内容，包含关键词：{", ".join(search_context.primary_keywords[:3])}',
                'source': '模拟数据源',
                'published_at': (datetime.now() - timedelta(days=i)).isoformat(),
                'relevance_score': 0.8 - i * 0.1,
                'url': f'https://example.com/news/{i+1}'
            })
        
        return mock_news
    
    def _generate_forex_analysis(self, search_context, news_results: List[Dict]) -> Dict[str, Any]:
        """生成外汇分析报告"""
        analysis = {
            'market_sentiment': self._analyze_market_sentiment(news_results),
            'key_factors': self._extract_key_factors(news_results, MarketType.FOREX),
            'central_bank_activity': self._analyze_central_bank_activity(news_results),
            'economic_indicators': self._analyze_economic_indicators(news_results),
            'summary': ''
        }
        
        # 生成摘要
        if search_context.symbol != "UNKNOWN":
            pair_info = self.forex_mapper.get_pair_info(search_context.symbol)
            if pair_info:
                analysis['pair_info'] = {
                    'name': pair_info.name_cn,
                    'category': pair_info.category,
                    'base_currency': pair_info.base_currency,
                    'quote_currency': pair_info.quote_currency
                }
        
        analysis['summary'] = f"基于 {len(news_results)} 条新闻的分析，市场情绪为 {analysis['market_sentiment']}。"
        
        return analysis
    
    def _generate_futures_analysis(self, search_context, news_results: List[Dict], include_seasonal: bool) -> Dict[str, Any]:
        """生成期货分析报告"""
        analysis = {
            'market_sentiment': self._analyze_market_sentiment(news_results),
            'supply_demand': self._analyze_supply_demand(news_results),
            'key_factors': self._extract_key_factors(news_results, MarketType.FUTURES),
            'price_drivers': self._analyze_price_drivers(news_results),
            'summary': ''
        }
        
        # 季节性分析
        if include_seasonal and search_context.symbol != "UNKNOWN":
            seasonal_info = self.futures_mapper.get_seasonal_analysis(search_context.symbol)
            if seasonal_info:
                analysis['seasonal_factors'] = seasonal_info
        
        # 合约信息
        if search_context.symbol != "UNKNOWN":
            contract_info = self.futures_mapper.get_contract_info(search_context.symbol)
            if contract_info:
                analysis['contract_info'] = {
                    'name': contract_info.name_cn,
                    'category': contract_info.category,
                    'exchange': contract_info.exchange
                }
        
        analysis['summary'] = f"基于 {len(news_results)} 条新闻的分析，市场情绪为 {analysis['market_sentiment']}。"
        
        return analysis
    
    def _analyze_market_sentiment(self, news_results: List[Dict]) -> str:
        """分析市场情绪"""
        positive_words = ['上涨', '看涨', '乐观', '增长', '强劲', '利好']
        negative_words = ['下跌', '看跌', '悲观', '下降', '疲软', '利空']
        
        positive_count = 0
        negative_count = 0
        
        for news in news_results:
            content = news.get('content', '') + ' ' + news.get('title', '')
            positive_count += sum(1 for word in positive_words if word in content)
            negative_count += sum(1 for word in negative_words if word in content)
        
        if positive_count > negative_count * 1.2:
            return '偏乐观'
        elif negative_count > positive_count * 1.2:
            return '偏悲观'
        else:
            return '中性'
    
    def _extract_key_factors(self, news_results: List[Dict], market_type: MarketType) -> List[str]:
        """提取关键影响因素"""
        key_factors = []
        
        factor_keywords = {
            MarketType.FOREX: ['利率', '央行', '经济数据', '通胀', '就业', '贸易'],
            MarketType.FUTURES: ['供应', '需求', '库存', '天气', '政策', '产量']
        }
        
        keywords = factor_keywords.get(market_type, [])
        
        for keyword in keywords:
            count = sum(1 for news in news_results 
                       if keyword in (news.get('content', '') + ' ' + news.get('title', '')))
            if count > 0:
                key_factors.append(f"{keyword}({count}条新闻)")
        
        return key_factors[:5]  # 返回前5个关键因素
    
    def _analyze_central_bank_activity(self, news_results: List[Dict]) -> Dict[str, int]:
        """分析央行活动"""
        central_banks = ['美联储', '欧央行', '日央行', '英央行', '澳联储']
        activity = {}
        
        for bank in central_banks:
            count = sum(1 for news in news_results 
                       if bank in (news.get('content', '') + ' ' + news.get('title', '')))
            if count > 0:
                activity[bank] = count
        
        return activity
    
    def _analyze_economic_indicators(self, news_results: List[Dict]) -> Dict[str, int]:
        """分析经济指标"""
        indicators = ['GDP', 'CPI', 'PPI', 'PMI', '非农', '零售销售']
        indicator_activity = {}
        
        for indicator in indicators:
            count = sum(1 for news in news_results 
                       if indicator in (news.get('content', '') + ' ' + news.get('title', '')))
            if count > 0:
                indicator_activity[indicator] = count
        
        return indicator_activity
    
    def _analyze_supply_demand(self, news_results: List[Dict]) -> Dict[str, Any]:
        """分析供需情况"""
        supply_keywords = ['供应', '产量', '库存', '开采', '种植']
        demand_keywords = ['需求', '消费', '进口', '出口', '工业需求']
        
        supply_mentions = sum(1 for news in news_results 
                             for keyword in supply_keywords
                             if keyword in (news.get('content', '') + ' ' + news.get('title', '')))
        
        demand_mentions = sum(1 for news in news_results 
                             for keyword in demand_keywords
                             if keyword in (news.get('content', '') + ' ' + news.get('title', '')))
        
        return {
            'supply_mentions': supply_mentions,
            'demand_mentions': demand_mentions,
            'balance': 'supply_focused' if supply_mentions > demand_mentions else 
                      'demand_focused' if demand_mentions > supply_mentions else 'balanced'
        }
    
    def _analyze_price_drivers(self, news_results: List[Dict]) -> List[str]:
        """分析价格驱动因素"""
        price_drivers = ['天气', '地缘政治', '美元', '通胀', '库存', '政策']
        drivers_found = []
        
        for driver in price_drivers:
            count = sum(1 for news in news_results 
                       if driver in (news.get('content', '') + ' ' + news.get('title', '')))
            if count > 0:
                drivers_found.append(f"{driver}({count}条)")
        
        return drivers_found
    
    def get_supported_instruments(self) -> Dict[str, Any]:
        """获取支持的金融工具列表"""
        return {
            'forex_pairs': {
                'major': self.forex_mapper.get_pairs_by_category('major'),
                'minor': self.forex_mapper.get_pairs_by_category('minor'),
                'exotic': self.forex_mapper.get_pairs_by_category('exotic')
            },
            'futures_contracts': {
                'energy': self.futures_mapper.get_contracts_by_category('energy'),
                'precious_metals': self.futures_mapper.get_contracts_by_category('precious_metals'),
                'industrial_metals': self.futures_mapper.get_contracts_by_category('industrial_metals'),
                'agriculture': self.futures_mapper.get_contracts_by_category('agriculture'),
                'soft_commodities': self.futures_mapper.get_contracts_by_category('soft_commodities')
            }
        }

# Flask API 应用
app = Flask(__name__)
api = ForexFuturesNewsAPI()

@app.route('/api/forex/news', methods=['POST'])
def search_forex_news():
    """外汇新闻搜索接口"""
    data = request.get_json()
    query = data.get('query', '')
    
    if not query:
        return jsonify({'success': False, 'error': '查询参数不能为空'}), 400
    
    result = api.search_forex_news(
        query,
        limit=data.get('limit', 50),
        days_back=data.get('days_back', 30),
        include_analysis=data.get('include_analysis', True)
    )
    
    return jsonify(result)

@app.route('/api/futures/news', methods=['POST'])
def search_futures_news():
    """期货新闻搜索接口"""
    data = request.get_json()
    query = data.get('query', '')
    
    if not query:
        return jsonify({'success': False, 'error': '查询参数不能为空'}), 400
    
    result = api.search_futures_news(
        query,
        limit=data.get('limit', 50),
        days_back=data.get('days_back', 30),
        include_analysis=data.get('include_analysis', True),
        include_seasonal=data.get('include_seasonal', True)
    )
    
    return jsonify(result)

@app.route('/api/multi-market/news', methods=['POST'])
def search_multi_market_news():
    """多市场新闻搜索接口"""
    data = request.get_json()
    query = data.get('query', '')
    
    if not query:
        return jsonify({'success': False, 'error': '查询参数不能为空'}), 400
    
    result = api.search_multi_market_news(
        query,
        limit=data.get('limit', 50),
        days_back=data.get('days_back', 30),
        include_analysis=data.get('include_analysis', True)
    )
    
    return jsonify(result)

@app.route('/api/instruments', methods=['GET'])
def get_supported_instruments():
    """获取支持的金融工具"""
    return jsonify(api.get_supported_instruments())

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)