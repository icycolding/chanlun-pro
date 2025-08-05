#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from typing import Union, List, Dict, Any
import MyTT
import numpy as np
import openai
import requests
import talib

from chanlun.cl_interface import BI, ICL, XD
from chanlun.exchange import get_exchange, Market
from chanlun.cl_utils import query_cl_chart_config, web_batch_get_cl_datas
from chanlun import config, fun
import json, datetime
from chanlun.db import db, TableByAIAnalyse
from chanlun.tools.knowledge_base import KnowledgeBase, init_default_knowledge_base


class AIAnalyseEnhanced:
    """
    增强版AI分析类，集成本地知识库功能
    """

    def __init__(self, market: str, kb_name: str = "chanlun_kb"):
        self.market = market
        self.ex = get_exchange(market=Market(self.market))
        
        # 初始化知识库
        self.kb = KnowledgeBase(kb_name)
        
        # 如果知识库为空，初始化默认知识库
        if self.kb.get_document_count() == 0:
            self.kb = init_default_knowledge_base()

        self.map_dircetion_type = {"up": "向上", "down": "向下"}
        self.map_zs_type = {"up": "上涨中枢", "down": "下跌中枢", "zd": "震荡中枢"}
        self.map_zss_direction = {
            "up": "上涨趋势",
            "down": "下跌趋势",
            None: "中枢扩展",
        }
        self.map_config_zs_type = {
            "zs_type_bz": "标准中枢",
            "zs_type_dn": "段内中枢",
            "zs_type_fx": "方向中枢",
            "zs_type_fl": "分类中枢",
        }
        self.map_mmd_type = {
            "1buy": "一买",
            "1sell": "一卖",
            "2buy": "二买",
            "2sell": "二卖",
            "3buy": "三买",
            "3sell": "三卖",
            "l2buy": "类二买",
            "l2sell": "类二卖",
            "l3buy": "类三买",
            "l3sell": "类三卖",
        }
        self.map_bc_type = {
            "bi": "笔背驰",
            "xd": "线段背驰",
            "pz": "盘整背驰",
            "qs": "趋势背驰",
        }

    def analyse_with_knowledge(self, code: str, frequency: str, 
                             use_knowledge: bool = True,
                             knowledge_categories: List[str] = None,
                             max_knowledge_docs: int = 3) -> dict:
        """
        使用知识库增强的分析方法
        
        Args:
            code: 股票代码
            frequency: 周期
            use_knowledge: 是否使用知识库
            knowledge_categories: 限制知识库搜索的分类
            max_knowledge_docs: 最大引用知识库文档数量
        
        Returns:
            dict: 分析结果
        """
        cl_config = query_cl_chart_config(self.market, code)
        stock = self.ex.stock_info(code)
        klines = self.ex.klines(code, frequency)
        cds = web_batch_get_cl_datas(self.market, code, {frequency: klines}, cl_config)
        cd = cds[0]
        
        try:
            # 生成基础提示词
            base_prompt = self.prompt(cd=cd)
            
            # 如果启用知识库，添加相关知识
            if use_knowledge:
                knowledge_prompt = self._generate_knowledge_prompt(
                    cd, base_prompt, knowledge_categories, max_knowledge_docs
                )
                final_prompt = base_prompt + "\n\n" + knowledge_prompt
            else:
                final_prompt = base_prompt
                
        except Exception as e:
            return {"ok": False, "msg": f"获取缠论当前 Prompt 异常：{e}"}
        
        print('enhanced prompt length:', len(final_prompt))
        analyse_res = self.req_llm_ai_model(final_prompt)

        if analyse_res["ok"]:
            # 记录数据库
            with db.Session() as session:
                record = TableByAIAnalyse(
                    market=self.market,
                    stock_code=code,
                    stock_name=stock["name"],
                    frequency=frequency,
                    model=analyse_res["model"],
                    msg=analyse_res["msg"],
                    prompt=final_prompt,
                    dt=datetime.datetime.now(),
                )
                session.add(record)
                session.commit()

        return {"ok": True, "msg": analyse_res["msg"]}
    
    def _generate_knowledge_prompt(self, cd: ICL, base_prompt: str, 
                                 categories: List[str] = None, 
                                 max_docs: int = 3) -> str:
        """
        根据当前缠论数据生成知识库查询并构建知识增强提示词
        
        Args:
            cd: 缠论数据对象
            base_prompt: 基础提示词
            categories: 限制搜索的知识库分类
            max_docs: 最大文档数量
        
        Returns:
            str: 知识增强提示词
        """
        # 分析当前缠论状态，生成搜索关键词
        search_queries = self._extract_search_queries(cd)
        
        # 搜索相关知识
        relevant_knowledge = []
        
        for query in search_queries:
            if categories:
                for category in categories:
                    results = self.kb.search(query, top_k=2, category=category, min_similarity=0.2)
                    relevant_knowledge.extend(results)
            else:
                results = self.kb.search(query, top_k=2, min_similarity=0.2)
                relevant_knowledge.extend(results)
        
        # 去重并按相似度排序
        seen_ids = set()
        unique_knowledge = []
        for doc in relevant_knowledge:
            if doc['id'] not in seen_ids:
                unique_knowledge.append(doc)
                seen_ids.add(doc['id'])
        
        # 按相似度排序并限制数量
        unique_knowledge.sort(key=lambda x: x['similarity'], reverse=True)
        unique_knowledge = unique_knowledge[:max_docs]
        
        if not unique_knowledge:
            return ""
        
        # 构建知识增强提示词
        knowledge_prompt = "\n## 相关缠论理论知识\n\n"
        knowledge_prompt += "以下是相关的缠论理论知识，请结合这些理论进行分析：\n\n"
        
        for i, doc in enumerate(unique_knowledge, 1):
            knowledge_prompt += f"### 知识点 {i}: {doc['title']}\n"
            knowledge_prompt += f"**分类**: {doc['category']}\n"
            knowledge_prompt += f"**内容**: {doc['content']}\n\n"
        
        knowledge_prompt += "---\n\n"
        knowledge_prompt += "**分析要求**：\n"
        knowledge_prompt += "1. 请结合以上理论知识，对当前缠论数据进行深入分析\n"
        knowledge_prompt += "2. 重点关注当前走势与理论的匹配程度\n"
        knowledge_prompt += "3. 基于理论知识，给出具体的操作建议\n"
        knowledge_prompt += "4. 如果发现与理论不符的情况，请特别说明\n"
        
        return knowledge_prompt
    
    def _extract_search_queries(self, cd: ICL) -> List[str]:
        """
        从缠论数据中提取搜索关键词
        
        Args:
            cd: 缠论数据对象
        
        Returns:
            List[str]: 搜索关键词列表
        """
        queries = []
        
        # 基础查询
        queries.append("缠论基础理论")
        
        # 根据买卖点情况添加查询
        bis = cd.get_bis()
        if bis:
            latest_bi = bis[-1]
            bi_mmds = latest_bi.line_mmds("|")
            if bi_mmds:
                for mmd in bi_mmds.split("|"):
                    if mmd in self.map_mmd_type:
                        queries.append(f"{self.map_mmd_type[mmd]}买卖点")
        
        # 根据背驰情况添加查询
        if bis:
            latest_bi = bis[-1]
            bi_bcs = latest_bi.line_bcs("|")
            if bi_bcs:
                queries.append("背驰理论")
                for bc in bi_bcs.split("|"):
                    if bc in self.map_bc_type:
                        queries.append(self.map_bc_type[bc])
        
        # 根据中枢情况添加查询
        for zs_type in cd.get_config()["zs_bi_type"]:
            zss = cd.get_bi_zss(zs_type)
            if zss:
                queries.append("中枢理论")
                if len(zss) >= 2:
                    zs_direction = cd.zss_is_qs(zss[-2], zss[-1])
                    if zs_direction == "up":
                        queries.append("上涨趋势")
                    elif zs_direction == "down":
                        queries.append("下跌趋势")
                    else:
                        queries.append("中枢扩展")
                break
        
        # 根据线段情况添加查询
        xds = cd.get_xds()
        if xds:
            queries.append("线段理论")
            latest_xd = xds[-1]
            if latest_xd.type == "up":
                queries.append("向上线段")
            else:
                queries.append("向下线段")
        
        # 去重
        return list(set(queries))
    
    def add_knowledge(self, title: str, content: str, category: str = "general") -> bool:
        """
        添加知识到知识库
        
        Args:
            title: 知识标题
            content: 知识内容
            category: 知识分类
        
        Returns:
            bool: 是否添加成功
        """
        return self.kb.add_document(title, content, category)
    
    def search_knowledge(self, query: str, top_k: int = 5, category: str = None) -> List[Dict[str, Any]]:
        """
        搜索知识库
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量
            category: 限制搜索分类
        
        Returns:
            List[Dict]: 搜索结果
        """
        return self.kb.search(query, top_k, category)
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """
        获取知识库统计信息
        
        Returns:
            Dict: 统计信息
        """
        return {
            "total_documents": self.kb.get_document_count(),
            "categories": self.kb.get_categories()
        }
    
    # 以下方法继承自原始AIAnalyse类
    def get_line_mmds(self, line: Union[BI, XD]):
        mmds = list(set(line.line_mmds("|")))
        mmds = [self.map_mmd_type[_m] for _m in mmds]
        return "|".join(mmds)

    def get_line_bcs(self, line: Union[BI, XD]):
        bcs = list(set(line.line_bcs("|")))
        bcs = [self.map_bc_type[_b] for _b in bcs]
        return "|".join(bcs)

    def prompt(self, cd: ICL) -> str:
        stock_info = self.ex.stock_info(cd.get_code())
        if stock_info is None:
            raise Exception(f"股票信息获取失败 {cd.get_code()}")
        stock_name = stock_info["name"]

        # 设置数值的精度变量
        precision = (
            len(str(stock_info["precision"])) - 1
            if "precision" in stock_info.keys()
            else 2
        )

        k = cd.get_src_klines()[-1]
        # Markdown 格式的提示词
        prompt = "```markdown\n# 缠论技术分析\n\n"
        prompt += "请根据以下缠论数据，分析后续可能走势，并按照概率排序输出。\n\n"
        prompt += "**输出格式：Markdown**\n\n"
        prompt += f"## 当前品种\n- **代码/名称**：`{cd.get_code()} - {stock_name}`\n- **数据周期**：`{cd.get_frequency()}`\n- **当前时间**：`{fun.datetime_to_str(k.date)}`\n- **最新价格**：`{round(k.c, precision)}`\n\n"

        # 笔数据
        bis_count = 9 if len(cd.get_bis()) >= 9 else len(cd.get_bis())
        prompt += f"## 最新的 {bis_count} 条缠论笔数据\n\n"
        prompt += "| 起始时间 | 结束时间 | 方向 | 起始值 | 完成状态 | 买点 | 背驰 |\n"
        prompt += "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        for bi in cd.get_bis()[-9:]:
            prompt += f"| {fun.datetime_to_str(bi.start.k.date)} | {fun.datetime_to_str(bi.end.k.date)} | {self.map_dircetion_type[bi.type]} | {round(bi.start.val, precision)} - {round(bi.end.val, precision)} | {bi.is_done()} | {self.get_line_mmds(bi)} | {self.get_line_bcs(bi)} |\n"
        prompt += "\n"

        # 线段数据
        xds_count = 3 if len(cd.get_xds()) >= 3 else len(cd.get_xds())
        prompt += f"## 最新的 {xds_count} 条缠论线段数据\n\n"
        prompt += "| 起始时间 | 结束时间 | 方向 | 起始值 | 完成状态 | 买点 | 背驰 |\n"
        prompt += "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        for xd in cd.get_xds()[-3:]:
            prompt += f"| {fun.datetime_to_str(xd.start.k.date)} | {fun.datetime_to_str(xd.end.k.date)} | {self.map_dircetion_type[xd.type]} | {round(xd.start.val, precision)} - {round(xd.end.val, precision)} | {xd.is_done()} | {self.get_line_mmds(xd)} | {self.get_line_bcs(xd)} |\n"
        prompt += "\n"

        # 中枢数据
        for zs_type in cd.get_config()["zs_bi_type"]:
            zss = cd.get_bi_zss(zs_type)
            if len(zss) >= 1:
                prompt += f"### 中枢信息：{self.map_config_zs_type[zs_type]}\n\n"
                if len(zss) >= 2:
                    zs_direction = cd.zss_is_qs(zss[-2], zss[-1])
                    prompt += f"- 最新两个中枢的位置关系：**{self.map_zss_direction[zs_direction]}**\n\n"
                else:
                    prompt += "- 目前只有单个中枢\n\n"
                prompt += "| 起始时间 | 结束时间 | 方向 | 最高值 | 最低值 | 高点 | 低点 | 级别 |\n"
                prompt += "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"
                for zs in zss[-2:]:
                    prompt += f"| {fun.datetime_to_str(zs.start.k.date)} | {fun.datetime_to_str(zs.end.k.date)} | {self.map_zs_type[zs.type]} | {round(zs.gg, precision)} | {round(zs.dd, precision)} | {round(zs.zg, precision)} | {round(zs.zd, precision)} | {zs.level} |\n"
                prompt += "\n"

        prompt += "> **数据说明**：中枢级别的意思，1表示是本级别，根据中枢内的线段数量计算，小于等于9表示本级别，大于1表示中枢内的线段大于9，中枢级别升级 (计算公式: `round(max([1, zs.line_num / 9]), 2)`)\n\n"
        prompt += "---\n"
        prompt += "请根据以上提供的笔/线段/中枢数据，进行分析。"
        return prompt

    def req_llm_ai_model(self, prompt: str) -> dict:
        """
        根据配置，调用不同的大模型服务
        """
        if config.OPENROUTER_AI_KEYS != "" and config.OPENROUTER_AI_MODEL != "":
            return self.req_openrouter_ai_model(prompt)
        if config.AI_TOKEN != "" and config.AI_MODEL != "":
            return self.req_siliconflow_ai_model(prompt)
        return {
            "ok": False,
            "msg": "未正确配置大模型的 API key 和模型名称",
            "model": "",
        }

    def req_siliconflow_ai_model(self, prompt: str) -> dict:
        """
        调用硅基流动大模型
        """
        try:
            url = "https://api.siliconflow.cn/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {config.AI_TOKEN}",
                "Content-Type": "application/json",
            }
            data = {
                "model": config.AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            response = requests.post(url, headers=headers, json=data, timeout=120)
            ai_res = response.json()
            
            if "error" in ai_res:
                return {
                    "ok": False,
                    "msg": f"AI 接口调用失败：{ai_res['error']['message']}",
                    "model": config.AI_MODEL,
                }
            
            if "choices" not in ai_res or len(ai_res["choices"]) == 0:
                return {
                    "ok": False,
                    "msg": f"AI 接口调用失败：{ai_res['message']}",
                    "model": config.AI_MODEL,
                }
            
            msg = ai_res["choices"][0]["message"]["content"]
            return {"ok": True, "msg": msg, "model": config.AI_MODEL}
            
        except Exception as e:
            return {
                "ok": False,
                "msg": f"AI 接口调用异常：{str(e)}",
                "model": config.AI_MODEL,
            }

    def req_openrouter_ai_model(self, prompt: str) -> dict:
        """
        调用OpenRouter大模型
        """
        try:
            client = openai.OpenAI(
                api_key=config.OPENROUTER_AI_KEYS,
                base_url="https://openrouter.ai/api/v1",
            )
            response = client.chat.completions.create(
                model=config.OPENROUTER_AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            
            if (
                response.choices[0].message.content == ""
                and response.choices[0].message.refusal is not None
            ):
                return {
                    "ok": False,
                    "msg": f"**[OpenAI API 错误]**: {response.choices[0].message.refusal}",
                    "model": config.OPENROUTER_AI_MODEL,
                }

            return {
                "ok": True,
                "msg": response.choices[0].message.content,
                "model": config.OPENROUTER_AI_MODEL,
            }
        except openai.OpenAIError as oe:
            return {
                "ok": False,
                "msg": f"**[OpenAI API 错误]**: {str(oe)}",
                "model": config.OPENROUTER_AI_MODEL,
            }
        except Exception as e:
            return {
                "ok": False,
                "msg": f"**[系统异常]**: {str(e)}",
                "model": config.OPENROUTER_AI_MODEL,
            }


if __name__ == "__main__":
    # 测试增强版AI分析
    ai = AIAnalyseEnhanced("a")
    
    # 查看知识库统计
    stats = ai.get_knowledge_stats()
    print(f"知识库统计: {stats}")
    
    # 测试知识搜索
    results = ai.search_knowledge("什么是一买点", top_k=2)
    print("\n知识搜索结果:")
    for result in results:
        print(f"- {result['title']}: {result['similarity']:.3f}")