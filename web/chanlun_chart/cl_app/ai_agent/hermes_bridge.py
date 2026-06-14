#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes bridge for chanlun-pro Web Chat.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from chanlun import config
from chanlun.config import get_data_path


class HermesBridge:
    DEFAULT_SKILLSET_VERSION = 1
    DEFAULT_SKILLS: List[Dict[str, str]] = [
        {
            "name": "macro-news-scout",
            "title": "Macro News Scout",
            "description": "宏观新闻研究技能，聚焦央行、通胀、就业、增长与风险事件。",
            "instructions": "先区分事件类型，再按时间线梳理新闻事实、政策含义、传导链路与可能影响的资产。对不确定信息明确标注待确认。",
        },
        {
            "name": "fx-price-action",
            "title": "FX Price Action",
            "description": "外汇研究技能，聚焦货币对、利差、美元方向、风险偏好与关键价位。",
            "instructions": "回答外汇问题时，优先结合汇率方向、利差预期、美元强弱、央行路径和事件催化。输出包含方向判断、关键驱动、风险点和需要继续跟踪的数据。",
        },
        {
            "name": "commodities-crossasset",
            "title": "Commodities Cross-Asset",
            "description": "大宗商品研究技能，联动原油、黄金、铜与全球风险资产。",
            "instructions": "分析商品时，同时看供需、美元、利率、库存、地缘冲突和相关股票/汇率联动。结论要区分短线催化和中期主线。",
        },
        {
            "name": "china-market-structure",
            "title": "China Market Structure",
            "description": "中国市场研究技能，关注 A 股、商品、人民币与政策脉络。",
            "instructions": "优先使用中国政策、产业链、资金流、人民币汇率和国内风险偏好解释市场问题。需要时区分政策预期、落地执行和市场定价阶段。",
        },
        {
            "name": "event-trading-playbook",
            "title": "Event Trading Playbook",
            "description": "事件驱动技能，适用于非农、CPI、央行会议、地缘风险等高波动时刻。",
            "instructions": "先给出事件摘要，再拆成基准情景、偏强情景、偏弱情景，分别说明对价格、波动率和风险资产的影响，并提示交易前后的验证点。",
        },
        {
            "name": "research-brief-writer",
            "title": "Research Brief Writer",
            "description": "研究简报技能，用于把新闻、价格和逻辑整理成可执行摘要。",
            "instructions": "输出采用固定结构：结论、核心事实、驱动因素、反方风险、关注列表。避免空泛表述，尽量把信息收敛成决策摘要。",
        },
    ]

    def __init__(self) -> None:
        self.repo_path = Path(
            os.environ.get("HERMES_AGENT_REPO")
            or "/Users/jiming/Documents/GitHub/hermes-agent"
        )
        self.python_path = Path(
            os.environ.get("HERMES_AGENT_PYTHON")
            or self.repo_path / "venv" / "bin" / "python"
        )
        self.model = os.environ.get("HERMES_AGENT_MODEL") or config.OPENROUTER_AI_MODEL or "google/gemini-2.5-pro-preview"
        self.base_url = os.environ.get("HERMES_AGENT_BASE_URL") or "https://openrouter.ai/api/v1"
        self.api_key = os.environ.get("OPENROUTER_API_KEY") or getattr(config, "OPENROUTER_AI_KEYS", "")
        self.tool_script_path = Path(
            os.environ.get("CHANLUN_HERMES_TOOL_SCRIPT")
            or "/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/ai_agent/hermes_chanlun_tool.py"
        )

    @staticmethod
    def get_user_hermes_home(tenant_id: str, user_id: str) -> Path:
        hermes_home = get_data_path() / "hermes_runtime" / tenant_id / user_id
        hermes_home.mkdir(parents=True, exist_ok=True)
        return hermes_home

    @staticmethod
    def _load_simple_yaml(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_simple_yaml(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml

            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _render_skill_markdown(title: str, description: str, instructions: str) -> str:
        return (
            f"---\nname: {title}\ndescription: {description}\n---\n\n"
            f"# {title}\n\n"
            f"## Purpose\n{description}\n\n"
            f"## Instructions\n{instructions.strip()}\n"
        )

    @classmethod
    def ensure_default_skills(cls, tenant_id: str, user_id: str) -> List[str]:
        hermes_home = cls.get_user_hermes_home(tenant_id=tenant_id, user_id=user_id)
        config_path = hermes_home / "config.yaml"
        cfg = cls._load_simple_yaml(config_path)
        skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
        if int(skills_cfg.get("bootstrap_version") or 0) >= cls.DEFAULT_SKILLSET_VERSION:
            return []

        skills_dir = hermes_home / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        installed: List[str] = []
        for skill in cls.DEFAULT_SKILLS:
            skill_dir = skills_dir / skill["name"]
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_md.write_text(
                    cls._render_skill_markdown(
                        skill["title"],
                        skill["description"],
                        skill["instructions"],
                    ),
                    encoding="utf-8",
                )
                installed.append(skill["name"])

        skills_cfg["bootstrap_version"] = cls.DEFAULT_SKILLSET_VERSION
        cfg["skills"] = skills_cfg
        cls._save_simple_yaml(config_path, cfg)
        return installed

    def is_ready(self) -> bool:
        return self.repo_path.exists() and self.python_path.exists() and bool(self.api_key)

    def build_env(self, tenant_id: str, user_id: str) -> Dict[str, str]:
        env = os.environ.copy()
        hermes_home = self.get_user_hermes_home(tenant_id=tenant_id, user_id=user_id)
        env["HERMES_HOME"] = str(hermes_home)
        env["OPENROUTER_API_KEY"] = self.api_key
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _route_market_action(self, message: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        context = context or {}
        text = str(message or "").lower()
        if any(keyword in text for keyword in ["回撤", "最大跌幅", "最大回落", "drawdown"]):
            return "drawdown_analysis"
        if any(keyword in text for keyword in ["历史事件图", "事件图", "相似事件", "历史事件", "event chart"]):
            return "event_chart_review"
        if any(keyword in text for keyword in ["历史", "复盘", "回顾", "review", "history"]):
            return "historical_analysis"
        if any(keyword in text for keyword in ["快照", "snapshot", "价格", "走势", "盘面", "交易", "下单"]):
            if context.get("market") and context.get("code"):
                return "market_data_view"
        if context.get("market") and context.get("code"):
            if any(keyword in text for keyword in ["推演", "主题", "分析", "为什么", "逻辑", "bias", "view", "研究", "报告", "研报"]):
                return "theme_simulation"
        return None

    def _invoke_chanlun_tool(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        process = subprocess.run(
            [
                sys.executable,
                str(self.tool_script_path),
                "--action",
                action,
                "--payload",
                json.dumps(payload, ensure_ascii=False),
            ],
            cwd=str(self.tool_script_path.parent),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if process.returncode != 0:
            raise RuntimeError((process.stderr or process.stdout or "chanlun tool execution failed").strip())
        return self._load_json_from_output(process.stdout)

    @staticmethod
    def _load_json_from_output(output: str) -> Dict[str, Any]:
        normalized = str(output or "").strip()
        if not normalized:
            raise ValueError("empty json output")
        try:
            return json.loads(normalized)
        except Exception:
            pass

        for line in reversed(normalized.splitlines()):
            candidate = line.strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except Exception:
                continue

        match = re.search(r"(\{[\s\S]*\})\s*$", normalized)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"unable to parse json output: {normalized[:500]}")

    def _load_enabled_skills(self, tenant_id: str, user_id: str) -> List[Dict[str, Any]]:
        self.ensure_default_skills(tenant_id=tenant_id, user_id=user_id)
        hermes_home = self.get_user_hermes_home(tenant_id=tenant_id, user_id=user_id)
        config_path = hermes_home / "config.yaml"
        disabled_names: set[str] = set()
        if config_path.exists():
            try:
                import yaml

                cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
                disabled = skills_cfg.get("disabled") or []
                if isinstance(disabled, str):
                    disabled = [disabled]
                disabled_names = {str(item).strip() for item in disabled if str(item).strip()}
            except Exception:
                disabled_names = set()
        skills_dir = hermes_home / "skills"
        results: List[Dict[str, Any]] = []
        if not skills_dir.exists():
            return results
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name in disabled_names:
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text(encoding="utf-8")
            title = skill_dir.name
            description = ""
            if content.startswith("---"):
                end = content.find("\n---", 3)
                if end != -1:
                    frontmatter = content[3:end].strip()
                    for line in frontmatter.splitlines():
                        if ":" not in line:
                            continue
                        key, _, value = line.partition(":")
                        key = key.strip()
                        value = value.strip()
                        if key == "name":
                            title = value or title
                        elif key == "description":
                            description = value
            results.append(
                {
                    "name": skill_dir.name,
                    "title": title,
                    "description": description,
                    "content": content,
                }
            )
        return results

    def _select_relevant_skills(
        self,
        message: str,
        skills: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        context = context or {}
        selected_name = str(context.get("skill_name") or "").strip().lower()
        if selected_name:
            matched = [skill for skill in skills if skill["name"].lower() == selected_name]
            if matched:
                return matched[:1]
        haystack = " ".join(
            [
                str(message or "").lower(),
                str(context.get("theme") or "").lower(),
                str(context.get("code") or "").lower(),
            ]
        )
        matched: List[Dict[str, Any]] = []
        for skill in skills:
            candidates = [
                str(skill.get("name") or "").lower(),
                str(skill.get("title") or "").lower(),
            ]
            if any(token and token in haystack for token in candidates):
                matched.append(skill)
        return matched[:2]

    def stream_chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        session_id: str,
        tenant_id: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        if not self.repo_path.exists():
            raise RuntimeError(f"Hermes repo not found: {self.repo_path}")
        if not self.python_path.exists():
            raise RuntimeError(f"Hermes python not found: {self.python_path}")
        if not self.api_key:
            raise RuntimeError("Hermes OpenRouter API key not configured")

        payload = {
            "message": message,
            "history": history[-24:],
            "session_id": session_id,
            "model": self.model,
            "base_url": self.base_url,
        }
        context = context or {}
        enabled_skills = self._load_enabled_skills(tenant_id=tenant_id, user_id=user_id)
        selected_skills = self._select_relevant_skills(message, enabled_skills, context)
        payload["context"] = context
        payload["selected_skills"] = [
            {
                "name": skill["name"],
                "title": skill["title"],
                "description": skill["description"],
                "content": skill["content"][:8000],
            }
            for skill in selected_skills
        ]
        tool_action = self._route_market_action(message, context)
        tool_result = None
        if tool_action:
            tool_payload = {
                "message": message,
                "theme_text": message,
                "theme_label": str(context.get("theme") or "").strip(),
                "current_market": str(context.get("market") or "").strip(),
                "current_code": str(context.get("code") or "").strip(),
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            }
            tool_result = self._invoke_chanlun_tool(tool_action, tool_payload)
            payload["tool_result"] = tool_result
        runner = textwrap.dedent(
            """
            import json
            import sys
            from run_agent import AIAgent

            payload = json.loads(sys.stdin.read())
            history = payload.get("history") or []
            tool_result = payload.get("tool_result")
            context = payload.get("context") or {}
            selected_skills = payload.get("selected_skills") or []

            def on_delta(text):
                if text:
                    print(json.dumps({"type": "content", "content": text}, ensure_ascii=False), flush=True)

            skill_context = ""
            if selected_skills:
                skill_parts = []
                for item in selected_skills:
                    skill_parts.append(
                        f"[Skill] {item.get('title') or item.get('name')}\\n"
                        f"Description: {item.get('description') or ''}\\n"
                        f"{item.get('content') or ''}"
                    )
                skill_context = "\\n\\n".join(skill_parts)

            agent = AIAgent(
                model=payload.get("model") or "google/gemini-2.5-pro-preview",
                base_url=payload.get("base_url") or "https://openrouter.ai/api/v1",
                session_id=payload.get("session_id"),
                quiet_mode=True,
                enabled_toolsets=["web"],
                disabled_toolsets=["terminal"],
                ephemeral_system_prompt=(
                    "你是 chanlun-pro 的 Hermes 编排助手。"
                    "优先基于已提供的结构化工具结果回答，不要编造不存在的市场数据。"
                    f" 当前上下文: {json.dumps(context, ensure_ascii=False)}"
                    + (f"\\n\\n用户启用/匹配到的技能如下:\\n{skill_context}" if skill_context else "")
                ),
            )
            user_message = payload.get("message") or ""
            if tool_result:
                tool_context = json.dumps(tool_result, ensure_ascii=False)
                user_message = f"{user_message}\\n\\n[chanlun_tool_result]\\n{tool_context}"
            result = agent.run_conversation(
                user_message,
                conversation_history=history,
                stream_callback=on_delta,
            )
            print(json.dumps({"type": "done", "final_response": result.get("final_response", "")}, ensure_ascii=False), flush=True)
            """
        )
        process = subprocess.Popen(
            [str(self.python_path), "-c", runner],
            cwd=str(self.repo_path),
            env=self.build_env(tenant_id=tenant_id, user_id=user_id),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(json.dumps(payload, ensure_ascii=False), timeout=180)
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "Hermes execution failed").strip())
        done_final = ""
        emitted_content = False
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") == "done":
                done_final = str(event.get("final_response") or "")
                continue
            if event.get("type") == "content":
                emitted_content = True
            yield json.dumps(event, ensure_ascii=False)
        if done_final and not emitted_content:
            yield json.dumps({"type": "content", "content": done_final}, ensure_ascii=False)
