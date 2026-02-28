#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货商品合约映射数据库
支持多种期货品种的识别和相关关键词搜索
"""

import re
from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class CommodityInfo:
    """商品基础信息"""
    symbol: str  # 交易代码
    name_en: str  # 英文名称
    name_cn: str  # 中文名称
    category: str  # 分类
    exchange: str  # 交易所
    unit: str  # 交易单位
    keywords: List[str]  # 基础关键词
    supply_keywords: List[str]  # 供应相关关键词
    demand_keywords: List[str]  # 需求相关关键词
    price_factors: List[str]  # 价格影响因素

@dataclass
class FuturesContractInfo:
    """期货合约信息"""
    symbol: str  # 合约代码
    commodity: str  # 商品名称
    name_en: str  # 英文名称
    name_cn: str  # 中文名称
    category: str  # 分类
    exchange: str  # 交易所
    keywords: List[str]  # 搜索关键词
    related_news_keywords: List[str]  # 相关新闻关键词
    seasonal_factors: List[str]  # 季节性因素
    geopolitical_keywords: List[str]  # 地缘政治关键词

class FuturesCommodityMapping:
    """期货商品映射管理器"""
    
    def __init__(self):
        self.commodities = self._init_commodities()
        self.futures_contracts = self._init_futures_contracts()
        self.contract_patterns = self._init_patterns()
    
    def _init_commodities(self) -> Dict[str, CommodityInfo]:
        """初始化商品基础信息"""
        return {
            # 能源类
            'CL': CommodityInfo(
                symbol='CL',
                name_en='Crude Oil',
                name_cn='原油',
                category='energy',
                exchange='NYMEX',
                unit='1000桶',
                keywords=['原油', 'Crude Oil', 'WTI', '石油', 'Oil'],
                supply_keywords=['OPEC', '页岩油', '石油产量', '钻井数', '库存', 'EIA', 'API'],
                demand_keywords=['炼油厂', '汽油需求', '经济增长', '工业生产', '交通运输'],
                price_factors=['地缘政治', '美元指数', '经济衰退', '制裁', '战争']
            ),
            'NG': CommodityInfo(
                symbol='NG',
                name_en='Natural Gas',
                name_cn='天然气',
                category='energy',
                exchange='NYMEX',
                unit='10000MMBtu',
                keywords=['天然气', 'Natural Gas', 'NG', '燃气'],
                supply_keywords=['页岩气', '天然气产量', '管道', 'LNG', '液化天然气'],
                demand_keywords=['供暖需求', '发电需求', '工业用气', '出口需求'],
                price_factors=['天气', '库存', '季节性', '欧洲能源危机']
            ),
            
            # 贵金属
            'GC': CommodityInfo(
                symbol='GC',
                name_en='Gold',
                name_cn='黄金',
                category='precious_metals',
                exchange='COMEX',
                unit='100盎司',
                keywords=['黄金', 'Gold', 'GC', '金价', '黄金价格'],
                supply_keywords=['金矿产量', '央行售金', '回收金', '矿业公司'],
                demand_keywords=['珠宝需求', '投资需求', '央行购金', 'ETF流入'],
                price_factors=['美元指数', '实际利率', '通胀预期', '避险情绪', '地缘政治']
            ),
            'SI': CommodityInfo(
                symbol='SI',
                name_en='Silver',
                name_cn='白银',
                category='precious_metals',
                exchange='COMEX',
                unit='5000盎司',
                keywords=['白银', 'Silver', 'SI', '银价', '白银价格'],
                supply_keywords=['银矿产量', '回收银', '工业供应'],
                demand_keywords=['工业需求', '投资需求', '珠宝需求', '太阳能'],
                price_factors=['黄金价格', '工业需求', '美元指数', '经济增长']
            ),
            
            # 工业金属
            'HG': CommodityInfo(
                symbol='HG',
                name_en='Copper',
                name_cn='铜',
                category='industrial_metals',
                exchange='COMEX',
                unit='25000磅',
                keywords=['铜', 'Copper', 'HG', '铜价', '红色金属'],
                supply_keywords=['铜矿产量', '智利', '秘鲁', '中国产量', '罢工'],
                demand_keywords=['建筑需求', '电力需求', '汽车需求', '中国需求'],
                price_factors=['中国经济', '美元指数', '库存', '供应中断', '基建投资']
            ),
            
            # 农产品
            'ZS': CommodityInfo(
                symbol='ZS',
                name_en='Soybeans',
                name_cn='大豆',
                category='agriculture',
                exchange='CBOT',
                unit='5000蒲式耳',
                keywords=['大豆', 'Soybeans', 'ZS', '豆类'],
                supply_keywords=['美国产量', '巴西产量', '阿根廷产量', '种植面积', '天气'],
                demand_keywords=['中国进口', '压榨需求', '豆粕', '豆油', '饲料需求'],
                price_factors=['中美贸易', '天气', '汇率', '种植成本', '库存']
            ),
            'ZC': CommodityInfo(
                symbol='ZC',
                name_en='Corn',
                name_cn='玉米',
                category='agriculture',
                exchange='CBOT',
                unit='5000蒲式耳',
                keywords=['玉米', 'Corn', 'ZC', '谷物'],
                supply_keywords=['美国产量', '种植面积', '单产', '天气', '干旱'],
                demand_keywords=['饲料需求', '乙醇需求', '出口需求', '工业需求'],
                price_factors=['天气', '库存', '能源价格', '畜牧业', '政策补贴']
            ),
            'ZW': CommodityInfo(
                symbol='ZW',
                name_en='Wheat',
                name_cn='小麦',
                category='agriculture',
                exchange='CBOT',
                unit='5000蒲式耳',
                keywords=['小麦', 'Wheat', 'ZW', '麦类'],
                supply_keywords=['美国产量', '俄罗斯产量', '乌克兰产量', '澳洲产量'],
                demand_keywords=['面粉需求', '出口需求', '饲料替代', '食品需求'],
                price_factors=['天气', '地缘政治', '俄乌冲突', '出口限制', '库存']
            ),
            
            # 软商品
            'KC': CommodityInfo(
                symbol='KC',
                name_en='Coffee',
                name_cn='咖啡',
                category='soft_commodities',
                exchange='ICE',
                unit='37500磅',
                keywords=['咖啡', 'Coffee', 'KC', '咖啡豆'],
                supply_keywords=['巴西产量', '哥伦比亚产量', '天气', '霜冻', '干旱'],
                demand_keywords=['全球消费', '新兴市场', '咖啡店', '即溶咖啡'],
                price_factors=['天气', '汇率', '库存', '投机资金', '替代品']
            ),
            'CC': CommodityInfo(
                symbol='CC',
                name_en='Cocoa',
                name_cn='可可',
                category='soft_commodities',
                exchange='ICE',
                unit='10吨',
                keywords=['可可', 'Cocoa', 'CC', '可可豆'],
                supply_keywords=['西非产量', '加纳', '科特迪瓦', '天气', '病虫害'],
                demand_keywords=['巧克力需求', '糖果需求', '节日消费', '新兴市场'],
                price_factors=['天气', '政治稳定', '汇率', '替代品', '库存']
            )
        }
    
    def _init_futures_contracts(self) -> Dict[str, FuturesContractInfo]:
        """初始化期货合约信息"""
        contracts = {}
        
        # 能源期货
        contracts['CL'] = FuturesContractInfo(
            symbol='CL',
            commodity='Crude Oil',
            name_en='WTI Crude Oil Futures',
            name_cn='WTI原油期货',
            category='energy',
            exchange='NYMEX',
            keywords=['CL', 'WTI', '原油期货', 'Crude Oil', '石油期货'],
            related_news_keywords=[
                'OPEC', 'EIA', 'API', '石油输出国', '页岩油', '钻井数',
                '原油库存', '炼油厂', '汽油库存', '石油需求'
            ],
            seasonal_factors=['夏季驾驶季', '冬季供暖', '飓风季节'],
            geopolitical_keywords=[
                '中东局势', '伊朗制裁', '委内瑞拉', '俄罗斯制裁',
                '利比亚', '伊拉克', '沙特阿拉伯'
            ]
        )
        
        contracts['NG'] = FuturesContractInfo(
            symbol='NG',
            commodity='Natural Gas',
            name_en='Natural Gas Futures',
            name_cn='天然气期货',
            category='energy',
            exchange='NYMEX',
            keywords=['NG', '天然气期货', 'Natural Gas', '燃气期货'],
            related_news_keywords=[
                '天然气库存', 'LNG', '液化天然气', '管道', '页岩气',
                '供暖需求', '发电需求', '工业用气'
            ],
            seasonal_factors=['冬季供暖', '夏季制冷', '肩膀月份'],
            geopolitical_keywords=[
                '俄罗斯天然气', '欧洲能源', '北溪管道', '卡塔尔',
                '美国LNG出口'
            ]
        )
        
        # 贵金属期货
        contracts['GC'] = FuturesContractInfo(
            symbol='GC',
            commodity='Gold',
            name_en='Gold Futures',
            name_cn='黄金期货',
            category='precious_metals',
            exchange='COMEX',
            keywords=['GC', '黄金期货', 'Gold', '金价', 'COMEX黄金'],
            related_news_keywords=[
                '美联储', '利率', '通胀', '美元指数', 'DXY',
                '央行购金', '黄金ETF', 'SPDR Gold', '避险需求'
            ],
            seasonal_factors=['印度婚礼季', '中国春节', '西方节日'],
            geopolitical_keywords=[
                '地缘政治', '贸易战', '经济衰退', '金融危机',
                '货币政策', '量化宽松'
            ]
        )
        
        contracts['SI'] = FuturesContractInfo(
            symbol='SI',
            commodity='Silver',
            name_en='Silver Futures',
            name_cn='白银期货',
            category='precious_metals',
            exchange='COMEX',
            keywords=['SI', '白银期货', 'Silver', '银价', 'COMEX白银'],
            related_news_keywords=[
                '工业需求', '太阳能', '电子产品', '汽车工业',
                '白银ETF', '投资需求', '珠宝需求'
            ],
            seasonal_factors=['工业生产周期', '太阳能安装季'],
            geopolitical_keywords=[
                '贸易政策', '工业政策', '新能源政策', '环保政策'
            ]
        )
        
        # 工业金属期货
        contracts['HG'] = FuturesContractInfo(
            symbol='HG',
            commodity='Copper',
            name_en='Copper Futures',
            name_cn='铜期货',
            category='industrial_metals',
            exchange='COMEX',
            keywords=['HG', '铜期货', 'Copper', '铜价', 'COMEX铜'],
            related_news_keywords=[
                '中国经济', '基建投资', '房地产', '电力建设',
                '汽车产业', '智利铜矿', '秘鲁铜矿', '铜库存'
            ],
            seasonal_factors=['建筑旺季', '电力建设周期'],
            geopolitical_keywords=[
                '中美贸易', '智利政局', '秘鲁政局', '矿工罢工',
                '环保政策', '碳中和'
            ]
        )
        
        # 农产品期货
        contracts['ZS'] = FuturesContractInfo(
            symbol='ZS',
            commodity='Soybeans',
            name_en='Soybean Futures',
            name_cn='大豆期货',
            category='agriculture',
            exchange='CBOT',
            keywords=['ZS', '大豆期货', 'Soybeans', '豆类期货', 'CBOT大豆'],
            related_news_keywords=[
                '中美贸易', '中国进口', '巴西大豆', '阿根廷大豆',
                '种植面积', '天气预报', '干旱', '洪涝', 'USDA报告'
            ],
            seasonal_factors=['种植季', '生长季', '收获季', '南美收获'],
            geopolitical_keywords=[
                '中美贸易战', '关税政策', '进口配额', '转基因政策',
                '巴西政策', '阿根廷政策'
            ]
        )
        
        return contracts
    
    def _init_patterns(self) -> List[str]:
        """初始化期货合约识别模式"""
        return [
            r'[A-Z]{1,2}\d{4}',     # CL2024, GC2024
            r'[A-Z]{1,2}\d{2}',      # CL24, GC24
            r'[A-Z]{1,4}',          # CL, GC, GOLD
        ]
    
    def identify_futures_contract(self, text: str) -> List[str]:
        """识别文本中的期货合约"""
        identified_contracts = set()
        
        # 直接匹配合约代码
        for symbol in self.futures_contracts.keys():
            if symbol in text.upper():
                identified_contracts.add(symbol)
        
        # 使用正则表达式匹配
        for pattern in self.contract_patterns:
            matches = re.findall(pattern, text.upper())
            for match in matches:
                # 提取基础合约代码
                base_symbol = re.sub(r'\d+', '', match)
                if base_symbol in self.futures_contracts:
                    identified_contracts.add(base_symbol)
        
        # 检查中文名称和关键词
        for symbol, contract_info in self.futures_contracts.items():
            for keyword in contract_info.keywords:
                if keyword in text:
                    identified_contracts.add(symbol)
        
        return list(identified_contracts)
    
    def get_search_keywords(self, symbol: str) -> List[str]:
        """获取期货合约的搜索关键词"""
        if symbol not in self.futures_contracts:
            return []
        
        contract_info = self.futures_contracts[symbol]
        commodity_info = self.commodities.get(symbol)
        
        keywords = []
        
        # 添加合约关键词
        keywords.extend(contract_info.keywords)
        keywords.extend(contract_info.related_news_keywords)
        keywords.extend(contract_info.seasonal_factors)
        keywords.extend(contract_info.geopolitical_keywords)
        
        # 添加商品基础关键词
        if commodity_info:
            keywords.extend(commodity_info.keywords)
            keywords.extend(commodity_info.supply_keywords)
            keywords.extend(commodity_info.demand_keywords)
            keywords.extend(commodity_info.price_factors)
        
        return list(set(keywords))
    
    def get_contract_info(self, symbol: str) -> Optional[FuturesContractInfo]:
        """获取期货合约详细信息"""
        return self.futures_contracts.get(symbol)
    
    def get_commodity_info(self, symbol: str) -> Optional[CommodityInfo]:
        """获取商品详细信息"""
        return self.commodities.get(symbol)
    
    def get_all_contracts(self) -> List[str]:
        """获取所有支持的期货合约"""
        return list(self.futures_contracts.keys())
    
    def get_contracts_by_category(self, category: str) -> List[str]:
        """按分类获取期货合约"""
        return [symbol for symbol, info in self.futures_contracts.items() 
                if info.category == category]
    
    def search_related_news_keywords(self, symbol: str) -> List[str]:
        """获取与期货合约相关的新闻搜索关键词"""
        if symbol not in self.futures_contracts:
            return []
        
        contract_info = self.futures_contracts[symbol]
        commodity_info = self.commodities.get(symbol)
        
        keywords = []
        
        # 基础关键词
        keywords.extend(contract_info.keywords)
        keywords.extend(contract_info.related_news_keywords)
        
        # 供需关键词
        if commodity_info:
            keywords.extend(commodity_info.supply_keywords)
            keywords.extend(commodity_info.demand_keywords)
            keywords.extend(commodity_info.price_factors)
        
        # 市场报告关键词
        market_reports = [
            'USDA', 'EIA', 'API', 'OPEC', 'IEA', 'CFTC',
            '库存报告', '产量报告', '需求预测', '价格预测'
        ]
        keywords.extend(market_reports)
        
        # 宏观经济关键词
        macro_keywords = [
            '美元指数', 'DXY', '通胀', '经济增长', 'GDP',
            '利率', '货币政策', '贸易政策', '关税'
        ]
        keywords.extend(macro_keywords)
        
        return list(set(keywords))
    
    def get_seasonal_analysis(self, symbol: str) -> Dict[str, List[str]]:
        """获取季节性分析信息"""
        if symbol not in self.futures_contracts:
            return {}
        
        contract_info = self.futures_contracts[symbol]
        
        return {
            'seasonal_factors': contract_info.seasonal_factors,
            'category': contract_info.category,
            'exchange': contract_info.exchange
        }

# 全局实例
futures_mapper = FuturesCommodityMapping()

if __name__ == "__main__":
    # 测试代码
    mapper = FuturesCommodityMapping()
    
    # 测试期货合约识别
    test_texts = [
        "CL原油期货今日上涨",
        "黄金GC合约分析",
        "大豆ZS期货走势",
        "WTI原油价格预测",
        "COMEX黄金期货"
    ]
    
    for text in test_texts:
        contracts = mapper.identify_futures_contract(text)
        print(f"文本: {text}")
        print(f"识别的期货合约: {contracts}")
        for contract in contracts:
            keywords = mapper.get_search_keywords(contract)
            print(f"{contract} 搜索关键词: {keywords[:10]}...")  # 只显示前10个
        print("-" * 50)
    
    # 测试分类查询
    print("\n按分类查询:")
    categories = ['energy', 'precious_metals', 'agriculture']
    for category in categories:
        contracts = mapper.get_contracts_by_category(category)
        print(f"{category}: {contracts}")