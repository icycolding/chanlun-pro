# -*- coding: utf-8 -*-
"""个股「分析观点」：抓东方财富股吧评论 → claude 分类总结 → 报告(JSON 缓存)。

设计对齐 serenity_aistocks 的「点击分析」：ThreadPoolExecutor + 内存任务表 +
前端轮询。数据源为 EastmoneyGubaProvider(无需 cookie/代理,国内直连)。

- POST /serenity/opinions/analyze          启动分析,返回 task_id
- GET  /serenity/opinions/task/<task_id>   轮询任务状态/结果
- GET  /serenity/opinions/<name>           读取已生成的观点报告
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

from flask import jsonify, request

try:  # 与现有路由一致地做登录保护;缺失时降级为放行(内部工具)
    from flask_login import login_required
except Exception:  # pragma: no cover
    def login_required(func):
        return func

from . import community_providers as _cp

# --- 配置 ---
_CLAUDE_BIN = os.environ.get("SERENITY_CLAUDE_BIN") or "/root/.local/bin/claude"
_CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("OPINION_CLAUDE_TIMEOUT", "480"))
_TASK_TYPE = "opinion_analyze"
_MAX_POSTS = 40
_FRESH_DAYS = 2  # 观点时效性短,缓存 2 天内视为新鲜

_BASE_DIR = pathlib.Path(__file__).resolve().parent
_PROJECT_ROOT = _BASE_DIR.parent.parent.parent  # cl_app -> chanlun_chart -> web -> chanlun-pro
_OPINIONS_JSON_PATH = _PROJECT_ROOT / "serenity-aleabitoreddit-main" / "stock_opinions.json"
_LOG_DIR = _BASE_DIR.parent / "logs" / "serenity_opinions"
_NEUTRAL_CWD = pathlib.Path(tempfile.gettempdir()) / "serenity_opinions_cwd"

# 任务上限/过期(与 serenity_aistocks 的量级一致)
_MAX_TASKS = 64
_TASK_TTL_SECONDS = 30 * 60

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opinion-analyze")
_TASKS: dict[str, dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()


# --- 任务表 ---
def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _set_task(task_id: str, **updates: Any) -> dict[str, Any]:
    with _TASKS_LOCK:
        task = _TASKS.get(task_id, {})
        task.update(updates)
        task["updated_at"] = _now_iso()
        _TASKS[task_id] = task
        # 简单裁剪:超量则丢弃最旧
        if len(_TASKS) > _MAX_TASKS:
            oldest = sorted(_TASKS.items(), key=lambda kv: kv[1].get("updated_at", ""))
            for tid, _ in oldest[: len(_TASKS) - _MAX_TASKS]:
                _TASKS.pop(tid, None)
        return dict(task)


def _get_task(task_id: str) -> dict[str, Any] | None:
    with _TASKS_LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


# --- 存储层(镜像 aistocks_research.json 的约定) ---
@lru_cache(maxsize=1)
def _load_opinions() -> dict[str, Any]:
    if not _OPINIONS_JSON_PATH.exists():
        return {}
    try:
        data = json.loads(_OPINIONS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_stock_opinion(name: str) -> dict[str, Any] | None:
    if not name:
        return None
    return _load_opinions().get(name)


def _write_opinion(name: str, entry: dict[str, Any]) -> None:
    data: dict[str, Any] = {}
    if _OPINIONS_JSON_PATH.exists():
        try:
            loaded = json.loads(_OPINIONS_JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    data.setdefault(
        "_meta",
        {
            "schema_version": 1,
            "keyed_by": "stock_name",
            "generator": "serenity_opinions",
            "source": "东方财富股吧",
            "disclaimer": "散户社区观点摘要,非投资建议。",
        },
    )
    data[name] = entry
    _OPINIONS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(_OPINIONS_JSON_PATH) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, str(_OPINIONS_JSON_PATH))
    _load_opinions.cache_clear()


def _is_fresh(entry: dict[str, Any]) -> bool:
    ts = entry.get("generated_at")
    if not ts:
        return False
    try:
        gen = datetime.datetime.fromisoformat(ts)
    except Exception:
        return False
    return (datetime.datetime.now() - gen).days < _FRESH_DAYS


# --- 数据采集:东财股吧 ---
def _fetch_guba_posts(code: str, name: str) -> list[dict[str, Any]]:
    provider = _cp.EastmoneyGubaProvider()
    try:
        posts = provider.fetch_posts(stock_code=code, stock_name=name, limit=_MAX_POSTS)
    except TypeError:
        posts = provider.fetch_posts(code, name)
    return [p for p in (posts or []) if isinstance(p, dict) and p.get("content")]


# --- Claude 调用 ---
def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _build_prompt(name: str, code: str, posts: list[dict[str, Any]]) -> str:
    lines = []
    for i, p in enumerate(posts, 1):
        content = str(p.get("content") or "").replace("\n", " ").strip()
        if not content:
            continue
        likes = p.get("like_count") or 0
        replies = p.get("reply_count") or 0
        lines.append(f"{i}. [{likes}赞/{replies}评] {content[:200]}")
    corpus = "\n".join(lines)
    schema = (
        '{"overall_mood":"偏多|中性|偏空","sentiment":{"bullish_pct":0,"bearish_pct":0,'
        '"neutral_pct":0},"bull_points":["..."],"bear_points":["..."],'
        '"hot_topics":[{"title":"..","stance":"多|空|中","summary":".."}],'
        '"risks":["..."],"consensus":"..","disagreements":"..",'
        '"notable_quotes":[{"text":"原文摘录","stance":"多|空|中"}],'
        '"confidence":"low|medium|high"}'
    )
    return (
        f"你是资深 A 股分析师。下面是股票「{name}」({code})东方财富股吧的 {len(lines)} 条散户评论。\n"
        f"请只依据这些评论,归纳当前散户舆情,做分类总结。注意区分情绪噪声与有信息量的观点,"
        f"情绪占比需大致自洽(相加约 100)。\n\n"
        f"【评论语料】\n{corpus}\n\n"
        f"【输出要求】只输出一个 JSON 对象,不要任何解释文字或代码块围栏,结构严格如下:\n{schema}"
    )


def _run_claude(prompt: str, log_path: pathlib.Path) -> str:
    _NEUTRAL_CWD.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    bin_dir = os.path.dirname(_CLAUDE_BIN)
    if bin_dir:
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    proc = subprocess.Popen(
        [_CLAUDE_BIN, "-p", prompt, "--output-format", "stream-json", "--verbose"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(_NEUTRAL_CWD),
        env=env,
    )
    final_text = ""
    watchdog = threading.Timer(_CLAUDE_TIMEOUT_SECONDS, proc.kill)
    watchdog.start()
    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            for line in proc.stdout:  # type: ignore[union-attr]
                lf.write(line)
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    evt = json.loads(stripped)
                except Exception:
                    continue
                if evt.get("type") == "result":
                    final_text = evt.get("result", "") or final_text
    finally:
        watchdog.cancel()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    if not final_text:
        raise RuntimeError("claude 无输出(超时或异常)")
    return final_text


# --- 任务主体 ---
def _run_opinion_task(task_id: str, name: str, code: str, force: bool) -> None:
    try:
        if not force:
            existing = get_stock_opinion(name)
            if existing and _is_fresh(existing):
                _set_task(
                    task_id,
                    state="done",
                    progress=100,
                    message="已有较新报告(缓存)",
                    finished_at=_now_iso(),
                    result={"name": name, "cached": True, "report": existing},
                )
                return

        _set_task(task_id, state="running", progress=15, message="抓取东财股吧评论…")
        posts = _fetch_guba_posts(code, name)
        if not posts:
            _set_task(
                task_id,
                state="failed",
                progress=100,
                message="未抓到股吧评论(可能被东财风控或代码有误)",
                finished_at=_now_iso(),
                error="guba_empty",
            )
            return

        _set_task(
            task_id,
            state="running",
            progress=45,
            message=f"已抓 {len(posts)} 条评论,Claude 分类总结中…",
        )
        prompt = _build_prompt(name, code, posts)
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{(code or name)}_{task_id[:8]}.log"
        text = _run_claude(prompt, log_path)
        report = _extract_json_object(text)
        if not report:
            _set_task(
                task_id,
                state="failed",
                progress=100,
                message="Claude 输出解析失败",
                finished_at=_now_iso(),
                error="no_json",
            )
            return

        report.setdefault("name", name)
        report.setdefault("code", code)
        report["source"] = "东方财富股吧"
        report["post_count"] = len(posts)
        report["generated_at"] = _now_iso()
        _write_opinion(name, report)
        _set_task(
            task_id,
            state="done",
            progress=100,
            message="分析完成",
            finished_at=_now_iso(),
            result={"name": name, "cached": False, "report": report},
        )
    except Exception as e:  # noqa: BLE001
        _set_task(
            task_id,
            state="failed",
            progress=100,
            message=f"分析失败:{e}",
            finished_at=_now_iso(),
            error=str(e),
        )


# --- 路由注册 ---
def register_serenity_opinions_routes(app) -> None:
    @app.route("/serenity/opinions/analyze", methods=["POST"])
    @login_required
    def serenity_opinions_analyze():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        code = (data.get("code") or "").strip()
        force = bool(data.get("force"))
        if not name:
            return jsonify({"ok": False, "message": "股票名称不能为空"}), 400
        task_id = uuid.uuid4().hex
        _set_task(
            task_id,
            task_id=task_id,
            task_type=_TASK_TYPE,
            stock_name=name,
            stock_code=code,
            state="pending",
            progress=0,
            message="分析任务已启动",
        )
        _EXECUTOR.submit(_run_opinion_task, task_id, name, code, force)
        return jsonify(
            {"ok": True, "task_id": task_id, "task_type": _TASK_TYPE, "message": "分析任务已启动"}
        )

    @app.route("/serenity/opinions/task/<task_id>", methods=["GET"])
    @login_required
    def serenity_opinions_task(task_id: str):
        task = _get_task(task_id)
        if not task or task.get("task_type") != _TASK_TYPE:
            return jsonify({"ok": False, "message": "任务不存在或已过期"}), 404
        return jsonify({"ok": True, **task})

    @app.route("/serenity/opinions/<name>", methods=["GET"])
    @login_required
    def serenity_opinions_get(name: str):
        return jsonify({"ok": True, "report": get_stock_opinion(name)})
