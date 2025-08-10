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
import tempfile
from typing import List, Dict, Optional, Tuple, Any
import logging
from zoneinfo import ZoneInfo
import pytz

try:
    import chromadb
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

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ImportError:
    print("警告: langchain 未安装，请运行: pip install langchain")
    RecursiveCharacterTextSplitter = None

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
    
    def __init__(self, db_path: Optional[str] = None, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """
        初始化向量数据库
        
        Args:
            db_path: 数据库存储路径. 如果为 None, 将使用默认路径 (相对于本文件的 `../chroma_db`).
            model_name: 嵌入模型名称
        """
        if db_path is None:
            # 默认数据库路径，相对于此文件的位置
            module_dir = os.path.dirname(os.path.abspath(__file__))
            # 数据库位于 cl_app 目录的上一级的 chroma_db 目录
            self.db_path = os.path.normpath(os.path.join(module_dir, '..', 'chroma_db'))
        else:
            self.db_path = db_path
            
        self.model_name = model_name
        self.client = None
        self.collection = None
        self.embedding_model = None
        
        # 确保数据库目录存在
        os.makedirs(self.db_path, exist_ok=True)
        
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
            # 尝试使用持久化客户端，如果失败则使用临时目录或内存客户端
            try:
                # 确保数据库目录存在且有正确权限
                os.makedirs(self.db_path, exist_ok=True)
                os.chmod(self.db_path, 0o755)
                
                # 创建持久化客户端（适配0.5.0版本）
                self.client = chromadb.PersistentClient(
                    path=self.db_path
                )
                logger.info(f"使用持久化数据库: {self.db_path}")
            except Exception as persist_error:
                logger.warning(f"持久化数据库初始化失败: {str(persist_error)}，尝试临时目录")
                try:
                    # 使用临时目录作为备选方案
                    temp_dir = tempfile.mkdtemp(prefix="chromadb_news_")
                    self.client = chromadb.PersistentClient(path=temp_dir)
                    logger.info(f"使用临时目录数据库: {temp_dir}")
                except Exception as temp_error:
                    logger.warning(f"临时目录数据库初始化失败: {str(temp_error)}，切换到内存模式")
                    # 使用内存客户端作为最后备选方案
                    self.client = chromadb.Client()
                    logger.info("使用内存数据库模式")
            
            # 获取或创建新闻向量集合，使用余弦相似度
            self.collection = self.client.get_or_create_collection(
                name="news_vectors",
                metadata={
                    "description": "新闻文本向量存储，用于语义搜索和量化分析",
                    "created_at": datetime.datetime.now().isoformat(),
                    "model": self.model_name,
                    "dimension": 384,
                    "distance_function": "cosine"
                }
                # 注意：ChromaDB会自动使用余弦距离作为默认距离函数
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
        【已修复和优化】添加新闻到向量数据库，采用文本切分策略。
        一篇新闻会被切分成多个语义块(chunks)，每个块独立存储，并包含可过滤的关键词元数据。
        
        Args:
            news_data: 新闻数据字典。
        
        Returns:
            bool: 是否添加成功
        """
        if self.collection is None:
            logger.error("向量数据库未初始化")
            return False
        
        try:
            # 1. 字段检查和内容哈希
            required_fields = ['news_id', 'title', 'body']
            for field in required_fields:
                if field not in news_data or not news_data[field]:
                    logger.error(f"缺少必需字段: {field}")
                    return False
            
            content_hash = self._generate_content_hash(news_data['title'], news_data['body'])
            
            # 2. 检查新闻ID是否已存在
            existing = self.collection.get(where={"news_id": str(news_data['news_id'])})
            if existing['ids']:
                logger.info(f"新闻ID已存在，跳过: {news_data['title'][:50]}...")
                return True

            # 3. 使用LangChain进行文本切分
            full_text = f"标题: {news_data['title']}\n\n内容: {news_data['body']}"
            
            if RecursiveCharacterTextSplitter is None:
                logger.error("关键组件 LangChain 未安装，无法执行新闻添加。")
                return False # 直接失败，而不是回退，以保证数据一致性
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=512,
                chunk_overlap=50,
                separators=["\n\n", "\n", "。", "！", "？", "，", " "]
            )
            chunks = text_splitter.split_text(full_text)
            
            if not chunks:
                logger.warning(f"文本切分后没有产生任何块，跳过新闻: {news_data['title'][:50]}...")
                return False

            logger.info(f"新闻 '{news_data['title'][:30]}...' 被切分成 {len(chunks)} 个语义块。")

            # 4. 【已修复】为整篇新闻预计算特征
            # 这是最关键的一步：提取出高质量的、可用于过滤的关键词列表
            keywords_list = self._extract_keywords(full_text)
            market_relevance = self._calculate_market_relevance(full_text, keywords_list)
            # keywords_list to str
            keywords_list = ','.join(keywords_list)
            # 准备批量添加的数据
            ids_to_add = []
            documents_to_add = []
            metadatas_to_add = []
            
            china_tz = pytz.timezone('Asia/Shanghai')
            
            for i, chunk_content in enumerate(chunks):
                chunk_id = f"{news_data['news_id']}_chunk_{i+1}"
                
                # 【已修复】每个列表只添加一次
                ids_to_add.append(chunk_id)
                documents_to_add.append(chunk_content) # 只添加纯净的块内容用于向量化
                
                # 处理发布时间
                published_at_iso = self._normalize_datetime(news_data.get('published_at'))
                try:
                    published_dt = datetime.datetime.fromisoformat(published_at_iso)
                    published_at_ts = published_dt.timestamp()
                except (ValueError, TypeError):
                    published_dt = datetime.datetime.now(china_tz)
                    published_at_ts = published_dt.timestamp()
                    published_at_iso = published_dt.isoformat()
                
                # 5. 【已修复】构建正确的元数据
                #    关键词作为可过滤的列表被添加到元数据中
                metadata = {
                    "news_id": str(news_data['news_id']),
                    "chunk_id": i + 1,
                    "total_chunks": len(chunks),
                    "title": str(news_data['title'][:500]) if news_data['title'] else '',
                    "source": str(news_data.get('source') or ''),
                    "published_at": published_at_iso,
                    "published_at_ts": published_at_ts,
                    "category": str(news_data.get('category') or ''),
                    "sentiment_score": float(news_data.get('sentiment_score', 0.0)),
                    "importance_score": float(news_data.get('importance_score', 0.5)),
                    "market_relevance": market_relevance,
                    "language": str(news_data.get('language') or 'zh'),
                    "content_hash": content_hash,
                    "created_at": datetime.datetime.now(china_tz).isoformat(),
                    # --- 【核心修复】将关键词作为列表添加到元数据中 ---
                    "keywords": keywords_list
                }
                metadatas_to_add.append(metadata)

            # 6. 【已修复】批量添加到集合，依赖ChromaDB的默认嵌入函数
            #    这是推荐的做法，除非你有特定的、更优的嵌入模型
            if ids_to_add:
                self.collection.add(
                    ids=ids_to_add,
                    documents=documents_to_add,
                    metadatas=metadatas_to_add
                )
                logger.info(f"新闻切分向量添加成功: {news_data['title'][:50]}... (共{len(chunks)}个块)")
                return True
            else:
                logger.warning("没有可添加的数据块。")
        
        except Exception as e:
            # 使用 exc_info=True 可以记录完整的堆栈跟踪，便于调试
            logger.error(f"添加新闻切分向量失败: {str(e)}", exc_info=True)
            return False
    
    def semantic_search_reimagined(
        self, 
        query: str, 
        n_results: int = 10, 
        keywords: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        【已升级】执行混合语义搜索。
        先用元数据（关键词、时间）进行硬过滤，再在过滤后的结果中进行语义搜索。
        
        Args:
            query: 搜索查询
            n_results: 返回结果数量 (1-100)
            keywords: 关键词过滤列表
            start_date: 开始时间 (ISO格式)
            end_date: 结束时间 (ISO格式)
            filters: 额外的过滤条件
        
        Returns:
            List[Dict]: 搜索结果列表
        """
        if self.collection is None:
            logger.error("向量数据库未初始化")
            return []
        
        # 参数验证
        
        if not query or not query.strip():
            logger.warning("搜索查询为空")
            return []
        
        if n_results < 1 or n_results > 100:
            logger.warning(f"结果数量超出范围 (1-100): {n_results}，将调整为10")
            n_results = 10
        
        try:
            # 1. 构建混合过滤器
            where_filter, where_document_filter = self._build_hybrid_filter(keywords, start_date, end_date, filters)
            
            # 2. 执行一次高效的数据库查询
            # 请求更多的结果（例如n*5），因为多个结果可能属于同一篇新闻
            query_n_results = n_results * 5
            collection_count = self.collection.count()
            
            # 确保查询结果数量至少为1
            final_n_results = max(1, min(query_n_results, collection_count))
            
            logger.info(f"执行混合搜索: 查询='{query}...', where={where_filter}, where_document={where_document_filter}, collection_count={collection_count}, final_n_results={final_n_results}")
            
            # 如果集合为空，直接返回空结果
            if collection_count == 0:
                logger.info("向量数据库为空，返回空结果")
                return []
            
            results = self.collection.query(
                query_texts=[query],
                n_results=final_n_results,
                where=where_filter,
                where_document=where_document_filter
            )
            
            if not results or not results['ids'] or not results['ids'][0]:
                logger.info(f"在过滤条件下未找到匹配结果: 查询='{query}'")
                return []
            
            # 3. 格式化和合并
            # 将原始的ChromaDB结果转换为更易于处理的字典列表
            formatted_chunks = [
                {
                    'id': results['ids'][0][i],
                    'document': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i]
                }
                for i in range(len(results['ids'][0]))
            ]
            
            # 4. 使用新的智能合并和评分方法
            final_results = self._merge_and_score_chunks(formatted_chunks, n_results)
            
            logger.info(f"混合搜索完成: 返回{len(final_results)}条结果")
            return final_results
            
        except Exception as e:
            logger.error(f"混合语义搜索失败: {e}")
            return []
    
    def semantic_search(self, query: str, n_results: int = 10, 
                       filters: Optional[Dict[str, Any]] = None,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None,
                       keywords: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        语义搜索新闻
        【兼容性方法】内部调用新的混合搜索实现
        
        Args:
            query: 搜索查询
            n_results: 返回结果数量
            filters: 过滤条件
            start_date: 开始时间 (ISO格式字符串)
            end_date: 结束时间 (ISO格式字符串)
            keywords: 关键词过滤列表
        
        Returns:
            List[Dict]: 搜索结果列表
        """
        # 直接调用新的混合搜索方法
        return self.semantic_search_reimagined(
            query=query,
            n_results=n_results,
            keywords=keywords,
            start_date=start_date,
            end_date=end_date,
            filters=filters
        )
    
    def _build_hybrid_filter(
        self, 
        keywords: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        构建用于ChromaDB的混合元数据和文档内容过滤器。
        
        Args:
            keywords: 关键词列表
            start_date: 开始时间 (ISO格式字符串)
            end_date: 结束时间 (ISO格式字符串)
            filters: 额外的元数据过滤条件
        
        Returns:
            Tuple[Optional[Dict], Optional[Dict]]: (where_filter, where_document_filter)
        """
        where_conditions = []
        where_document_conditions = []

        # 1. 处理元数据过滤 - 时间戳
        if start_date or end_date:
            try:
                if start_date:
                    start_dt = datetime.datetime.fromisoformat(start_date)
                    where_conditions.append({"published_at_ts": {"$gte": start_dt.timestamp()}})
                if end_date:
                    end_dt = datetime.datetime.fromisoformat(end_date)
                    where_conditions.append({"published_at_ts": {"$lte": end_dt.timestamp()}})
            except ValueError as e:
                logger.warning(f"无效的时间格式，将忽略时间过滤: {e}")

        # 2. 处理额外的元数据过滤条件
        if filters:
            for key, value in filters.items():
                if key not in ['published_at_ts']:
                    where_conditions.append({key: value})

        # 3. 【核心变更】处理文档内容过滤 - 关键词
        if keywords:
            keyword_conditions = [{"$contains": kw} for kw in keywords]
            if len(keyword_conditions) > 1:
                where_document_conditions.append({"$or": keyword_conditions})
            elif keyword_conditions:
                where_document_conditions.append(keyword_conditions[0])

        # 组合最终的过滤器
        where_filter = {"$and": where_conditions} if len(where_conditions) > 1 else (where_conditions[0] if where_conditions else None)
        where_document_filter = {"$and": where_document_conditions} if len(where_document_conditions) > 1 else (where_document_conditions[0] if where_document_conditions else None)

        return where_filter, where_document_filter
    
    def _merge_and_score_chunks(self, search_results: List[Dict], n_results: int) -> List[Dict]:
        """
        合并属于同一新闻的块，并基于检索到的块重新计算新闻的综合分数。
        采用更智能的评分策略：最大相似度 + 平均相似度 + 匹配块数量加成。
        
        Args:
            search_results: 块级搜索结果
            n_results: 最大返回结果数
        
        Returns:
            List[Dict]: 合并后的新闻级结果
        """
        news_aggregator = {}
        
        for result in search_results:
            metadata = result.get('metadata', {})
            news_id = metadata.get('news_id')
            if not news_id:
                continue
            
            distance = result.get('distance', 1.0)
            similarity_score = max(0.0, 1.0 - distance)  # 距离越小，相似度越高
            
            if news_id not in news_aggregator:
                news_aggregator[news_id] = {
                    "news_id": news_id,
                    "metadata": metadata,  # 使用第一个检索到的块的元数据作为基础
                    "total_similarity": 0.0,
                    "max_similarity": 0.0,
                    "matched_chunks_count": 0,
                    "content_chunks": [],
                    "chunk_details": []
                }
            
            agg = news_aggregator[news_id]
            agg["total_similarity"] += similarity_score
            agg["max_similarity"] = max(agg["max_similarity"], similarity_score)
            agg["matched_chunks_count"] += 1
            agg["content_chunks"].append(result.get('document', ''))
            agg["chunk_details"].append({
                'chunk_id': metadata.get('chunk_id', 1),
                'content': result.get('document', ''),
                'score': similarity_score
            })
        
        # 计算每条新闻的综合分数
        for news_id, agg in news_aggregator.items():
            # 智能评分模型：
            # - 最大相似度占70%权重（确保至少有一个高度相关的块）
            # - 平均相似度占20%权重（整体相关性）
            # - 匹配块数量加成占10%权重（覆盖度奖励）
            avg_similarity = agg['total_similarity'] / agg['matched_chunks_count']
            chunk_bonus = min(0.1, agg['matched_chunks_count'] * 0.02)  # 最多10%加成
            
            agg['composite_score'] = (
                agg['max_similarity'] * 0.7 + 
                avg_similarity * 0.2 + 
                chunk_bonus
            )
            
            # 合并内容：优先显示最相关的前3个块
            sorted_chunks = sorted(agg['chunk_details'], key=lambda x: x['score'], reverse=True)
            top_chunks = sorted_chunks[:3]
            agg['full_content'] = "\n---\n".join([chunk['content'] for chunk in top_chunks])
        
        # 按综合分数排序
        sorted_news = sorted(news_aggregator.values(), key=lambda x: x['composite_score'], reverse=True)
        
        # 格式化为最终输出
        final_results = []
        for news in sorted_news[:n_results]:
            final_results.append({
                'id': news['news_id'],
                'document': news['full_content'],
                'metadata': news['metadata'],
                'distance': 1.0 - news['composite_score'],  # 将综合分转换回距离概念
                'score': news['composite_score'],
                'matched_chunks': news['matched_chunks_count']
            })
        
        return final_results
    
    def _merge_chunks_by_news_id(self, chunk_results: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
        """
        将同一新闻的多个块合并为一个结果
        
        Args:
            chunk_results: 块级搜索结果
            max_results: 最大返回结果数
        
        Returns:
            List[Dict]: 合并后的新闻级结果
        """
        news_groups = {}
        
        # 按news_id分组
        for result in chunk_results:
            metadata = result.get('metadata', {})
            news_id = metadata.get('news_id')
            
            if news_id not in news_groups:
                news_groups[news_id] = {
                    'chunks': [],
                    'best_score': 0,
                    'metadata': metadata  # 使用第一个块的元数据作为基础
                }
            
            # 计算相似度分数（ChromaDB使用平方欧几里得距离）
            distance = result.get('distance', float('inf'))
            if distance is not None and distance != float('inf'):
                # 将距离转换为相似度分数，使用倒数函数
                # 距离越小，相似度越高
                score = 1.0 / (1.0 + distance)
            else:
                score = 0.0
            
            news_groups[news_id]['chunks'].append({
                'chunk_id': metadata.get('chunk_id', 1),
                'content': result.get('document', ''),
                'score': score
            })
            
            # 更新最佳匹配分数
            if score > news_groups[news_id]['best_score']:
                news_groups[news_id]['best_score'] = score
        
        # 构建合并结果
        merged_results = []
        for news_id, group in news_groups.items():
            # 按块编号排序
            group['chunks'].sort(key=lambda x: x['chunk_id'])
            
            # 合并内容（取最相关的前3个块）
            top_chunks = sorted(group['chunks'], key=lambda x: x['score'], reverse=True)[:3]
            merged_content = '\n\n'.join([chunk['content'] for chunk in top_chunks])
            
            merged_result = group['metadata'].copy()
            merged_result.update({
                'content': merged_content,
                'score': group['best_score'],
                'total_chunks': len(group['chunks']),
                'matched_chunks': len(top_chunks),
                'chunk_details': group['chunks']  # 保留所有块的详细信息
            })
            
            merged_results.append(merged_result)
        
        # 按分数排序并限制结果数量
        merged_results.sort(key=lambda x: x['score'], reverse=True)
        return merged_results[:max_results]
    
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
            # 通过metadata查找该新闻的所有块
            original_chunks = self.collection.get(
                where={"news_id": news_id}
            )
            
            if not original_chunks['documents']:
                logger.warning(f"未找到新闻: {news_id}")
                return []
            
            # 使用第一个块的内容进行搜索（通常是标题+开头内容，最具代表性）
            query_text = original_chunks['documents'][0]
            
            # 进行语义搜索，排除自己
            results = self.semantic_search(
                query=query_text,
                n_results=n_results * 2,  # 多获取一些，因为可能包含自己的块
                filters=None  # 不使用过滤器，在后处理中排除
            )
            
            # 过滤掉自己的新闻
            filtered_results = []
            for result in results:
                if result.get('news_id') != news_id:
                    filtered_results.append(result)
                    if len(filtered_results) >= n_results:
                        break
            
            return filtered_results
            
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
            # 获取所有符合条件的块
            results = self.collection.get(
                where={"market_relevance": {"$gte": min_relevance}},
                limit=limit * 3  # 获取更多块，因为需要按新闻ID合并
            )
            
            if not results['ids']:
                return []
            
            # 格式化块结果
            chunk_results = []
            for i, doc_id in enumerate(results['ids']):
                chunk_result = {
                    'id': doc_id,
                    'document': results['documents'][i],
                    'metadata': results['metadatas'][i],
                    'distance': 0.0  # 这里不是搜索结果，设为0
                }
                chunk_results.append(chunk_result)
            
            # 使用现有的合并方法按新闻ID合并块
            merged_results = self._merge_chunks_by_news_id(chunk_results, limit)
            
            # 为每个结果添加市场相关度信息
            for result in merged_results:
                # 从metadata中获取市场相关度（使用最高的相关度）
                max_relevance = 0.0
                for chunk in result.get('chunk_details', []):
                    chunk_relevance = chunk.get('metadata', {}).get('market_relevance', 0.0)
                    max_relevance = max(max_relevance, chunk_relevance)
                result['market_relevance'] = max_relevance
            
            # 按市场相关性排序
            merged_results.sort(
                key=lambda x: x.get('market_relevance', 0.0), 
                reverse=True
            )
            
            return merged_results
            
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
        删除新闻的所有块
        
        Args:
            news_id: 新闻ID
        
        Returns:
            bool: 是否删除成功
        """
        if self.collection is None:
            return False
        
        try:
            # 查找该新闻的所有块
            existing_chunks = self.collection.get(where={"news_id": str(news_id)})
            
            if not existing_chunks['ids']:
                logger.info(f"未找到新闻ID为 {news_id} 的任何块")
                return True
            
            # 删除所有找到的块
            self.collection.delete(ids=existing_chunks['ids'])
            logger.info(f"新闻 {news_id} 的 {len(existing_chunks['ids'])} 个块已删除成功")
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