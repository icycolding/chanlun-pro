#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品向量数据库处理模块
使用 Chroma DB 存储产品/商品向量数据，支持语义搜索

主要功能:
1. 期货商品信息向量化存储
2. 产品语义推荐搜索
3. 产品的增删改查 (CRUD)
"""

import os
import logging
import uuid
from typing import List, Dict, Optional, Any
from dataclasses import asdict

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

# 导入期货商品映射
import importlib.util
try:
    from cl_app.futures_commodity_mapping import futures_mapper
except ImportError:
    try:
        # 动态加载以绕过 cl_app 包初始化 (避免 PyArmor 依赖)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.normpath(os.path.join(current_dir, '../futures_commodity_mapping.py'))
        
        spec = importlib.util.spec_from_file_location("futures_commodity_mapping", file_path)
        module = importlib.util.module_from_spec(spec)
        # sys.modules["futures_commodity_mapping"] = module # 可选
        spec.loader.exec_module(module)
        futures_mapper = module.futures_mapper
    except Exception as e:
        logging.error(f"Failed to load futures_mapper: {e}")
        futures_mapper = None

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProductVectorDB:
    """
    产品向量数据库管理类
    
    Collection: product_vectors
    存储字段:
       - id: symbol (如 CL, GC)
       - document: 语义化描述文本
       - metadata: {name, category, exchange, ...}
    """
    
    def __init__(self, db_path: Optional[str] = None, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """
        初始化向量数据库
        """
        if db_path is None:
            # 默认数据库路径，与 NewsVectorDB 保持一致
            # 位于 web/chanlun_chart/chroma_db
            module_dir = os.path.dirname(os.path.abspath(__file__))
            self.db_path = os.path.normpath(os.path.join(module_dir, '..', '..', 'chroma_db'))
        else:
            self.db_path = db_path
            
        self.model_name = model_name
        self.client = None
        self.collection = None
        self.embedding_model = None
        
        # 确保数据库目录存在
        os.makedirs(self.db_path, exist_ok=True)
        
        # 初始化
        self._init_db()
        self._init_model()
        self._init_collection()

    def _init_db(self):
        """初始化 ChromaDB 客户端"""
        if not chromadb:
            logger.error("ChromaDB not installed")
            return
            
        try:
            self.client = chromadb.PersistentClient(path=self.db_path)
            logger.info(f"Connected to ChromaDB at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to connect to ChromaDB: {e}")

    def _init_model(self):
        """初始化 Embedding 模型"""
        if not SentenceTransformer:
            logger.error("sentence-transformers not installed")
            return
            
        try:
            # 使用与 NewsVectorDB 相同的模型
            self.embedding_model = SentenceTransformer(self.model_name)
            logger.info(f"Loaded embedding model: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")

    def _init_collection(self):
        """初始化或获取 Collection"""
        if not self.client:
            return
            
        try:
            # 获取或创建集合
            self.collection = self.client.get_or_create_collection(
                name="product_vectors",
                metadata={"hnsw:space": "cosine"}
            )
            
            # 检查是否需要初始化数据
            if self.collection.count() == 0 and futures_mapper:
                logger.info("Product collection is empty, initializing data...")
                self.init_data_from_mapper()
            else:
                logger.info(f"Product collection loaded with {self.collection.count()} items")
                
        except Exception as e:
            logger.error(f"Failed to get/create collection: {e}")

    def _construct_document(self, data: Dict[str, Any]) -> str:
        """根据结构化数据构造语义文本"""
        # 必填字段
        symbol = data.get('symbol', '')
        name_cn = data.get('name_cn', '')
        name_en = data.get('name_en', '')
        category = data.get('category', '')
        exchange = data.get('exchange', '')
        
        # 列表字段处理
        def list_to_str(key):
            val = data.get(key, [])
            if isinstance(val, list):
                return ', '.join(val)
            return str(val)

        desc_parts = [
            f"{name_cn} ({name_en}, {symbol}) 是 {exchange} 交易所的 {category} 类产品。",
            f"中文关键词: {list_to_str('keywords')}。",
            f"相关影响因素: {list_to_str('price_factors')}。",
            f"看涨逻辑: {data.get('bullish_logic', '暂无')}。",
            f"看跌逻辑: {data.get('bearish_logic', '暂无')}。"
        ]
        
        return " ".join(desc_parts)

    def add_product(self, product_data: Dict[str, Any]) -> bool:
        """
        新增产品
        Args:
            product_data: 包含 symbol, name_cn, name_en, category, exchange, keywords 等字段的字典
        """
        if not self.collection or not self.embedding_model:
            return False
            
        try:
            symbol = product_data.get('symbol')
            if not symbol:
                raise ValueError("Symbol is required")
                
            doc_id = f"product_{symbol}"
            document = self._construct_document(product_data)
            
            # 准备 Metadata (扁平化，Chroma不支持嵌套字典)
            meta = {k: str(v) for k, v in product_data.items()}
            meta['type'] = 'product'
            
            embedding = self.embedding_model.encode([document]).tolist()
            
            self.collection.add(
                ids=[doc_id],
                documents=[document],
                embeddings=embedding,
                metadatas=[meta]
            )
            logger.info(f"Added product: {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to add product: {e}")
            return False

    def update_product(self, symbol: str, product_data: Dict[str, Any]) -> bool:
        """更新产品 (覆盖模式)"""
        # Chroma 的 upsert 可以处理，或者先 delete 后 add
        # 这里直接用 upsert 逻辑 (add 会报错如果ID存在，所以用 upsert 或 update)
        # 但为了稳妥，先构造数据
        
        if not self.collection or not self.embedding_model:
            return False
            
        try:
            if not product_data.get('symbol'):
                product_data['symbol'] = symbol
                
            doc_id = f"product_{symbol}"
            document = self._construct_document(product_data)
            meta = {k: str(v) for k, v in product_data.items()}
            meta['type'] = 'product'
            
            embedding = self.embedding_model.encode([document]).tolist()
            
            self.collection.upsert(
                ids=[doc_id],
                documents=[document],
                embeddings=embedding,
                metadatas=[meta]
            )
            logger.info(f"Updated product: {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to update product: {e}")
            return False

    def delete_product(self, symbol: str) -> bool:
        """删除产品"""
        if not self.collection:
            return False
            
        try:
            doc_id = f"product_{symbol}"
            self.collection.delete(ids=[doc_id])
            logger.info(f"Deleted product: {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete product: {e}")
            return False

    def get_product(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单个产品详情"""
        if not self.collection:
            return None
            
        try:
            doc_id = f"product_{symbol}"
            result = self.collection.get(ids=[doc_id], include=['metadatas', 'documents'])
            
            if result['ids']:
                return {
                    'symbol': symbol,
                    'metadata': result['metadatas'][0],
                    'document': result['documents'][0]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get product: {e}")
            return None

    def get_all_products(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取所有产品列表 (用于后台展示)"""
        if not self.collection:
            return []
            
        try:
            # Chroma 的 get 不支持无条件返回所有，必须分页或者指定 ID
            # 但如果 limit 足够大，可以返回前 N 个
            # 注意: Chroma 默认 limit 可能是 10
            result = self.collection.get(limit=limit, include=['metadatas'])
            
            products = []
            for i in range(len(result['ids'])):
                products.append({
                    'id': result['ids'][i],
                    'metadata': result['metadatas'][i]
                })
            return products
        except Exception as e:
            logger.error(f"Failed to get all products: {e}")
            return []

    def init_data_from_mapper(self):
        """从 FuturesCommodityMapping 导入数据"""
        if not self.collection or not self.embedding_model or not futures_mapper:
            return

        documents = []
        metadatas = []
        ids = []

        # 遍历所有期货合约
        contracts = futures_mapper.futures_contracts
        
        for symbol, info in contracts.items():
            # 构造字典以便复用 _construct_document
            data = {
                'symbol': info.symbol,
                'name_cn': info.name_cn,
                'name_en': info.name_en,
                'category': info.category,
                'exchange': info.exchange,
                'keywords': info.keywords + info.related_news_keywords,
                'price_factors': info.seasonal_factors + info.geopolitical_keywords
            }
            
            # 补充商品信息
            commodity_info = futures_mapper.get_commodity_info(symbol)
            if commodity_info:
                data['keywords'].extend(commodity_info.supply_keywords)
                data['keywords'].extend(commodity_info.demand_keywords)
                data['price_factors'].extend(commodity_info.price_factors)
            
            document = self._construct_document(data)
            
            # 准备 Metadata
            meta = {k: str(v) for k, v in data.items()}
            meta['type'] = 'futures'
            
            documents.append(document)
            metadatas.append(meta)
            ids.append(f"product_{symbol}")

        # 批量写入
        if documents:
            try:
                embeddings = self.embedding_model.encode(documents).tolist()
                
                self.collection.add(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas
                )
                logger.info(f"Successfully initialized {len(documents)} products")
            except Exception as e:
                logger.error(f"Failed to initialize data: {e}")

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        语义搜索产品
        """
        if not self.collection or not self.embedding_model:
            return []
            
        try:
            query_embedding = self.embedding_model.encode([query]).tolist()
            
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                include=["metadatas", "documents", "distances"]
            )
            
            formatted_results = []
            if results['ids'] and len(results['ids']) > 0:
                for i in range(len(results['ids'][0])):
                    item = {
                        "id": results['ids'][0][i],
                        "metadata": results['metadatas'][0][i],
                        "document": results['documents'][0][i],
                        "score": results['distances'][0][i] if 'distances' in results else 0
                    }
                    formatted_results.append(item)
                    
            return formatted_results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

# 全局单例
_product_db_instance = None

def get_product_db():
    global _product_db_instance
    if _product_db_instance is None:
        _product_db_instance = ProductVectorDB()
    return _product_db_instance

if __name__ == "__main__":
    # 修正路径以便直接运行
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../src')))
    
    # 测试代码
    db = get_product_db()
    
    # 强制初始化检查
    if db.collection.count() == 0:
        print("Initializing data...")
        db.init_data_from_mapper()
    
    test_queries = [
        "看涨美元买什么",
        "中东局势紧张",
        "通胀高企",
        "新能源汽车需求增加"
    ]
    
    print(f"Collection count: {db.collection.count()}")
    
    for q in test_queries:
        print(f"\nQuery: {q}")
        results = db.search(q)
        for r in results:
            print(f"  - [{r['metadata']['symbol']}] {r['metadata']['name_cn']} (Score: {r['score']:.4f})")
