#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能新闻搜索系统
支持根据股票代码或公司名称自动化精确查找相关新闻

功能特性:
1. 股票代码格式识别和标准化 (支持 2015.HK, R:2015.HK, 02015 等格式)
2. 股票代码到公司名称的映射
3. 基于语义搜索的新闻检索
4. 智能关键词匹配和过滤
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from datetime import datetime, timedelta

# 导入项目内部模块
try:
    from .news_vector_db import NewsVectorDB
    # from .akshare_utils import AKShareProvider
except ImportError:
    # 处理直接运行时的导入
    from news_vector_db import NewsVectorDB
    from akshare_utils import AKShareProvider

logger = logging.getLogger(__name__)

@dataclass
class StockInfo:
    """股票信息数据类"""
    code: str  # 标准化后的股票代码
    name: str  # 公司名称
    exchange: str  # 交易所
    market_type: str  # 市场类型 (HK, US, CN)
    original_input: str  # 原始输入
    aliases: List[str]  # 别名列表

class StockCodeMapper:
    """股票代码映射器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.akshare_provider = AKShareProvider()
        self.predefined_mappings = {}
        self.code_patterns = {}
        self.exchange_info = {}
        
        # 加载配置文件
        self._load_config(config_file)
    
    def _load_config(self, config_file: Optional[str] = None):
        """加载股票映射配置文件"""
        if config_file is None:
            # 默认配置文件路径
            config_file = Path(__file__).parent / "stock_mappings.json"
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 加载股票映射数据
            mappings = config.get('mappings', {})
            
            # 处理港股映射
            for code, info in mappings.get('hk_stocks', {}).items():
                stock_info = StockInfo(
                    code=code,
                    name=info['name'],
                    exchange=info['exchange'],
                    market_type=info['market_type'],
                    original_input=code,
                    aliases=info.get('aliases', [])
                )
                # 添加多种代码格式的映射
                self.predefined_mappings[code] = stock_info
                # 添加去掉前导零的版本
                short_code = code.lstrip('0')
                if short_code and short_code != code:
                    self.predefined_mappings[short_code] = stock_info
            
            # 处理美股映射
            for code, info in mappings.get('us_stocks', {}).items():
                stock_info = StockInfo(
                    code=code,
                    name=info['name'],
                    exchange=info['exchange'],
                    market_type=info['market_type'],
                    original_input=code,
                    aliases=info.get('aliases', [])
                )
                self.predefined_mappings[code] = stock_info
            
            # 处理A股映射
            for code, info in mappings.get('cn_stocks', {}).items():
                stock_info = StockInfo(
                    code=code,
                    name=info['name'],
                    exchange=info['exchange'],
                    market_type=info['market_type'],
                    original_input=code,
                    aliases=info.get('aliases', [])
                )
                self.predefined_mappings[code] = stock_info
            
            # 加载代码模式和交易所信息
            self.code_patterns = config.get('code_patterns', {})
            self.exchange_info = config.get('exchange_info', {})
            
            logger.info(f"✅ 成功加载股票映射配置: {len(self.predefined_mappings)} 个股票")
            
        except FileNotFoundError:
            logger.warning(f"⚠️ 配置文件未找到: {config_file}，使用默认映射")
            self._load_default_mappings()
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {e}，使用默认映射")
            self._load_default_mappings()
    
    def _load_default_mappings(self):
        """加载默认的股票映射 (备用方案)"""
        self.predefined_mappings = {
            # 港股映射
            "2015": StockInfo(
                code="02015",
                name="理想汽车",
                exchange="HKEX",
                market_type="HK",
                original_input="2015",
                aliases=["理想汽车", "Li Auto", "LI", "理想", "Li Auto Inc"]
            ),
            "02015": StockInfo(
                code="02015",
                name="理想汽车",
                exchange="HKEX",
                market_type="HK",
                original_input="02015",
                aliases=["理想汽车", "Li Auto", "LI", "理想", "Li Auto Inc"]
            ),
            # 美股映射
            "TSLA": StockInfo(
                code="TSLA",
                name="特斯拉",
                exchange="NASDAQ",
                market_type="US",
                original_input="TSLA",
                aliases=["特斯拉", "Tesla", "Tesla Inc"]
            ),
        }
    
    def parse_stock_input(self, input_str: str) -> Optional[StockInfo]:
        """
        解析股票输入，支持多种格式
        
        Args:
            input_str: 用户输入的股票代码或公司名称
            
        Returns:
            StockInfo: 解析后的股票信息，如果无法解析则返回None
        """
        if not input_str or not input_str.strip():
            return None
            
        input_str = input_str.strip()
        logger.info(f"🔍 开始解析股票输入: '{input_str}'")
        
        # 1. 尝试直接匹配预定义映射
        stock_info = self._match_predefined_mapping(input_str)
        if stock_info:
            logger.info(f"✅ 直接匹配成功: {stock_info.name} ({stock_info.code})")
            return stock_info
        
        # 2. 尝试解析各种股票代码格式
        stock_info = self._parse_stock_code_formats(input_str)
        if stock_info:
            logger.info(f"✅ 代码格式解析成功: {stock_info.name} ({stock_info.code})")
            return stock_info
        
        # 3. 尝试按公司名称搜索
        stock_info = self._search_by_company_name(input_str)
        if stock_info:
            logger.info(f"✅ 公司名称搜索成功: {stock_info.name} ({stock_info.code})")
            return stock_info
        
        logger.warning(f"❌ 无法解析股票输入: '{input_str}'")
        return None
    
    def _match_predefined_mapping(self, input_str: str) -> Optional[StockInfo]:
        """匹配预定义映射表"""
        # 直接匹配代码
        if input_str in self.predefined_mappings:
            return self.predefined_mappings[input_str]
        
        # 匹配别名
        for stock_info in self.predefined_mappings.values():
            if input_str in stock_info.aliases or input_str.lower() in [alias.lower() for alias in stock_info.aliases]:
                return stock_info
        
        return None
    
    def _parse_stock_code_formats(self, input_str: str) -> Optional[StockInfo]:
        """解析各种股票代码格式"""
        # 移除常见前缀和后缀
        clean_input = input_str.upper()
        
        # 处理 KH.02015 格式 (港股)
        if clean_input.startswith('KH.'):
            hk_code = clean_input[3:]  # 移除 "KH." 前缀
            return self._create_hk_stock_info(hk_code, input_str)
        
        # 处理 R:2015.HK 格式
        if clean_input.startswith('R:'):
            clean_input = clean_input[2:]
        
        # 处理 .HK 后缀
        if clean_input.endswith('.HK'):
            hk_code = clean_input[:-3]
            return self._create_hk_stock_info(hk_code, input_str)
        
        # 处理纯数字港股代码
        if clean_input.isdigit() and len(clean_input) <= 5:
            return self._create_hk_stock_info(clean_input, input_str)
        
        # 处理美股代码格式 (字母)
        if re.match(r'^[A-Z]{1,5}$', clean_input):
            return self._create_us_stock_info(clean_input, input_str)
        
        # 处理A股代码格式 (6位数字)
        if re.match(r'^\d{6}$', clean_input):
            return self._create_cn_stock_info(clean_input, input_str)
        
        return None
    
    def _create_hk_stock_info(self, code: str, original_input: str) -> Optional[StockInfo]:
        """创建港股信息"""
        # 标准化为5位港股代码
        normalized_code = code.zfill(5)
        
        # 检查预定义映射
        if normalized_code in self.predefined_mappings:
            return self.predefined_mappings[normalized_code]
        
        # 尝试通过AKShare获取信息
        try:
            hk_info = self.akshare_provider.get_hk_stock_info(normalized_code)
            if hk_info and hk_info.get('name'):
                return StockInfo(
                    code=normalized_code,
                    name=hk_info['name'],
                    exchange="HKEX",
                    market_type="HK",
                    original_input=original_input,
                    aliases=[hk_info['name']]
                )
        except Exception as e:
            logger.debug(f"AKShare获取港股信息失败: {e}")
        
        # 创建默认港股信息
        return StockInfo(
            code=normalized_code,
            name=f"港股{normalized_code}",
            exchange="HKEX",
            market_type="HK",
            original_input=original_input,
            aliases=[f"港股{normalized_code}"]
        )
    
    def _create_us_stock_info(self, code: str, original_input: str) -> Optional[StockInfo]:
        """创建美股信息"""
        # 检查预定义映射
        if code in self.predefined_mappings:
            return self.predefined_mappings[code]
        
        # 创建默认美股信息
        return StockInfo(
            code=code,
            name=f"美股{code}",
            exchange="NASDAQ",
            market_type="US",
            original_input=original_input,
            aliases=[f"美股{code}"]
        )
    
    def _create_cn_stock_info(self, code: str, original_input: str) -> Optional[StockInfo]:
        """创建A股信息"""
        # 检查预定义映射
        if code in self.predefined_mappings:
            return self.predefined_mappings[code]
        
        # 创建默认A股信息
        exchange = "SZSE" if code.startswith(('000', '002', '300')) else "SSE"
        return StockInfo(
            code=code,
            name=f"A股{code}",
            exchange=exchange,
            market_type="CN",
            original_input=original_input,
            aliases=[f"A股{code}"]
        )
    
    def _search_by_company_name(self, company_name: str) -> Optional[StockInfo]:
        """根据公司名称搜索"""
        # 在预定义映射中搜索
        for stock_info in self.predefined_mappings.values():
            if (company_name.lower() in stock_info.name.lower() or 
                any(company_name.lower() in alias.lower() for alias in stock_info.aliases)):
                return stock_info
        
        return None

class SmartNewsSearcher:
    """智能新闻搜索器"""
    
    def __init__(self, vector_db: NewsVectorDB):
        self.vector_db = vector_db
        self.stock_mapper = StockCodeMapper()
    
    def search_news_by_stock(self, 
                           stock_input: str,
                           n_results: int = 20,
                           days_back: int = 30,
                           include_related: bool = True) -> Dict[str, Any]:
        """
        根据股票代码或公司名称搜索相关新闻
        
        Args:
            stock_input: 股票代码或公司名称 (如: "R:2015.HK", "理想汽车")
            n_results: 返回结果数量
            days_back: 搜索最近多少天的新闻
            include_related: 是否包含相关新闻 (使用别名搜索)
            
        Returns:
            Dict: 搜索结果和统计信息
        """
        logger.info(f"🔍 开始智能新闻搜索: '{stock_input}'")
        
        # 1. 解析股票信息
        stock_info = self.stock_mapper.parse_stock_input(stock_input)
        if not stock_info:
            return {
                'success': False,
                'error': f'无法识别股票代码或公司名称: {stock_input}',
                'results': [],
                'total_found': 0
            }
        
        logger.info(f"✅ 股票信息解析成功: {stock_info.name} ({stock_info.code})")
        
        # 2. 构建搜索关键词
        search_keywords = self._build_search_keywords(stock_info, include_related)
        logger.info(f"🔑 搜索关键词: {search_keywords}")
        
        # 3. 设置时间范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # 4. 执行搜索
        all_results = []
        search_stats = {
            'stock_info': {
                'code': stock_info.code,
                'name': stock_info.name,
                'exchange': stock_info.exchange,
                'market_type': stock_info.market_type,
                'original_input': stock_info.original_input
            },
            'search_params': {
                'keywords': search_keywords,
                'n_results': n_results,
                'days_back': days_back,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            },
            'search_results': {}
        }
        
        # 5. 使用主要关键词进行语义搜索
        primary_query = stock_info.name
        try:
            primary_results = self.vector_db.semantic_search(
                query=primary_query,
                n_results=n_results,
                keywords=search_keywords,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            all_results.extend(primary_results)
            search_stats['search_results']['primary_search'] = {
                'query': primary_query,
                'found': len(primary_results)
            }
            
            logger.info(f"📊 主要搜索完成: 找到 {len(primary_results)} 条结果")
            
        except Exception as e:
            logger.error(f"❌ 主要搜索失败: {e}")
            search_stats['search_results']['primary_search'] = {
                'query': primary_query,
                'found': 0,
                'error': str(e)
            }
        
        # 6. 如果启用相关搜索，使用别名进行补充搜索
        if include_related and stock_info.aliases:
            for alias in stock_info.aliases[:3]:  # 限制别名搜索数量
                if alias.lower() != stock_info.name.lower():  # 避免重复搜索
                    try:
                        alias_results = self.vector_db.semantic_search(
                            query=alias,
                            n_results=max(5, n_results // 3),  # 别名搜索结果较少
                            keywords=[alias],
                            start_date=start_date.isoformat(),
                            end_date=end_date.isoformat()
                        )
                        
                        # 去重合并
                        existing_ids = {r.get('id') for r in all_results}
                        new_results = [r for r in alias_results if r.get('id') not in existing_ids]
                        all_results.extend(new_results)
                        
                        search_stats['search_results'][f'alias_search_{alias}'] = {
                            'query': alias,
                            'found': len(alias_results),
                            'new_results': len(new_results)
                        }
                        
                        logger.info(f"📊 别名搜索 '{alias}': 找到 {len(alias_results)} 条，新增 {len(new_results)} 条")
                        
                    except Exception as e:
                        logger.error(f"❌ 别名搜索 '{alias}' 失败: {e}")
                        search_stats['search_results'][f'alias_search_{alias}'] = {
                            'query': alias,
                            'found': 0,
                            'error': str(e)
                        }
        
        # 7. 结果排序和限制
        all_results = sorted(all_results, key=lambda x: x.get('score', 0), reverse=True)[:n_results]
        
        # 8. 统计分析
        search_stats['final_stats'] = {
            'total_found': len(all_results),
            'sources': self._analyze_sources(all_results),
            'date_range': self._analyze_date_range(all_results)
        }
        
        logger.info(f"✅ 智能新闻搜索完成: 共找到 {len(all_results)} 条相关新闻")
        
        return {
            'success': True,
            'stock_info': stock_info,
            'results': all_results,
            'stats': search_stats,
            'total_found': len(all_results)
        }
    
    def _build_search_keywords(self, stock_info: StockInfo, include_related: bool) -> List[str]:
        """构建搜索关键词列表"""
        keywords = [stock_info.name, stock_info.code]
        
        if include_related:
            keywords.extend(stock_info.aliases)
        
        # 去重并过滤空值
        keywords = list(set(filter(None, keywords)))
        return keywords
    
    def _analyze_sources(self, results: List[Dict]) -> Dict[str, int]:
        """分析新闻来源分布"""
        sources = {}
        for result in results:
            source = result.get('metadata', {}).get('source', '未知来源')
            sources[source] = sources.get(source, 0) + 1
        return sources
    
    def _analyze_date_range(self, results: List[Dict]) -> Dict[str, Any]:
        """分析新闻日期分布"""
        if not results:
            return {}
        
        dates = []
        for result in results:
            published_at = result.get('metadata', {}).get('published_at')
            if published_at:
                try:
                    dates.append(datetime.fromisoformat(published_at))
                except:
                    continue
        
        if not dates:
            return {}
        
        return {
            'earliest': min(dates).isoformat(),
            'latest': max(dates).isoformat(),
            'total_days': (max(dates) - min(dates)).days + 1
        }

# 便捷函数
def create_smart_news_searcher(vector_db: NewsVectorDB) -> SmartNewsSearcher:
    """创建智能新闻搜索器实例"""
    return SmartNewsSearcher(vector_db)

def search_stock_news(stock_input: str, 
                     vector_db: NewsVectorDB,
                     n_results: int = 20,
                     days_back: int = 30) -> Dict[str, Any]:
    """便捷的股票新闻搜索函数"""
    searcher = create_smart_news_searcher(vector_db)
    return searcher.search_news_by_stock(
        stock_input=stock_input,
        n_results=n_results,
        days_back=days_back,
        include_related=True
    )