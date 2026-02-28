#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义搜索优化器
专门针对外汇和期货市场的语义搜索优化
"""

import re
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
import jieba
import jieba.posseg as pseg
from collections import defaultdict
import math

# 导入映射模块
from forex_currency_mapping import forex_mapper
from futures_commodity_mapping import futures_mapper
from enhanced_market_search import MarketType

@dataclass
class KeywordWeight:
    """关键词权重"""
    keyword: str
    weight: float
    category: str  # primary, secondary, context
    market_type: MarketType

@dataclass
class SearchContext:
    """搜索上下文"""
    market_type: MarketType
    symbol: str
    primary_keywords: List[str]
    secondary_keywords: List[str]
    context_keywords: List[str]
    exclude_keywords: List[str]
    synonym_map: Dict[str, List[str]]

class SemanticSearchOptimizer:
    """语义搜索优化器"""
    
    def __init__(self):
        self.forex_mapper = forex_mapper
        self.futures_mapper = futures_mapper
        
        # 初始化jieba分词
        self._init_jieba_dict()
        
        # 权重配置
        self.weight_config = {
            'primary': 1.0,      # 主要关键词
            'secondary': 0.7,    # 次要关键词
            'context': 0.5,      # 上下文关键词
            'synonym': 0.8,      # 同义词
            'related': 0.6,      # 相关词
            'exclude': -2.0      # 排除词（负权重）
        }
        
        # 同义词映射
        self.synonym_maps = self._init_synonym_maps()
        
        # 上下文关键词
        self.context_keywords = self._init_context_keywords()
    
    def _init_jieba_dict(self):
        """初始化jieba词典"""
        # 添加外汇相关词汇
        forex_terms = [
            ('EURUSD', 10, 'n'), ('GBPUSD', 10, 'n'), ('USDJPY', 10, 'n'),
            ('外汇', 8, 'n'), ('汇率', 8, 'n'), ('货币对', 8, 'n'),
            ('美联储', 9, 'n'), ('欧央行', 9, 'n'), ('日央行', 9, 'n')
        ]
        
        # 添加期货相关词汇
        futures_terms = [
            ('原油期货', 10, 'n'), ('黄金期货', 10, 'n'), ('大豆期货', 10, 'n'),
            ('WTI', 9, 'n'), ('布伦特', 9, 'n'), ('COMEX', 9, 'n'),
            ('NYMEX', 9, 'n'), ('CBOT', 9, 'n')
        ]
        
        for term, freq, tag in forex_terms + futures_terms:
            jieba.add_word(term, freq, tag)
    
    def _init_synonym_maps(self) -> Dict[str, List[str]]:
        """初始化同义词映射"""
        return {
            # 外汇同义词
            '美元': ['USD', 'Dollar', '美金'],
            '欧元': ['EUR', 'Euro'],
            '英镑': ['GBP', 'Pound', '镑'],
            '日元': ['JPY', 'Yen'],
            '澳元': ['AUD', 'Australian Dollar'],
            '加元': ['CAD', 'Canadian Dollar'],
            '瑞郎': ['CHF', 'Swiss Franc'],
            '人民币': ['CNY', 'Yuan', 'RMB'],
            
            # 央行同义词
            '美联储': ['Fed', 'Federal Reserve', '联储'],
            '欧央行': ['ECB', 'European Central Bank'],
            '日央行': ['BOJ', 'Bank of Japan'],
            '英央行': ['BOE', 'Bank of England'],
            '澳联储': ['RBA', 'Reserve Bank of Australia'],
            
            # 期货同义词
            '原油': ['石油', 'Oil', 'Crude', 'WTI', 'Brent'],
            '黄金': ['Gold', '金价', '贵金属'],
            '白银': ['Silver', '银价'],
            '铜': ['Copper', '红色金属'],
            '大豆': ['Soybeans', '豆类'],
            '玉米': ['Corn', '谷物'],
            '小麦': ['Wheat', '麦类'],
            '天然气': ['Natural Gas', 'NG', '燃气'],
            
            # 机构同义词
            'OPEC': ['石油输出国组织', '欧佩克'],
            'EIA': ['美国能源信息署'],
            'API': ['美国石油协会'],
            'USDA': ['美国农业部'],
            'IEA': ['国际能源署'],
            
            # 经济指标同义词
            'GDP': ['国内生产总值', '经济增长'],
            'CPI': ['消费者价格指数', '通胀'],
            'PPI': ['生产者价格指数'],
            'PMI': ['采购经理人指数'],
            'NFP': ['非农就业', '非农数据'],
        }
    
    def _init_context_keywords(self) -> Dict[MarketType, Dict[str, List[str]]]:
        """初始化上下文关键词"""
        return {
            MarketType.FOREX: {
                'policy': ['货币政策', '利率决议', '量化宽松', 'QE', '加息', '降息'],
                'economic': ['经济数据', 'GDP', 'CPI', '就业', '贸易平衡', '零售销售'],
                'market': ['汇率', '外汇储备', '汇率干预', '资本流动'],
                'geopolitical': ['贸易战', '制裁', '地缘政治', '国际关系']
            },
            MarketType.FUTURES: {
                'supply': ['产量', '库存', '供应', '开采', '种植', '收获'],
                'demand': ['需求', '消费', '进口', '出口', '工业需求'],
                'weather': ['天气', '干旱', '洪涝', '霜冻', '厄尔尼诺'],
                'policy': ['政策', '补贴', '关税', '配额', '储备'],
                'reports': ['报告', 'USDA', 'EIA', 'API', 'OPEC', 'IEA']
            }
        }
    
    def optimize_search_query(self, query: str, market_type: MarketType = None, symbol: str = None) -> SearchContext:
        """优化搜索查询"""
        # 1. 分词和词性标注
        words = self._segment_text(query)
        
        # 2. 识别市场类型和标的（如果未提供）
        if not market_type or not symbol:
            detected_market, detected_symbol = self._detect_market_and_symbol(query, words)
            market_type = market_type or detected_market
            symbol = symbol or detected_symbol
        
        # 3. 提取和分类关键词
        primary_keywords = self._extract_primary_keywords(words, market_type, symbol)
        secondary_keywords = self._extract_secondary_keywords(words, market_type)
        context_keywords = self._extract_context_keywords(words, market_type)
        exclude_keywords = self._extract_exclude_keywords(words, market_type)
        
        # 4. 构建同义词映射
        synonym_map = self._build_synonym_map(primary_keywords + secondary_keywords)
        
        return SearchContext(
            market_type=market_type,
            symbol=symbol,
            primary_keywords=primary_keywords,
            secondary_keywords=secondary_keywords,
            context_keywords=context_keywords,
            exclude_keywords=exclude_keywords,
            synonym_map=synonym_map
        )
    
    def _segment_text(self, text: str) -> List[Tuple[str, str]]:
        """分词和词性标注"""
        return [(word, flag) for word, flag in pseg.cut(text)]
    
    def _detect_market_and_symbol(self, query: str, words: List[Tuple[str, str]]) -> Tuple[MarketType, str]:
        """检测市场类型和标的"""
        # 检查外汇
        forex_pairs = self.forex_mapper.identify_forex_pair(query)
        if forex_pairs:
            return MarketType.FOREX, forex_pairs[0]
        
        # 检查期货
        futures_contracts = self.futures_mapper.identify_futures_contract(query)
        if futures_contracts:
            return MarketType.FUTURES, futures_contracts[0]
        
        # 基于关键词推断
        forex_score = sum(1 for word, _ in words if any(kw in word for kw in ['汇率', '外汇', '货币', '央行']))
        futures_score = sum(1 for word, _ in words if any(kw in word for kw in ['期货', '商品', '合约', '库存']))
        
        if forex_score > futures_score:
            return MarketType.FOREX, "UNKNOWN"
        elif futures_score > 0:
            return MarketType.FUTURES, "UNKNOWN"
        else:
            return MarketType.UNKNOWN, "UNKNOWN"
    
    def _extract_primary_keywords(self, words: List[Tuple[str, str]], market_type: MarketType, symbol: str) -> List[str]:
        """提取主要关键词"""
        primary_keywords = []
        
        # 添加标的相关关键词
        if symbol != "UNKNOWN":
            primary_keywords.append(symbol)
            
            if market_type == MarketType.FOREX and symbol in self.forex_mapper.forex_pairs:
                pair_info = self.forex_mapper.forex_pairs[symbol]
                primary_keywords.extend(pair_info.keywords[:3])
            elif market_type == MarketType.FUTURES and symbol in self.futures_mapper.futures_contracts:
                contract_info = self.futures_mapper.futures_contracts[symbol]
                primary_keywords.extend(contract_info.keywords[:3])
        
        # 从分词结果中提取重要词汇
        important_pos = ['n', 'nr', 'ns', 'nt', 'nz']  # 名词类
        for word, pos in words:
            if pos in important_pos and len(word) > 1:
                # 检查是否为重要的市场术语
                if self._is_important_market_term(word, market_type):
                    primary_keywords.append(word)
        
        return list(set(primary_keywords))
    
    def _extract_secondary_keywords(self, words: List[Tuple[str, str]], market_type: MarketType) -> List[str]:
        """提取次要关键词"""
        secondary_keywords = []
        
        # 添加市场通用关键词
        market_general_keywords = {
            MarketType.FOREX: ['汇率', '外汇', '货币', '央行', '利率'],
            MarketType.FUTURES: ['期货', '商品', '合约', '价格', '库存']
        }
        
        if market_type in market_general_keywords:
            secondary_keywords.extend(market_general_keywords[market_type])
        
        # 从分词结果中提取
        for word, pos in words:
            if pos in ['v', 'a', 'ad'] and len(word) > 1:  # 动词、形容词
                if self._is_relevant_term(word, market_type):
                    secondary_keywords.append(word)
        
        return list(set(secondary_keywords))
    
    def _extract_context_keywords(self, words: List[Tuple[str, str]], market_type: MarketType) -> List[str]:
        """提取上下文关键词"""
        context_keywords = []
        
        if market_type in self.context_keywords:
            for category, keywords in self.context_keywords[market_type].items():
                for word, _ in words:
                    if any(kw in word for kw in keywords):
                        context_keywords.extend(keywords[:2])  # 添加相关的上下文关键词
                        break
        
        return list(set(context_keywords))
    
    def _extract_exclude_keywords(self, words: List[Tuple[str, str]], market_type: MarketType) -> List[str]:
        """提取排除关键词"""
        exclude_map = {
            MarketType.FOREX: ['股票', '期货', '商品', '合约'],
            MarketType.FUTURES: ['股票', '外汇', '汇率', '货币对'],
            MarketType.STOCK: ['外汇', '期货', '商品', '汇率']
        }
        
        return exclude_map.get(market_type, [])
    
    def _build_synonym_map(self, keywords: List[str]) -> Dict[str, List[str]]:
        """构建同义词映射"""
        synonym_map = {}
        
        for keyword in keywords:
            if keyword in self.synonym_maps:
                synonym_map[keyword] = self.synonym_maps[keyword]
            else:
                # 查找反向映射
                for main_word, synonyms in self.synonym_maps.items():
                    if keyword in synonyms:
                        synonym_map[keyword] = [main_word] + [s for s in synonyms if s != keyword]
                        break
        
        return synonym_map
    
    def _is_important_market_term(self, word: str, market_type: MarketType) -> bool:
        """判断是否为重要的市场术语"""
        important_terms = {
            MarketType.FOREX: {
                '美元', '欧元', '英镑', '日元', '澳元', '加元', '瑞郎', '人民币',
                '美联储', '欧央行', '日央行', '英央行', '澳联储',
                '汇率', '外汇', '货币政策', '利率', '量化宽松'
            },
            MarketType.FUTURES: {
                '原油', '黄金', '白银', '铜', '大豆', '玉米', '小麦', '天然气',
                '期货', '商品', '合约', 'OPEC', 'EIA', 'USDA', 'API',
                '库存', '产量', '供需', '天气'
            }
        }
        
        return word in important_terms.get(market_type, set())
    
    def _is_relevant_term(self, word: str, market_type: MarketType) -> bool:
        """判断是否为相关术语"""
        relevant_terms = {
            MarketType.FOREX: {'上涨', '下跌', '走强', '走弱', '贬值', '升值', '波动'},
            MarketType.FUTURES: {'上涨', '下跌', '涨价', '跌价', '供应', '需求', '短缺', '过剩'}
        }
        
        return word in relevant_terms.get(market_type, set())
    
    def calculate_relevance_score(self, text: str, search_context: SearchContext) -> float:
        """计算文本相关性得分"""
        score = 0.0
        text_lower = text.lower()
        
        # 主要关键词匹配
        for keyword in search_context.primary_keywords:
            if keyword.lower() in text_lower:
                score += self.weight_config['primary']
                
                # 同义词匹配
                if keyword in search_context.synonym_map:
                    for synonym in search_context.synonym_map[keyword]:
                        if synonym.lower() in text_lower:
                            score += self.weight_config['synonym']
        
        # 次要关键词匹配
        for keyword in search_context.secondary_keywords:
            if keyword.lower() in text_lower:
                score += self.weight_config['secondary']
        
        # 上下文关键词匹配
        for keyword in search_context.context_keywords:
            if keyword.lower() in text_lower:
                score += self.weight_config['context']
        
        # 排除关键词惩罚
        for keyword in search_context.exclude_keywords:
            if keyword.lower() in text_lower:
                score += self.weight_config['exclude']
        
        # 标的符号匹配（高权重）
        if search_context.symbol != "UNKNOWN" and search_context.symbol.lower() in text_lower:
            score += 2.0
        
        return max(0, score)  # 确保得分非负
    
    def expand_search_terms(self, search_context: SearchContext) -> List[str]:
        """扩展搜索词汇"""
        expanded_terms = []
        
        # 添加原始关键词
        expanded_terms.extend(search_context.primary_keywords)
        expanded_terms.extend(search_context.secondary_keywords[:5])  # 限制次要关键词数量
        
        # 添加同义词
        for keyword, synonyms in search_context.synonym_map.items():
            expanded_terms.extend(synonyms[:2])  # 每个关键词最多添加2个同义词
        
        # 添加上下文关键词
        expanded_terms.extend(search_context.context_keywords[:3])  # 限制上下文关键词数量
        
        return list(set(expanded_terms))
    
    def generate_search_query_string(self, search_context: SearchContext) -> str:
        """生成搜索查询字符串"""
        query_parts = []
        
        # 主要关键词（必须包含）
        if search_context.primary_keywords:
            primary_query = ' OR '.join(f'"{kw}"' for kw in search_context.primary_keywords[:3])
            query_parts.append(f"({primary_query})")
        
        # 次要关键词（可选）
        if search_context.secondary_keywords:
            secondary_query = ' OR '.join(search_context.secondary_keywords[:3])
            query_parts.append(f"({secondary_query})")
        
        # 排除关键词
        if search_context.exclude_keywords:
            exclude_query = ' '.join(f'-"{kw}"' for kw in search_context.exclude_keywords)
            query_parts.append(exclude_query)
        
        return ' AND '.join(query_parts)

# 全局实例
semantic_optimizer = SemanticSearchOptimizer()

if __name__ == "__main__":
    # 测试代码
    optimizer = SemanticSearchOptimizer()
    
    test_queries = [
        "EURUSD汇率走势分析",
        "黄金期货价格预测",
        "原油库存报告影响",
        "美联储利率决议",
        "大豆供需平衡表"
    ]
    
    for query in test_queries:
        print(f"\n查询: {query}")
        context = optimizer.optimize_search_query(query)
        
        print(f"市场类型: {context.market_type.value}")
        print(f"标的: {context.symbol}")
        print(f"主要关键词: {context.primary_keywords}")
        print(f"次要关键词: {context.secondary_keywords}")
        print(f"上下文关键词: {context.context_keywords}")
        print(f"排除关键词: {context.exclude_keywords}")
        
        # 生成搜索查询
        search_query = optimizer.generate_search_query_string(context)
        print(f"搜索查询: {search_query}")
        print("-" * 50)