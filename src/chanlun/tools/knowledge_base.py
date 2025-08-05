#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import pickle
from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import jieba
import re
from chanlun import config
from chanlun.fun import get_data_path


class KnowledgeBase:
    """
    本地知识库管理类
    支持文档存储、检索和相似度匹配
    """
    
    def __init__(self, kb_name: str = "chanlun_kb"):
        self.kb_name = kb_name
        self.kb_path = get_data_path() / "knowledge_base" / kb_name
        self.kb_path.mkdir(parents=True, exist_ok=True)
        
        # 知识库文件路径
        self.documents_file = self.kb_path / "documents.json"
        self.vectors_file = self.kb_path / "vectors.pkl"
        self.vectorizer_file = self.kb_path / "vectorizer.pkl"
        
        # 初始化数据结构
        self.documents: List[Dict[str, Any]] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.document_vectors: Optional[np.ndarray] = None
        
        # 加载现有知识库
        self.load_knowledge_base()
    
    def preprocess_text(self, text: str) -> str:
        """
        文本预处理：分词、去除标点符号等
        """
        # 去除特殊字符，保留中文、英文、数字
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', ' ', text)
        # 使用jieba分词
        words = jieba.cut(text)
        return ' '.join(words)
    
    def add_document(self, title: str, content: str, category: str = "general", 
                    metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        添加文档到知识库
        
        Args:
            title: 文档标题
            content: 文档内容
            category: 文档分类（如：缠论理论、实战案例、技术指标等）
            metadata: 额外的元数据
        
        Returns:
            bool: 是否添加成功
        """
        try:
            doc_id = len(self.documents)
            processed_content = self.preprocess_text(content)
            
            document = {
                "id": doc_id,
                "title": title,
                "content": content,
                "processed_content": processed_content,
                "category": category,
                "metadata": metadata or {},
                "created_at": str(Path().cwd())
            }
            
            self.documents.append(document)
            
            # 重新构建向量索引
            self._rebuild_vectors()
            
            # 保存到文件
            self.save_knowledge_base()
            
            return True
        except Exception as e:
            print(f"添加文档失败: {e}")
            return False
    
    def search(self, query: str, top_k: int = 5, category: Optional[str] = None, 
              min_similarity: float = 0.1) -> List[Dict[str, Any]]:
        """
        搜索相关文档
        
        Args:
            query: 查询文本
            top_k: 返回最相关的文档数量
            category: 限制搜索的文档分类
            min_similarity: 最小相似度阈值
        
        Returns:
            List[Dict]: 相关文档列表，包含相似度分数
        """
        if not self.documents or self.vectorizer is None:
            return []
        
        try:
            # 预处理查询文本
            processed_query = self.preprocess_text(query)
            
            # 将查询转换为向量
            query_vector = self.vectorizer.transform([processed_query])
            
            # 计算相似度
            similarities = cosine_similarity(query_vector, self.document_vectors)[0]
            
            # 获取相似度排序的文档索引
            doc_indices = np.argsort(similarities)[::-1]
            
            results = []
            for idx in doc_indices:
                if len(results) >= top_k:
                    break
                
                similarity = similarities[idx]
                if similarity < min_similarity:
                    continue
                
                doc = self.documents[idx]
                
                # 如果指定了分类，过滤不匹配的文档
                if category and doc["category"] != category:
                    continue
                
                result = {
                    "id": doc["id"],
                    "title": doc["title"],
                    "content": doc["content"],
                    "category": doc["category"],
                    "metadata": doc["metadata"],
                    "similarity": float(similarity)
                }
                results.append(result)
            
            return results
        
        except Exception as e:
            print(f"搜索失败: {e}")
            return []
    
    def _rebuild_vectors(self):
        """
        重新构建文档向量索引
        """
        if not self.documents:
            return
        
        # 提取所有文档的处理后内容
        processed_contents = [doc["processed_content"] for doc in self.documents]
        
        # 创建或更新TF-IDF向量化器
        if self.vectorizer is None:
            # 根据文档数量调整参数，避免max_df和min_df冲突
            doc_count = len(processed_contents)
            max_df = min(0.95, max(0.5, doc_count - 1)) if doc_count > 1 else 1.0
            
            self.vectorizer = TfidfVectorizer(
                max_features=5000,
                stop_words=None,  # 中文没有内置停用词
                ngram_range=(1, 2),  # 使用1-gram和2-gram
                min_df=1,
                max_df=max_df
            )
        
        # 构建文档向量矩阵
        self.document_vectors = self.vectorizer.fit_transform(processed_contents)
    
    def save_knowledge_base(self):
        """
        保存知识库到文件
        """
        try:
            # 保存文档数据
            with open(self.documents_file, 'w', encoding='utf-8') as f:
                json.dump(self.documents, f, ensure_ascii=False, indent=2)
            
            # 保存向量数据
            if self.document_vectors is not None:
                with open(self.vectors_file, 'wb') as f:
                    pickle.dump(self.document_vectors, f)
            
            # 保存向量化器
            if self.vectorizer is not None:
                with open(self.vectorizer_file, 'wb') as f:
                    pickle.dump(self.vectorizer, f)
            
            print(f"知识库已保存到: {self.kb_path}")
        
        except Exception as e:
            print(f"保存知识库失败: {e}")
    
    def load_knowledge_base(self):
        """
        从文件加载知识库
        """
        try:
            # 加载文档数据
            if self.documents_file.exists():
                with open(self.documents_file, 'r', encoding='utf-8') as f:
                    self.documents = json.load(f)
            
            # 加载向量数据
            if self.vectors_file.exists():
                with open(self.vectors_file, 'rb') as f:
                    self.document_vectors = pickle.load(f)
            
            # 加载向量化器
            if self.vectorizer_file.exists():
                with open(self.vectorizer_file, 'rb') as f:
                    self.vectorizer = pickle.load(f)
            
            print(f"知识库已加载，包含 {len(self.documents)} 个文档")
        
        except Exception as e:
            print(f"加载知识库失败: {e}")
            # 初始化空的知识库
            self.documents = []
            self.vectorizer = None
            self.document_vectors = None
    
    def get_categories(self) -> List[str]:
        """
        获取所有文档分类
        """
        categories = set(doc["category"] for doc in self.documents)
        return list(categories)
    
    def get_document_count(self) -> int:
        """
        获取文档总数
        """
        return len(self.documents)
    
    def delete_document(self, doc_id: int) -> bool:
        """
        删除指定文档
        """
        try:
            self.documents = [doc for doc in self.documents if doc["id"] != doc_id]
            # 重新分配ID
            for i, doc in enumerate(self.documents):
                doc["id"] = i
            
            # 重新构建向量索引
            self._rebuild_vectors()
            
            # 保存更改
            self.save_knowledge_base()
            
            return True
        except Exception as e:
            print(f"删除文档失败: {e}")
            return False
    
    def clear_knowledge_base(self) -> bool:
        """
        清空知识库
        """
        try:
            self.documents = []
            self.vectorizer = None
            self.document_vectors = None
            
            # 删除文件
            for file_path in [self.documents_file, self.vectors_file, self.vectorizer_file]:
                if file_path.exists():
                    file_path.unlink()
            
            return True
        except Exception as e:
            print(f"清空知识库失败: {e}")
            return False


def init_default_knowledge_base():
    """
    初始化默认的缠论知识库
    """
    kb = KnowledgeBase("chanlun_kb")
    
    # 如果知识库为空，添加一些基础的缠论知识
    if kb.get_document_count() == 0:
        # 基础缠论理论
        kb.add_document(
            title="缠论基础 - 分型定义",
            content="""分型是缠论中的基础概念。顶分型：第二根K线的高点是三根K线中最高的，且第二根K线的低点大于等于第一根和第三根K线的低点。底分型：第二根K线的低点是三根K线中最低的，且第二根K线的高点小于等于第一根和第三根K线的高点。分型是构成笔的基础。""",
            category="缠论理论"
        )
        
        kb.add_document(
            title="缠论基础 - 笔的定义",
            content="""笔是连接两个相邻分型的直线。笔的形成需要满足：1. 两个分型之间至少包含一根K线；2. 分型确认后才能形成笔；3. 笔的方向由起始分型决定，顶分型开始的是向下笔，底分型开始的是向上笔。笔是构成线段的基础单位。""",
            category="缠论理论"
        )
        
        kb.add_document(
            title="缠论基础 - 线段定义",
            content="""线段是由至少三笔构成的更大级别结构。线段的特征包括：1. 至少包含三笔；2. 线段内部的笔不能被后续笔完全包含；3. 线段的确认需要特定的破坏条件。线段是构成中枢的基础。""",
            category="缠论理论"
        )
        
        kb.add_document(
            title="缠论基础 - 中枢定义",
            content="""中枢是缠论中的核心概念，定义为至少由三段同级别走势类型的重叠部分。中枢具有以下特征：1. 至少三段走势重叠；2. 中枢有明确的高点和低点；3. 中枢内部的震荡体现了多空力量的平衡；4. 中枢的突破往往预示着趋势的延续或转折。""",
            category="缠论理论"
        )
        
        kb.add_document(
            title="缠论买卖点 - 第一类买卖点",
            content="""第一类买点：向下走势的最后一个中枢的第三类买点。第一类卖点：向上走势的最后一个中枢的第三类卖点。第一类买卖点是趋势转折的重要信号，通常出现在趋势的末端，是抄底或逃顶的关键位置。""",
            category="买卖点理论"
        )
        
        kb.add_document(
            title="缠论买卖点 - 第二类买卖点",
            content="""第二类买点：第一类买点后的第一次回调不跌破第一类买点时形成。第二类卖点：第一类卖点后的第一次反弹不突破第一类卖点时形成。第二类买卖点是趋势确认的信号，风险相对较小，是较为安全的入场点。""",
            category="买卖点理论"
        )
        
        kb.add_document(
            title="缠论买卖点 - 第三类买卖点",
            content="""第三类买点：一个中枢的第一次离开。第三类卖点：一个中枢的第一次离开。第三类买卖点是趋势延续的信号，通常出现在中枢突破时，是追涨杀跌的关键位置。需要注意假突破的风险。""",
            category="买卖点理论"
        )
        
        kb.add_document(
            title="缠论背驰理论",
            content="""背驰是缠论中判断趋势转折的重要工具。背驰的判断需要比较两段同级别走势的力度，通常使用MACD等指标辅助判断。背驰分为趋势背驰和盘整背驰。趋势背驰往往预示着大级别的转折，而盘整背驰则可能只是小级别的调整。""",
            category="背驰理论"
        )
        
        print("已初始化默认缠论知识库")
    
    return kb


if __name__ == "__main__":
    # 测试知识库功能
    kb = init_default_knowledge_base()
    
    # 测试搜索
    results = kb.search("什么是分型", top_k=3)
    print("\n搜索结果:")
    for result in results:
        print(f"标题: {result['title']}")
        print(f"相似度: {result['similarity']:.3f}")
        print(f"内容: {result['content'][:100]}...")
        print("-" * 50)