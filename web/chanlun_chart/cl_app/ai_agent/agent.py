#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGI Agent 核心编排模块 (RAG 增强版)
采用 Intent-First 架构，强制先检索后生成，确保信息来源真实
"""

import json
import logging
import os
import openai
from typing import List, Dict, Any, Generator, Optional

from chanlun import config
from cl_app.news_vector_db import NewsVectorDB
from .product_db import get_product_db

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AGIAgent:
    """
    AGI 市场助手 Agent
    
    逻辑流程:
    1. 意图识别 (Intent Classification)
    2. 强制检索 (Mandatory Retrieval)
    3. 上下文注入 (Context Injection)
    4. 回答生成 (Generation)
    """
    
    def __init__(self):
        # 初始化 OpenAI 客户端
        self.client = openai.OpenAI(
            api_key=config.OPENROUTER_AI_KEYS,
            base_url="https://openrouter.ai/api/v1"
        )
        self.model = config.OPENROUTER_AI_MODEL
        
        # 初始化数据库
        self.news_db = NewsVectorDB() 
        self.product_db = get_product_db()

    def _classify_intent(self, query: str) -> str:
        """
        简单意图识别
        Returns: 'NEWS', 'PRODUCT', 'CHAT'
        """
        query = query.lower()
        
        # 产品/投资建议类关键词
        product_keywords = [
            "买什么", "推荐", "代码", "symbol", "合约", "对冲", "投资", "建仓", "做多", "做空",
            "what to buy", "invest", "recommend"
        ]
        if any(k in query for k in product_keywords):
            return "PRODUCT"
            
        # 显式的新闻/行情关键词
        news_keywords = [
            "新闻", "消息", "发生", "事件", "为什么", "原因", "数据", "非农", "cpi", "会议",
            "news", "happen", "why", "event", "data"
        ]
        if any(k in query for k in news_keywords):
            return "NEWS"
            
        # 如果涉及具体标的名称（如黄金、原油），默认也是查新闻/基本面
        # 这里可以扩展更多逻辑，简单起见，如果包含特定标的，倾向于查新闻
        # 但如果只是打招呼，就 CHAT
        chat_keywords = ["你好", "hello", "hi", "是谁", "who are you"]
        if any(k in query for k in chat_keywords) and len(query) < 20:
            return "CHAT"
            
        # 默认回退到 NEWS，因为这是一个市场助手
        return "NEWS"

    def chat_stream(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        """
        流式对话核心方法
        """
        # 获取用户最后一条消息
        user_query = messages[-1]['content']
        intent = self._classify_intent(user_query)
        
        context_str = ""
        citation_event = None
        
        try:
            # --- 阶段 1: 检索 (Retrieval) ---
            
            if intent == "NEWS":
                yield json.dumps({"type": "thinking", "content": "正在检索市场新闻数据库..."})
                
                # 调用 NewsDB
                results = self.news_db.semantic_search_reimagined(user_query, n_results=3)
                
                if results:
                    # 格式化前端展示数据
                    display_data = []
                    context_lines = []
                    
                    for r in results:
                        display_data.append({
                            "title": r.get("title"),
                            "content": r.get("content", "")[:200],
                            "time": r.get("published_at"),
                            "source": r.get("source"),
                            "score": r.get("score")
                        })
                        # 构造 Prompt 上下文 (精简以提升速度)
                        context_lines.append(f"标题: {r.get('title')}\n内容: {r.get('content', '')[:150]}...\n")
                    
                    citation_event = {
                        "type": "citation",
                        "tool": "search_market_news",
                        "data": display_data
                    }
                    context_str = "\n---\n".join(context_lines)
                else:
                    yield json.dumps({"type": "thinking", "content": "未找到相关新闻，尝试直接分析..."})

            elif intent == "PRODUCT":
                yield json.dumps({"type": "thinking", "content": "正在检索产品数据库..."})
                
                # 调用 ProductDB
                results = self.product_db.search(user_query, top_k=3)
                
                if results:
                    display_data = []
                    context_lines = []
                    
                    for r in results:
                        meta = r.get("metadata", {})
                        display_data.append({
                            "symbol": meta.get("symbol"),
                            "name": meta.get("name_cn"),
                            "description": r.get("document"),
                            "score": r.get("score")
                        })
                        context_lines.append(f"{meta.get('name_cn')}: {r.get('document')[:150]}...")
                    
                    citation_event = {
                        "type": "citation",
                        "tool": "search_investment_products",
                        "data": display_data
                    }
                    context_str = "\n---\n".join(context_lines)

            # 发送引用卡片给前端 (如果有)
            if citation_event:
                yield json.dumps(citation_event)

            # --- 阶段 2: 生成 (Generation) ---
            
            # 构造 System Prompt
            base_prompt = """你是一位专业的金融市场助手 (AGI Market Intelligence)。
你的任务是根据提供的【参考资料库】来回答用户的问题。

原则：
1. **基于事实**：回答必须基于参考资料中的信息。如果参考资料中没有相关信息，请明确说明“数据库中暂无相关数据”，不要编造。
2. **结构化**：
   - 市场综述：一句话概括。
   - 关键要点：列出参考资料中的核心事实。
   - 深度分析：结合资料分析影响。
3. **引用**：在提到具体数据或观点时，可以自然地提及来源（如“据华尔街日报报道...”）。

回答风格：专业、客观、简洁。
"""
            
            if context_str:
                system_content = f"{base_prompt}\n\n【参考资料库】:\n{context_str}"
            else:
                # 如果没有检索到或意图是闲聊
                system_content = "你是一位专业的金融市场助手。请专业地回答用户的问题。"
            
            # 替换或插入 System Message
            # 为了不破坏原有 messages 结构，我们在最前面插入一个临时的 system message
            # 并且不保留在历史中（因为 context 太长了，只在当前轮次有效）
            
            # 注意：OpenAI API 通常把 System Message 放在第一位
            messages_for_llm = [{"role": "system", "content": system_content}] + messages
            
            # 调用 LLM
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages_for_llm,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield json.dumps({"type": "content", "content": chunk.choices[0].delta.content})

        except Exception as e:
            logger.error(f"Chat error: {e}")
            yield json.dumps({"type": "error", "content": str(e)})
