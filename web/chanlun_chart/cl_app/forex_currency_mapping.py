#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外汇货币对映射数据库
支持多种格式的货币对识别和相关关键词搜索
"""

import re
from typing import Dict, List, Set, Optional
from dataclasses import dataclass

@dataclass
class CurrencyInfo:
    """货币信息"""
    code: str  # 货币代码
    name_en: str  # 英文名称
    name_cn: str  # 中文名称
    country: str  # 国家
    central_bank: str  # 央行
    keywords: List[str]  # 相关关键词

@dataclass
class ForexPairInfo:
    """外汇货币对信息"""
    pair: str  # 标准格式 EURUSD
    base_currency: str  # 基础货币
    quote_currency: str  # 计价货币
    name_en: str  # 英文名称
    name_cn: str  # 中文名称
    category: str  # 分类：major/minor/exotic
    keywords: List[str]  # 搜索关键词
    related_news_keywords: List[str]  # 相关新闻关键词

class ForexCurrencyMapping:
    """外汇货币对映射管理器"""
    
    def __init__(self):
        self.currencies = self._init_currencies()
        self.forex_pairs = self._init_forex_pairs()
        self.pair_patterns = self._init_patterns()
    
    def _init_currencies(self) -> Dict[str, CurrencyInfo]:
        """初始化货币信息"""
        return {
            'USD': CurrencyInfo(
                code='USD',
                name_en='US Dollar',
                name_cn='美元',
                country='美国',
                central_bank='美联储',
                keywords=['美元', 'USD', 'Dollar', '美联储', 'Fed', 'Federal Reserve']
            ),
            'EUR': CurrencyInfo(
                code='EUR',
                name_en='Euro',
                name_cn='欧元',
                country='欧盟',
                central_bank='欧央行',
                keywords=['欧元', 'EUR', 'Euro', '欧央行', 'ECB', 'European Central Bank']
            ),
            'GBP': CurrencyInfo(
                code='GBP',
                name_en='British Pound',
                name_cn='英镑',
                country='英国',
                central_bank='英央行',
                keywords=['英镑', 'GBP', 'Pound', '英央行', 'BOE', 'Bank of England']
            ),
            'JPY': CurrencyInfo(
                code='JPY',
                name_en='Japanese Yen',
                name_cn='日元',
                country='日本',
                central_bank='日央行',
                keywords=['日元', 'JPY', 'Yen', '日央行', 'BOJ', 'Bank of Japan']
            ),
            'AUD': CurrencyInfo(
                code='AUD',
                name_en='Australian Dollar',
                name_cn='澳元',
                country='澳大利亚',
                central_bank='澳联储',
                keywords=['澳元', 'AUD', 'Australian Dollar', '澳联储', 'RBA', 'Reserve Bank of Australia']
            ),
            'CAD': CurrencyInfo(
                code='CAD',
                name_en='Canadian Dollar',
                name_cn='加元',
                country='加拿大',
                central_bank='加央行',
                keywords=['加元', 'CAD', 'Canadian Dollar', '加央行', 'BOC', 'Bank of Canada']
            ),
            'CHF': CurrencyInfo(
                code='CHF',
                name_en='Swiss Franc',
                name_cn='瑞郎',
                country='瑞士',
                central_bank='瑞士央行',
                keywords=['瑞郎', 'CHF', 'Swiss Franc', '瑞士央行', 'SNB', 'Swiss National Bank']
            ),
            'NZD': CurrencyInfo(
                code='NZD',
                name_en='New Zealand Dollar',
                name_cn='纽元',
                country='新西兰',
                central_bank='新西兰联储',
                keywords=['纽元', 'NZD', 'New Zealand Dollar', '新西兰联储', 'RBNZ']
            ),
            'CNY': CurrencyInfo(
                code='CNY',
                name_en='Chinese Yuan',
                name_cn='人民币',
                country='中国',
                central_bank='中国人民银行',
                keywords=['人民币', 'CNY', 'Yuan', '央行', 'PBOC', '中国人民银行']
            )
        }
    
    def _init_forex_pairs(self) -> Dict[str, ForexPairInfo]:
        """初始化外汇货币对信息"""
        pairs = {
            # 主要货币对 (Major Pairs)
            'EURUSD': ForexPairInfo(
                pair='EURUSD',
                base_currency='EUR',
                quote_currency='USD',
                name_en='Euro/US Dollar',
                name_cn='欧元/美元',
                category='major',
                keywords=['EURUSD', 'EUR/USD', '欧美', '欧元美元'],
                related_news_keywords=['欧央行', '美联储', 'ECB', 'Fed', '欧元区', '美国经济']
            ),
            'GBPUSD': ForexPairInfo(
                pair='GBPUSD',
                base_currency='GBP',
                quote_currency='USD',
                name_en='British Pound/US Dollar',
                name_cn='英镑/美元',
                category='major',
                keywords=['GBPUSD', 'GBP/USD', '镑美', '英镑美元'],
                related_news_keywords=['英央行', '美联储', 'BOE', 'Fed', '英国经济', '脱欧']
            ),
            'USDJPY': ForexPairInfo(
                pair='USDJPY',
                base_currency='USD',
                quote_currency='JPY',
                name_en='US Dollar/Japanese Yen',
                name_cn='美元/日元',
                category='major',
                keywords=['USDJPY', 'USD/JPY', '美日', '美元日元'],
                related_news_keywords=['美联储', '日央行', 'Fed', 'BOJ', '日本经济', '汇率干预']
            ),
            'USDCHF': ForexPairInfo(
                pair='USDCHF',
                base_currency='USD',
                quote_currency='CHF',
                name_en='US Dollar/Swiss Franc',
                name_cn='美元/瑞郎',
                category='major',
                keywords=['USDCHF', 'USD/CHF', '美瑞', '美元瑞郎'],
                related_news_keywords=['美联储', '瑞士央行', 'Fed', 'SNB', '避险货币']
            ),
            'AUDUSD': ForexPairInfo(
                pair='AUDUSD',
                base_currency='AUD',
                quote_currency='USD',
                name_en='Australian Dollar/US Dollar',
                name_cn='澳元/美元',
                category='major',
                keywords=['AUDUSD', 'AUD/USD', '澳美', '澳元美元'],
                related_news_keywords=['澳联储', '美联储', 'RBA', 'Fed', '澳洲经济', '商品价格']
            ),
            'USDCAD': ForexPairInfo(
                pair='USDCAD',
                base_currency='USD',
                quote_currency='CAD',
                name_en='US Dollar/Canadian Dollar',
                name_cn='美元/加元',
                category='major',
                keywords=['USDCAD', 'USD/CAD', '美加', '美元加元'],
                related_news_keywords=['美联储', '加央行', 'Fed', 'BOC', '原油价格', '加拿大经济']
            ),
            'NZDUSD': ForexPairInfo(
                pair='NZDUSD',
                base_currency='NZD',
                quote_currency='USD',
                name_en='New Zealand Dollar/US Dollar',
                name_cn='纽元/美元',
                category='major',
                keywords=['NZDUSD', 'NZD/USD', '纽美', '纽元美元'],
                related_news_keywords=['新西兰联储', '美联储', 'RBNZ', 'Fed', '新西兰经济']
            ),
            
            # 交叉货币对 (Cross Pairs)
            'EURGBP': ForexPairInfo(
                pair='EURGBP',
                base_currency='EUR',
                quote_currency='GBP',
                name_en='Euro/British Pound',
                name_cn='欧元/英镑',
                category='minor',
                keywords=['EURGBP', 'EUR/GBP', '欧英', '欧元英镑'],
                related_news_keywords=['欧央行', '英央行', 'ECB', 'BOE', '脱欧', '欧元区']
            ),
            'EURJPY': ForexPairInfo(
                pair='EURJPY',
                base_currency='EUR',
                quote_currency='JPY',
                name_en='Euro/Japanese Yen',
                name_cn='欧元/日元',
                category='minor',
                keywords=['EURJPY', 'EUR/JPY', '欧日', '欧元日元'],
                related_news_keywords=['欧央行', '日央行', 'ECB', 'BOJ', '欧元区', '日本经济']
            ),
            'GBPJPY': ForexPairInfo(
                pair='GBPJPY',
                base_currency='GBP',
                quote_currency='JPY',
                name_en='British Pound/Japanese Yen',
                name_cn='英镑/日元',
                category='minor',
                keywords=['GBPJPY', 'GBP/JPY', '镑日', '英镑日元'],
                related_news_keywords=['英央行', '日央行', 'BOE', 'BOJ', '英国经济', '日本经济']
            ),
            
            # 新兴市场货币对
            'USDCNY': ForexPairInfo(
                pair='USDCNY',
                base_currency='USD',
                quote_currency='CNY',
                name_en='US Dollar/Chinese Yuan',
                name_cn='美元/人民币',
                category='exotic',
                keywords=['USDCNY', 'USD/CNY', '美人', '美元人民币', '离岸人民币'],
                related_news_keywords=['美联储', '央行', 'Fed', 'PBOC', '中美贸易', '人民币汇率']
            )
        }
        
        return pairs
    
    def _init_patterns(self) -> List[str]:
        """初始化货币对识别模式"""
        return [
            r'[A-Z]{6}',           # EURUSD
            r'[A-Z]{3}/[A-Z]{3}',  # EUR/USD
            r'[A-Z]{3}-[A-Z]{3}',  # EUR-USD
            r'[A-Z]{3}\s[A-Z]{3}', # EUR USD
        ]
    
    def identify_forex_pair(self, text: str) -> List[str]:
        """识别文本中的货币对"""
        identified_pairs = set()
        
        # 使用正则表达式匹配
        for pattern in self.pair_patterns:
            print('pattern',pattern)
            matches = re.findall(pattern, text.upper())
            for match in matches:
                # 标准化格式
                normalized = re.sub(r'[^A-Z]', '', match)
                if len(normalized) == 6:
                    base = normalized[:3]
                    quote = normalized[3:]
                    pair = f"{base}{quote}"
                    if pair in self.forex_pairs:
                        identified_pairs.add(pair)
        
        # 检查中文名称
        for pair_code, pair_info in self.forex_pairs.items():
            for keyword in pair_info.keywords:
                if keyword in text:
                    identified_pairs.add(pair_code)
        
        return list(identified_pairs)
    
    def get_search_keywords(self, pair: str) -> List[str]:
        """获取货币对的搜索关键词"""
        if pair not in self.forex_pairs:
            return []
        
        pair_info = self.forex_pairs[pair]
        keywords = []
        
        # 添加货币对关键词
        keywords.extend(pair_info.keywords)
        keywords.extend(pair_info.related_news_keywords)
        
        # 添加基础货币和计价货币的关键词
        base_currency = self.currencies.get(pair_info.base_currency)
        quote_currency = self.currencies.get(pair_info.quote_currency)
        
        if base_currency:
            keywords.extend(base_currency.keywords)
        if quote_currency:
            keywords.extend(quote_currency.keywords)
        
        return list(set(keywords))
    
    def get_pair_info(self, pair: str) -> Optional[ForexPairInfo]:
        """获取货币对详细信息"""
        return self.forex_pairs.get(pair)
    
    def get_all_pairs(self) -> List[str]:
        """获取所有支持的货币对"""
        return list(self.forex_pairs.keys())
    
    def get_pairs_by_category(self, category: str) -> List[str]:
        """按分类获取货币对"""
        return [pair for pair, info in self.forex_pairs.items() 
                if info.category == category]
    
    def search_related_news_keywords(self, pair: str) -> List[str]:
        """获取与货币对相关的新闻搜索关键词"""
        if pair not in self.forex_pairs:
            return []
        
        pair_info = self.forex_pairs[pair]
        keywords = []
        
        # 基础关键词
        keywords.extend(pair_info.keywords)
        keywords.extend(pair_info.related_news_keywords)
        
        # 经济指标关键词
        economic_indicators = [
            'GDP', 'CPI', 'PPI', 'PMI', '非农就业', 'NFP',
            '零售销售', '工业生产', '贸易平衡', '消费者信心',
            '利率决议', '货币政策', '量化宽松', 'QE'
        ]
        keywords.extend(economic_indicators)
        
        # 市场情绪关键词
        market_sentiment = [
            '避险情绪', '风险偏好', '美元指数', 'DXY',
            '地缘政治', '贸易战', '通胀预期', '经济衰退'
        ]
        keywords.extend(market_sentiment)
        
        return list(set(keywords))

# 全局实例
forex_mapper = ForexCurrencyMapping()

if __name__ == "__main__":
    # 测试代码
    mapper = ForexCurrencyMapping()
    
    # 测试货币对识别
    test_texts = [
        "EURUSD今日上涨",
        "EUR/USD汇率走势",
        "欧美货币对分析",
        "美联储政策影响USD"
    ]
    
    for text in test_texts:
        pairs = mapper.identify_forex_pair(text)
        print(f"文本: {text}")
        print(f"识别的货币对: {pairs}")
        for pair in pairs:
            keywords = mapper.get_search_keywords(pair)
            print(f"{pair} 搜索关键词: {keywords[:10]}...")  # 只显示前10个
        print("-" * 50)