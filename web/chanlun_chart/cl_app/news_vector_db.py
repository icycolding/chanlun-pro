#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻向量数据库处理模块
使用 Chroma DB 存储新闻向量数据，支持语义搜索和量化分析

主要功能:
1. 新闻文本向量化存储
2. 语义相似度搜索
3. 情感分析和主题分类
4. 量化分析数据提取
"""

import os
import json
import datetime
import hashlib
from typing import List, Dict, Optional, Tuple, Any
import logging
from zoneinfo import ZoneInfo
import pytz

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions
except ImportError:
    print("警告: chromadb 未安装，请运行: pip install chromadb")
    chromadb = None

try:
    import jieba
    import jieba.analyse
except ImportError:
    print("警告: jieba 未安装，请运行: pip install jieba")
    jieba = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("警告: sentence-transformers 未安装，请运行: pip install sentence-transformers")
    SentenceTransformer = None

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NewsVectorDB:
    """
    新闻向量数据库管理类
    
    向量数据结构设计:
    1. Collection: news_vectors - 存储新闻向量和元数据
    2. 元数据字段:
       - news_id: 新闻唯一标识
       - title: 新闻标题
       - source: 新闻来源
       - published_at: 发布时间
       - category: 新闻分类
       - sentiment_score: 情感分数 (-1到1)
       - importance_score: 重要性分数 (0到1)
       - market_relevance: 市场相关性 (0到1)
       - keywords: 关键词列表
       - entities: 实体识别结果
       - language: 语言
       - content_hash: 内容哈希值
    3. 向量维度: 384 (使用sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
    """
    
    def __init__(self, db_path: str = "./chroma_db", model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """
        初始化向量数据库
        
        Args:
            db_path: 数据库存储路径
            model_name: 嵌入模型名称
        """
        self.db_path = db_path
        self.model_name = model_name
        self.client = None
        self.collection = None
        self.embedding_model = None
        
        # 确保数据库目录存在
        os.makedirs(db_path, exist_ok=True)
        
        # 初始化数据库连接
        self._init_database()
        
        # 初始化嵌入模型
        self._init_embedding_model()
    
    def _init_database(self):
        """初始化 Chroma 数据库连接"""
        if chromadb is None:
            logger.error("ChromaDB 未安装，无法初始化向量数据库")
            return
            
        try:
            # 创建持久化客户端
            self.client = chromadb.PersistentClient(
                path=self.db_path,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            # 获取或创建新闻向量集合
            self.collection = self.client.get_or_create_collection(
                name="news_vectors",
                metadata={
                    "description": "新闻文本向量存储，用于语义搜索和量化分析",
                    "created_at": datetime.datetime.now().isoformat(),
                    "model": self.model_name,
                    "dimension": 384
                }
            )
            
            logger.info(f"向量数据库初始化成功，集合大小: {self.collection.count()}")
            
        except Exception as e:
            logger.error(f"初始化向量数据库失败: {str(e)}")
            raise
    
    def _init_embedding_model(self):
        """初始化嵌入模型"""
        if SentenceTransformer is None:
            logger.warning("sentence-transformers 未安装，将使用 ChromaDB 默认嵌入函数")
            return
            
        try:
            # 使用多语言模型，支持中英文
            self.embedding_model = SentenceTransformer(self.model_name)
            logger.info(f"嵌入模型 {self.model_name} 加载成功")
        except Exception as e:
            logger.warning(f"加载嵌入模型失败: {str(e)}，将使用默认嵌入函数")
            self.embedding_model = None
    
    def _extract_keywords(self, text: str, topK: int = 10) -> List[str]:
        """提取文本关键词"""
        if jieba is None:
            return []
            
        try:
            # 使用 TF-IDF 提取关键词
            keywords = jieba.analyse.extract_tags(text, topK=topK, withWeight=False)
            return keywords
        except Exception as e:
            logger.warning(f"关键词提取失败: {str(e)}")
            return []
    
    def _calculate_market_relevance(self, text: str, keywords: List[str]) -> float:
        """计算市场相关性分数"""
        # 金融市场相关关键词
        market_keywords = {
            '股票', '股市', '股价', '涨跌', '交易', '投资', '基金', '债券',
            '期货', '外汇', '汇率', '央行', '利率', '通胀', 'GDP', 'CPI',
            '经济', '金融', '银行', '证券', '保险', '房地产', '商品',
            'stock', 'market', 'trading', 'investment', 'fund', 'bond',
            'forex', 'currency', 'rate', 'economy', 'finance', 'bank'
        }
        
        # 计算匹配度
        text_lower = text.lower()
        keyword_matches = sum(1 for kw in market_keywords if kw in text_lower)
        extracted_matches = sum(1 for kw in keywords if kw in market_keywords)
        
        # 综合评分
        relevance_score = min(1.0, (keyword_matches * 0.1 + extracted_matches * 0.2))
        return relevance_score
    
    def _generate_content_hash(self, title: str, body: str) -> str:
        """生成内容哈希值，用于去重"""
        content = f"{title}\n{body}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _create_embedding(self, text: str) -> List[float]:
        """创建文本嵌入向量"""
        if self.embedding_model is not None:
            try:
                embedding = self.embedding_model.encode(text, convert_to_tensor=False)
                return embedding.tolist()
            except Exception as e:
                logger.warning(f"使用自定义模型创建嵌入失败: {str(e)}")
        
        # 如果自定义模型失败，返回 None，让 ChromaDB 使用默认嵌入函数
        return None
    
    def _normalize_datetime(self, dt_input) -> str:
        """统一处理时间格式，确保返回中国时区的ISO格式字符串"""
        try:
            # 中国时区
            china_tz = pytz.timezone('Asia/Shanghai')
            
            if dt_input is None:
                return datetime.datetime.now(china_tz).isoformat()
            
            if isinstance(dt_input, datetime.datetime):
                # 如果是datetime对象，转换为中国时区
                if dt_input.tzinfo is None:
                    # 无时区信息，假设为UTC时间
                    dt_utc = pytz.utc.localize(dt_input)
                    dt_china = dt_utc.astimezone(china_tz)
                else:
                    # 有时区信息，直接转换
                    dt_china = dt_input.astimezone(china_tz)
                return dt_china.isoformat()
            
            if isinstance(dt_input, str):
                # 如果是字符串，尝试解析后转换
                if dt_input.strip() == '':
                    return datetime.datetime.now(china_tz).isoformat()
                
                # 尝试解析各种时间格式
                try:
                    # ISO格式
                    if 'T' in dt_input:
                        if dt_input.endswith('Z'):
                            # UTC时间
                            parsed_dt = datetime.datetime.fromisoformat(dt_input.replace('Z', '+00:00'))
                            dt_china = parsed_dt.astimezone(china_tz)
                        elif '+' in dt_input or dt_input.count('-') > 2:
                            # 带时区的ISO格式
                            parsed_dt = datetime.datetime.fromisoformat(dt_input)
                            dt_china = parsed_dt.astimezone(china_tz)
                        else:
                            # 无时区的ISO格式，假设为UTC
                            parsed_dt = datetime.datetime.fromisoformat(dt_input)
                            dt_utc = pytz.utc.localize(parsed_dt)
                            dt_china = dt_utc.astimezone(china_tz)
                        return dt_china.isoformat()
                    else:
                        # 简单日期格式，假设为中国时区
                        parsed_dt = datetime.datetime.strptime(dt_input, '%Y-%m-%d')
                        dt_china = china_tz.localize(parsed_dt)
                        return dt_china.isoformat()
                except ValueError:
                    logger.warning(f"无法解析时间格式: {dt_input}，使用当前中国时间")
                    return datetime.datetime.now(china_tz).isoformat()
            
            # 其他类型，使用当前中国时间
            logger.warning(f"不支持的时间类型: {type(dt_input)}，使用当前中国时间")
            return datetime.datetime.now(china_tz).isoformat()
            
        except Exception as e:
            logger.error(f"时间格式化失败: {str(e)}，使用当前中国时间")
            china_tz = pytz.timezone('Asia/Shanghai')
            return datetime.datetime.now(china_tz).isoformat()
    
    def add_news(self, news_data: Dict[str, Any]) -> bool:
        """
        添加新闻到向量数据库
        
        Args:
            news_data: 新闻数据字典，包含以下字段:
                - news_id: 新闻ID
                - title: 标题
                - body: 内容
                - source: 来源
                - published_at: 发布时间
                - category: 分类
                - sentiment_score: 情感分数
                - importance_score: 重要性分数
                - language: 语言
        
        Returns:
            bool: 是否添加成功
        """
        if self.collection is None:
            logger.error("向量数据库未初始化")
            return False
        
        try:
            # 必需字段检查
            required_fields = ['news_id', 'title', 'body']
            for field in required_fields:
                if field not in news_data or not news_data[field]:
                    logger.error(f"缺少必需字段: {field}")
                    return False
            
            # 生成内容哈希
            content_hash = self._generate_content_hash(news_data['title'], news_data['body'])
            
            # 检查是否已存在
            existing = self.collection.get(
                where={"content_hash": content_hash}
            )
            if existing['ids']:
                logger.info(f"新闻已存在，跳过: {news_data['title'][:50]}...")
                return True
            
            # 准备文本内容用于向量化
            full_text = f"{news_data['title']}\n{news_data['body']}"
            
            # 提取关键词
            keywords = self._extract_keywords(full_text)
            
            # 计算市场相关性
            market_relevance = self._calculate_market_relevance(full_text, keywords)
            
            # 中国时区
            china_tz = pytz.timezone('Asia/Shanghai')
            
            # 准备元数据，确保所有字符串字段不为None，时间统一使用中国时区
            metadata = {
                "news_id": str(news_data['news_id']),
                "title": str(news_data['title'][:500]) if news_data['title'] else '',  # 限制长度并确保非None
                "source": str(news_data.get('source') or ''),
                "published_at": self._normalize_datetime(news_data.get('published_at')),
                "category": str(news_data.get('category') or ''),
                "sentiment_score": float(news_data.get('sentiment_score', 0.0)),
                "importance_score": float(news_data.get('importance_score', 0.5)),
                "market_relevance": market_relevance,
                "keywords": json.dumps(keywords, ensure_ascii=False),
                "language": str(news_data.get('language') or 'zh'),
                "content_hash": content_hash,
                "created_at": datetime.datetime.now(china_tz).isoformat()
            }
            
            logger.info(f"新闻时间处理 - 原始时间: {news_data.get('published_at')}, 标准化后: {metadata['published_at']}")
            
            # 创建嵌入向量
            embedding = self._create_embedding(full_text)
            
            # 添加到集合
            if embedding is not None:
                self.collection.add(
                    ids=[news_data['news_id']],
                    documents=[full_text],
                    metadatas=[metadata],
                    embeddings=[embedding]
                )
            else:
                # 使用 ChromaDB 默认嵌入函数
                self.collection.add(
                    ids=[news_data['news_id']],
                    documents=[full_text],
                    metadatas=[metadata]
                )
            
            logger.info(f"新闻向量添加成功: {news_data['title'][:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"添加新闻向量失败: {str(e)}")
            return False
    
    def semantic_search(self, query: str, n_results: int = 10, 
                       filters: Optional[Dict[str, Any]] = None,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        语义搜索新闻
        
        Args:
            query: 搜索查询
            n_results: 返回结果数量
            filters: 过滤条件
            start_date: 开始时间 (ISO格式字符串)
            end_date: 结束时间 (ISO格式字符串)
        
        Returns:
            List[Dict]: 搜索结果列表
        """
        if self.collection is None:
            logger.error("向量数据库未初始化")
            return []

        try:
            # 构建时间过滤条件
            where_conditions = filters.copy() if filters else {}
            
            # ChromaDB的时间过滤存在兼容性问题，改为Python层面过滤
            # 先执行基本查询，然后在Python层面进行时间过滤
            time_filter_needed = bool(start_date or end_date)
            start_dt = None
            end_dt = None
            
            if time_filter_needed:
                try:
                    # 中国时区
                    china_tz = pytz.timezone('Asia/Shanghai')
                    
                    if start_date:
                        # 使用统一的时间标准化方法，确保转换为中国时区
                        start_dt_str = self._normalize_datetime(start_date)
                        start_dt = datetime.datetime.fromisoformat(start_dt_str)
                        
                    if end_date:
                        # 使用统一的时间标准化方法，确保转换为中国时区
                        end_dt_str = self._normalize_datetime(end_date)
                        end_dt = datetime.datetime.fromisoformat(end_dt_str)
                        
                    logger.info(f"应用中国时区时间过滤: {start_date} -> {start_dt_str if start_date else None} 到 {end_date} -> {end_dt_str if end_date else None}")
                except ValueError as ve:
                    logger.warning(f"时间格式无效: {ve}")
                    time_filter_needed = False
            
            # 执行语义搜索，如果需要时间过滤则获取更多结果以便后续过滤
            query_n_results = n_results * 3 if time_filter_needed else n_results
            
            results = self.collection.query(
                query_texts=[query],
                n_results=query_n_results,
                where=where_conditions if where_conditions else None
            )
            
            # 格式化结果并应用时间过滤
            formatted_results = []
            for i, doc_id in enumerate(results['ids'][0]):
                metadata = results['metadatas'][0][i]
                
                # 应用时间过滤（文档时间已经是中国时区格式）
                if time_filter_needed:
                    try:
                        doc_time_str = metadata.get('published_at', '')
                        if doc_time_str:
                            # 文档时间已经是标准化的中国时区格式，直接解析
                            doc_time = datetime.datetime.fromisoformat(doc_time_str)
                            
                            # 检查时间范围（都是中国时区时间，可以直接比较）
                            if start_dt and doc_time < start_dt:
                                continue
                            if end_dt and doc_time > end_dt:
                                continue
                    except (ValueError, TypeError) as e:
                        # 时间解析失败，记录警告并跳过该文档
                        logger.warning(f"文档时间解析失败: {doc_time_str}, 错误: {e}")
                        continue
                
                result = {
                    'id': doc_id,
                    'document': results['documents'][0][i],
                    'metadata': metadata,
                    'distance': results['distances'][0][i] if 'distances' in results else None
                }
                formatted_results.append(result)
                
                # 如果已经获得足够的结果，停止处理
                if len(formatted_results) >= n_results:
                    break
            
            logger.info(f"语义搜索完成: 查询='{query}', 返回{len(formatted_results)}个结果")
            return formatted_results
            
        except Exception as e:
            logger.error(f"语义搜索失败: {str(e)}")
            return []
    
    def get_similar_news(self, news_id: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        获取相似新闻
        
        Args:
            news_id: 新闻ID
            n_results: 返回结果数量
        
        Returns:
            List[Dict]: 相似新闻列表
        """
        if self.collection is None:
            return []
        
        try:
            # 获取原新闻
            original = self.collection.get(ids=[news_id])
            if not original['documents']:
                logger.warning(f"未找到新闻: {news_id}")
                return []
            
            # 使用原新闻文档进行搜索
            return self.semantic_search(
                query=original['documents'][0],
                n_results=n_results + 1,  # +1 因为会包含自己
                filters={"news_id": {"$ne": news_id}}  # 排除自己
            )
            
        except Exception as e:
            logger.error(f"获取相似新闻失败: {str(e)}")
            return []
    
    def get_market_relevant_news(self, min_relevance: float = 0.3, 
                                limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取市场相关新闻
        
        Args:
            min_relevance: 最小相关性分数
            limit: 返回数量限制
        
        Returns:
            List[Dict]: 市场相关新闻列表
        """
        if self.collection is None:
            return []
        
        try:
            results = self.collection.get(
                where={"market_relevance": {"$gte": min_relevance}},
                limit=limit
            )
            
            formatted_results = []
            for i, doc_id in enumerate(results['ids']):
                result = {
                    'id': doc_id,
                    'document': results['documents'][i],
                    'metadata': results['metadatas'][i]
                }
                formatted_results.append(result)
            
            # 按市场相关性排序
            formatted_results.sort(
                key=lambda x: x['metadata']['market_relevance'], 
                reverse=True
            )
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"获取市场相关新闻失败: {str(e)}")
            return []
    
    def get_sentiment_analysis(self, start_date: Optional[datetime.datetime] = None,
                              end_date: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        """
        获取情感分析统计
        
        Args:
            start_date: 开始日期（将转换为中国时区）
            end_date: 结束日期（将转换为中国时区）
        
        Returns:
            Dict: 情感分析统计结果
        """
        if self.collection is None:
            return {}
        
        try:
            # 获取所有数据，然后在Python层面进行时间过滤
            results = self.collection.get()
            
            if not results['metadatas']:
                return {"total": 0, "positive": 0, "negative": 0, "neutral": 0, "avg_sentiment": 0.0}
            
            # 时间过滤处理
            filtered_metadatas = []
            if start_date or end_date:
                # 转换查询时间为中国时区
                start_dt = None
                end_dt = None
                if start_date:
                    start_dt_str = self._normalize_datetime(start_date)
                    start_dt = datetime.datetime.fromisoformat(start_dt_str)
                if end_date:
                    end_dt_str = self._normalize_datetime(end_date)
                    end_dt = datetime.datetime.fromisoformat(end_dt_str)
                
                logger.info(f"情感分析时间过滤: {start_date} -> {start_dt} 到 {end_date} -> {end_dt}")
                
                # 过滤文档
                for meta in results['metadatas']:
                    try:
                        doc_time_str = meta.get('published_at', '')
                        if doc_time_str:
                            doc_time = datetime.datetime.fromisoformat(doc_time_str)
                            
                            # 检查时间范围（都是中国时区时间）
                            if start_dt and doc_time < start_dt:
                                continue
                            if end_dt and doc_time > end_dt:
                                continue
                        
                        filtered_metadatas.append(meta)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"情感分析时间解析失败: {doc_time_str}, 错误: {e}")
                        continue
            else:
                filtered_metadatas = results['metadatas']
            
            if not filtered_metadatas:
                return {"total": 0, "positive": 0, "negative": 0, "neutral": 0, "avg_sentiment": 0.0}
            
            # 统计情感分布
            sentiments = [meta.get('sentiment_score', 0.0) for meta in filtered_metadatas]
            positive = sum(1 for s in sentiments if s > 0.1)
            negative = sum(1 for s in sentiments if s < -0.1)
            neutral = len(sentiments) - positive - negative
            avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0
            
            return {
                "total": len(sentiments),
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
                "avg_sentiment": avg_sentiment,
                "sentiment_distribution": sentiments
            }
            
        except Exception as e:
            logger.error(f"获取情感分析失败: {str(e)}")
            return {}
    
    def delete_news(self, news_id: str) -> bool:
        """
        删除新闻向量
        
        Args:
            news_id: 新闻ID
        
        Returns:
            bool: 是否删除成功
        """
        if self.collection is None:
            return False
        
        try:
            self.collection.delete(ids=[news_id])
            logger.info(f"新闻向量删除成功: {news_id}")
            return True
        except Exception as e:
            logger.error(f"删除新闻向量失败: {str(e)}")
            return False
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """
        获取集合统计信息
        
        Returns:
            Dict: 统计信息
        """
        if self.collection is None:
            return {}
        
        try:
            count = self.collection.count()
            return {
                "total_documents": count,
                "collection_name": self.collection.name,
                "model_name": self.model_name,
                "db_path": self.db_path
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {str(e)}")
            return {}


# 全局向量数据库实例
_vector_db_instance = None

def get_vector_db(db_path: str = "./chroma_db") -> NewsVectorDB:
    """
    获取向量数据库单例实例
    
    Args:
        db_path: 数据库路径
    
    Returns:
        NewsVectorDB: 向量数据库实例
    """
    global _vector_db_instance
    if _vector_db_instance is None:
        _vector_db_instance = NewsVectorDB(db_path=db_path)
    return _vector_db_instance