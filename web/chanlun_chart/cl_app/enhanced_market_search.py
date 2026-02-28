#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强的市场搜索算法
支持股票、外汇、期货的统一搜索和新闻检索
"""

import re
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import logging

# 导入映射模块
from cl_app.forex_currency_mapping import forex_mapper, ForexPairInfo
from cl_app.futures_commodity_mapping import futures_mapper, FuturesContractInfo
from cl_app.smart_news_search import StockCodeMapper, StockInfo

class MarketType(Enum):
    """市场类型枚举"""
    STOCK = "stock"
    FOREX = "forex"
    FUTURES = "futures"
    UNKNOWN = "unknown"

@dataclass
class SearchResult:
    """搜索结果"""
    market_type: MarketType
    symbol: str
    name_en: str
    name_cn: str
    keywords: List[str]
    confidence: float  # 置信度 0-1
    additional_info: Dict[str, Any]

@dataclass
class NewsSearchQuery:
    """新闻搜索查询"""
    primary_keywords: List[str]  # 主要关键词
    secondary_keywords: List[str]  # 次要关键词
    exclude_keywords: List[str]  # 排除关键词
    market_type: MarketType
    symbol: str
    time_range: int = 30  # 天数
    max_results: int = 50

class EnhancedMarketSearch:
    """增强的市场搜索引擎"""
    
    def __init__(self):
        self.forex_mapper = forex_mapper
        self.futures_mapper = futures_mapper
        self.stock_mapper = StockCodeMapper()
        self.logger = logging.getLogger(__name__)
        
        # 股票代码模式（按优先级排序，更具体的模式在前）
        self.stock_patterns = [
            r'KH\.\d{5}',      # KH前缀股票代码
            r'\d{4}\.HK',      # 港股
            r'\d{6}\.SH',      # 沪市
            r'\d{6}\.SZ',      # 深市
            r'\b(?!KH\b)[A-Z]{2,5}\b',  # 美股（至少2个字母，排除KH前缀）
        ]
        
        # 通用市场关键词
        self.market_keywords = {
            MarketType.STOCK: ['股票', '股价', '上市公司', '财报', '业绩', '股市'],
            MarketType.FOREX: ['外汇', '汇率', '货币', '央行', '利率', '货币政策'],
            MarketType.FUTURES: ['期货', '商品', '合约', '库存', '产量', '供需']
        }
    
    def identify_market_instrument(self, query: str) -> List[SearchResult]:
        """识别市场工具类型和具体标的"""
        results = []
        
        # 1. 尝试识别外汇货币对
        forex_pairs = self.forex_mapper.identify_forex_pair(query)
        for pair in forex_pairs:
            pair_info = self.forex_mapper.get_pair_info(pair)
            if pair_info:
                keywords = self.forex_mapper.get_search_keywords(pair)
                result = SearchResult(
                    market_type=MarketType.FOREX,
                    symbol=pair,
                    name_en=pair_info.name_en,
                    name_cn=pair_info.name_cn,
                    keywords=keywords,
                    confidence=0.9,
                    additional_info={
                        'category': pair_info.category,
                        'base_currency': pair_info.base_currency,
                        'quote_currency': pair_info.quote_currency
                    }
                )
                results.append(result)
        
        # 2. 尝试识别期货合约
        futures_contracts = self.futures_mapper.identify_futures_contract(query)
        for contract in futures_contracts:
            contract_info = self.futures_mapper.get_contract_info(contract)
            commodity_info = self.futures_mapper.get_commodity_info(contract)
            if contract_info:
                keywords = self.futures_mapper.get_search_keywords(contract)
                result = SearchResult(
                    market_type=MarketType.FUTURES,
                    symbol=contract,
                    name_en=contract_info.name_en,
                    name_cn=contract_info.name_cn,
                    keywords=keywords,
                    confidence=0.9,
                    additional_info={
                        'category': contract_info.category,
                        'exchange': contract_info.exchange,
                        'commodity': contract_info.commodity,
                        'seasonal_factors': contract_info.seasonal_factors
                    }
                )
                results.append(result)
        
        # 3. 尝试识别股票代码
        stock_matches = self._identify_stock_symbols(query)
        results.extend(stock_matches)
        
        # 4. 如果没有明确识别，尝试基于关键词推断
        if not results:
            inferred_results = self._infer_market_type(query)
            results.extend(inferred_results)
        
        return results
    
    def _identify_stock_symbols(self, query: str) -> List[SearchResult]:
        """识别股票代码"""
        results = []
        found_symbols = set()  # 避免重复识别同一个符号
        
        for pattern in self.stock_patterns:
            matches = re.findall(pattern, query.upper())
            for match in matches:
                if match not in found_symbols:
                    found_symbols.add(match)
                    
                    # 使用StockCodeMapper获取股票信息
                    stock_info = self.stock_mapper.parse_stock_input(match)
                    
                    if stock_info:
                        # 使用映射器获取的详细信息
                        keywords = [match, stock_info.code, stock_info.name] + stock_info.aliases + ['股票', '股价', '财报']
                        result = SearchResult(
                            market_type=MarketType.STOCK,
                            symbol=stock_info.code,
                            name_en=stock_info.name,
                            name_cn=stock_info.name,
                            keywords=keywords,
                            confidence=0.9,
                            additional_info={
                                'exchange': stock_info.exchange,
                                'market_type': stock_info.market_type,
                                'aliases': stock_info.aliases
                            }
                        )
                    else:
                        # 回退到原有逻辑
                        result = SearchResult(
                            market_type=MarketType.STOCK,
                            symbol=match,
                            name_en=f"Stock {match}",
                            name_cn=f"股票 {match}",
                            keywords=[match, '股票', '股价', '财报'],
                            confidence=0.8,
                            additional_info={'exchange': self._get_stock_exchange(match)}
                        )
                    
                    results.append(result)
        
        return results
    
    def _get_stock_exchange(self, symbol: str) -> str:
        """根据股票代码获取交易所"""
        if '.HK' in symbol or symbol.startswith('KH.'):
            return '港交所'
        elif '.SH' in symbol:
            return '上交所'
        elif '.SZ' in symbol:
            return '深交所'
        else:
            return '美股'
    
    def _infer_market_type(self, query: str) -> List[SearchResult]:
        """基于关键词推断市场类型"""
        results = []
        
        for market_type, keywords in self.market_keywords.items():
            score = sum(1 for keyword in keywords if keyword in query)
            if score > 0:
                confidence = min(score / len(keywords), 0.7)  # 最高0.7置信度
                result = SearchResult(
                    market_type=market_type,
                    symbol="UNKNOWN",
                    name_en=f"Unknown {market_type.value}",
                    name_cn=f"未知{market_type.value}",
                    keywords=keywords,
                    confidence=confidence,
                    additional_info={'inferred': True}
                )
                results.append(result)
        
        return results
    
    def generate_news_search_query(self, search_results: List[SearchResult]) -> List[NewsSearchQuery]:
        """生成新闻搜索查询"""
        queries = []
        
        for result in search_results:
            print('result', result)
            if result.market_type == MarketType.FOREX:
                query = self._generate_forex_news_query(result)
            elif result.market_type == MarketType.FUTURES:
                query = self._generate_futures_news_query(result)
            elif result.market_type == MarketType.STOCK:
                query = self._generate_stock_news_query(result)
            else:
                query = self._generate_generic_news_query(result)
            
            queries.append(query)
        
        return queries
    
    def _generate_forex_news_query(self, result: SearchResult) -> NewsSearchQuery:
        """生成外汇新闻搜索查询"""
        primary_keywords = [result.symbol, result.name_cn,'fx','usd']
        
        # 添加货币对特定关键词
        if result.symbol in self.forex_mapper.forex_pairs:
            pair_info = self.forex_mapper.forex_pairs[result.symbol]
            primary_keywords.extend(pair_info.keywords[:3])  # 取前3个关键词
        
        # 次要关键词
        secondary_keywords = [
            '汇率', '外汇', '央行', '货币政策', '利率决议',
            '经济数据', 'GDP', 'CPI', '就业数据'
        ]
        
        # 排除关键词
        exclude_keywords = ['股票', '期货', '商品']
        
        return NewsSearchQuery(
            primary_keywords=primary_keywords,
            secondary_keywords=secondary_keywords,
            exclude_keywords=exclude_keywords,
            market_type=MarketType.FOREX,
            symbol=result.symbol
        )
    
    def _generate_futures_news_query(self, result: SearchResult) -> NewsSearchQuery:
        """生成期货新闻搜索查询"""
        primary_keywords = [result.symbol, result.name_cn]
        
        # 添加期货特定关键词
        if result.symbol in self.futures_mapper.futures_contracts:
            contract_info = self.futures_mapper.futures_contracts[result.symbol]
            primary_keywords.extend(contract_info.keywords[:3])
        
        # 次要关键词
        secondary_keywords = [
            '期货', '商品', '库存', '产量', '供需',
            '价格', '合约', '交割', '持仓'
        ]
        
        # 根据商品类别添加特定关键词
        category = result.additional_info.get('category', '')
        if category == 'energy':
            secondary_keywords.extend(['OPEC', 'EIA', 'API', '钻井数'])
        elif category == 'agriculture':
            secondary_keywords.extend(['USDA', '天气', '种植', '收获'])
        elif category == 'precious_metals':
            secondary_keywords.extend(['避险', '通胀', '美元指数'])
        
        exclude_keywords = ['股票', '外汇', '汇率']
        
        return NewsSearchQuery(
            primary_keywords=primary_keywords,
            secondary_keywords=secondary_keywords,
            exclude_keywords=exclude_keywords,
            market_type=MarketType.FUTURES,
            symbol=result.symbol
        )
    
    def _generate_stock_news_query(self, result: SearchResult) -> NewsSearchQuery:
        """生成股票新闻搜索查询"""
        primary_keywords = [result.symbol, result.name_cn]
        
        secondary_keywords = [
            '股票', '股价', '上市公司', '财报', '业绩',
            '营收', '利润', '分红', '重组', '并购'
        ]
        
        exclude_keywords = ['外汇', '期货', '商品']
        
        return NewsSearchQuery(
            primary_keywords=primary_keywords,
            secondary_keywords=secondary_keywords,
            exclude_keywords=exclude_keywords,
            market_type=MarketType.STOCK,
            symbol=result.symbol
        )
    
    def _generate_generic_news_query(self, result: SearchResult) -> NewsSearchQuery:
        """生成通用新闻搜索查询"""
        return NewsSearchQuery(
            primary_keywords=[result.name_cn] if result.name_cn != "未知" else [],
            secondary_keywords=result.keywords[:5],
            exclude_keywords=[],
            market_type=result.market_type,
            symbol=result.symbol
        )
    
    def search_news(self, query: str,days: str,vector_db=None) -> Dict[str, Any]:
        """搜索相关新闻"""
        # 1. 识别市场工具
        search_results = self.identify_market_instrument(query)
        print('search_results',search_results)
        if not search_results:
            return {
                'success': False,
                'message': '未能识别有效的市场工具',
                'results': []
            }
        
        # 2. 生成搜索查询
        news_queries = self.generate_news_search_query(search_results)
        print('news_queries11', news_queries)
        # 3. 执行新闻搜索
        all_news = []
        news_results = self._search_with_vector_db('eurusd', vector_db,days)

        # for news_query in news_queries:
        #     if vector_db:
        #         # 使用向量数据库搜索
        #         news_results = self._search_with_vector_db(news_query, vector_db,days)
        #         all_news.extend(news_results)
        print('all_news2', len(all_news))
        # 4. 去重和排序
        unique_news = self._deduplicate_news(all_news)
        print('unique_news2', len(unique_news))
        sorted_news = self._sort_news_by_relevance(unique_news, search_results)
        print('sorted_news2', len(sorted_news))
        return {
            'success': True,
            'identified_instruments': [{
                'market_type': result.market_type.value,
                'symbol': result.symbol,
                'name': result.name_cn,
                'confidence': result.confidence
            } for result in search_results],
            'news_count': len(sorted_news),
            'news_results': sorted_news[:50]  # 限制返回数量
        }
    
    def _search_with_vector_db(self, news_query: NewsSearchQuery, vector_db,days) -> List[Dict]:
        """使用向量数据库搜索新闻"""
        try:
            # 构建搜索关键词
            search_keywords = ' '.join(news_query.primary_keywords + news_query.secondary_keywords[:3])
            print('search_keywords',search_keywords)
            # 调用向量数据库搜索
            # days = 
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            results = vector_db.semantic_search(
                query=search_keywords,
                n_results=news_query.max_results,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            # 过滤排除关键词
            filtered_results = []
            for result in results:
                content = result.get('content', '') + result.get('title', '')
                if not any(exclude_word in content for exclude_word in news_query.exclude_keywords):
                    result['market_type'] = news_query.market_type.value
                    result['symbol'] = news_query.symbol
                    filtered_results.append(result)
            
            return filtered_results
            
        except Exception as e:
            self.logger.error(f"向量数据库搜索失败: {e}")
            return []
    
    def _deduplicate_news(self, news_list: List[Dict]) -> List[Dict]:
        """新闻去重"""
        seen_hashes = set()

        # 用於存儲去重複後的結果
        deduplicated_data = []

        # 遍歷原始數據
        for item in news_list:
            # 從 metadata 中獲取 content_hash
            content_hash = item.get('metadata', {}).get('content_hash')
            
            # 如果 content_hash 存在且沒有被見過
            if content_hash and content_hash not in seen_hashes:
                # 將這個項目添加到結果列表中
                deduplicated_data.append(item)
                # 將它的 hash 添加到 seen_hashes 集合中，以便後續檢查
                seen_hashes.add(content_hash)
        return deduplicated_data
    
    def _sort_news_by_relevance(self, news_list: List[Dict], search_results: List[SearchResult]) -> List[Dict]:
        """按相关性排序新闻"""
        # 简单的相关性评分
        for news in news_list:
            score = 0
            content = (news.get('content', '') + news.get('title', '')).lower()
            
            for result in search_results:
                # 主要关键词匹配
                if result.symbol.lower() in content:
                    score += 10
                if result.name_cn in content:
                    score += 8
                
                # 次要关键词匹配
                for keyword in result.keywords[:5]:
                    if keyword.lower() in content:
                        score += 2
            
            news['relevance_score'] = score
        
        # 按相关性和时间排序
        return sorted(news_list, key=lambda x: (x.get('relevance_score', 0), x.get('published_at', '')), reverse=True)
    
    def get_market_analysis_keywords(self, market_type: MarketType, symbol: str) -> List[str]:
        """获取市场分析关键词"""
        if market_type == MarketType.FOREX:
            return self.forex_mapper.search_related_news_keywords(symbol)
        elif market_type == MarketType.FUTURES:
            return self.futures_mapper.search_related_news_keywords(symbol)
        else:
            return self.market_keywords.get(market_type, [])

# 全局实例
# enhanced_search = EnhancedMarketSearch()

if __name__ == "__main__":
    # 测试代码
    search_engine = EnhancedMarketSearch()
    
    test_queries = [
        "EURUSD汇率分析",
        "黄金GC期货走势",
        "原油CL价格预测",
        "2015.HK理想汽车",
        "大豆期货供需分析"
    ]
    
    for query in test_queries:
        print(f"\n查询: {query}")
        results = search_engine.identify_market_instrument(query)
        
        for result in results:
            print(f"市场类型: {result.market_type.value}")
            print(f"标的: {result.symbol} - {result.name_cn}")
            print(f"置信度: {result.confidence:.2f}")
            print(f"关键词: {result.keywords[:5]}...")
            print("-" * 30)