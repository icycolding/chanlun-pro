#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from dateutil import tz
# from ib_insync import IB  # type: ignore


@dataclass
class NewsItem:
    time: dt.datetime
    provider: str
    headline: str
    article_id: str


def _now_utc() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def list_news_providers(ib: IB) -> List[Tuple[str, str]]:
    """
    返回 [(code, name), ...]
    """
    providers = ib.reqNewsProviders()
    return [(p.code, p.name) for p in providers]


def fetch_historical_news(
    ib: IB,
    con_id: int,
    provider_codes: Sequence[str],
    lookback_hours: int = 24,
    max_items: int = 15,
) -> List[NewsItem]:
    """
    从 IBKR 拉取某个 conId 的新闻标题列表（通常需要订阅新闻源）。

    注意：
    - IB 的 providerCodes 参数是用逗号分隔的字符串
    - 这里为了稳健性只抓 headlines（不抓全文）
    """
    if not provider_codes:
        return []

    end = _now_utc()
    start = end - dt.timedelta(hours=lookback_hours)

    # IB API 的时间格式支持 "YYYYMMDD HH:MM:SS"（UTC）
    start_str = start.strftime("%Y%m%d %H:%M:%S")
    end_str = end.strftime("%Y%m%d %H:%M:%S")
    provider_str = ",".join(provider_codes)

    try:
        res = ib.reqHistoricalNews(
            conId=con_id,
            providerCodes=provider_str,
            startDateTime=start_str,
            endDateTime=end_str,
            totalResults=max_items,
            historicalNewsOptions=[],
        )
    except Exception:
        return []

    items: List[NewsItem] = []
    for n in res or []:
        # n.time: str like "20260101 12:34:56"
        try:
            t = dt.datetime.strptime(n.time, "%Y%m%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        except Exception:
            t = _now_utc()

        items.append(
            NewsItem(
                time=t,
                provider=str(getattr(n, "providerCode", "")),
                headline=str(getattr(n, "headline", "")),
                article_id=str(getattr(n, "articleId", "")),
            )
        )

    # 去重（同标题多源重复的情况）
    dedup: Dict[str, NewsItem] = {}
    for it in items:
        key = it.headline.strip().lower()
        if not key:
            continue
        if key not in dedup:
            dedup[key] = it
    out = list(dedup.values())
    out.sort(key=lambda x: x.time, reverse=True)
    return out[:max_items]


def classify_relevance(headline: str) -> Dict[str, int]:
    """
    关键词规则：返回 {symbol: score_delta}，用于风险/情绪评分。
    说明：这是一个“可解释的启发式”版本，后续你也可以替换成更复杂的 NLP。
    """
    h = headline.lower()
    score: Dict[str, int] = {}

    def add(sym: str, v: int) -> None:
        score[sym] = score.get(sym, 0) + v

    # USD 宏观（影响广）
    usd_kw = ["fed", "fomc", "powell", "cpi", "inflation", "nfp", "payroll", "ppi", "rates", "yield", "treasury"]
    if any(k in h for k in usd_kw):
        for sym in ["EURUSD", "USDJPY", "GBPUSD", "XAUUSD", "USDCNH"]:
            add(sym, 8)

    # 欧元区/ECB
    if any(k in h for k in ["ecb", "eurozone", "euro area", "euro", "lagarde", "germany"]):
        add("EURUSD", 10)

    # 日本/BOJ
    if any(k in h for k in ["boj", "japan", "yen", "kishida", "ueno"]):
        add("USDJPY", 10)

    # 英国/BOE
    if any(k in h for k in ["boe", "bank of england", "uk", "britain", "pound", "sterling"]):
        add("GBPUSD", 10)

    # 黄金
    if any(k in h for k in ["gold", "xau", "bullion", "safe haven", "geopolitical", "war"]):
        add("XAUUSD", 12)

    # 中国/CNH
    if any(k in h for k in ["china", "cnh", "yuan", "pbo", "pboe", "beijing", "tariff", "export"]):
        add("USDCNH", 12)

    # 风险事件放大器
    shock_kw = ["surge", "plunge", "crash", "default", "sanction", "emergency", "unexpected", "shock", "panic"]
    if any(k in h for k in shock_kw):
        for sym in list(score.keys()) or ["EURUSD", "USDJPY", "GBPUSD", "XAUUSD", "USDCNH"]:
            add(sym, 6)

    return score


def aggregate_risk_scores(news: Dict[str, List[NewsItem]]) -> Dict[str, int]:
    """
    输出每个品种 0-100 的风险分数（越高表示“新闻驱动风险/波动上升”的可能越大）。
    """
    raw: Dict[str, int] = {k: 0 for k in news.keys()}
    for sym, items in news.items():
        for it in items:
            contrib = classify_relevance(it.headline).get(sym, 0)
            raw[sym] = raw.get(sym, 0) + contrib

    # 归一化：用 soft cap，避免极端标题刷分
    scores: Dict[str, int] = {}
    for sym, v in raw.items():
        # 经验参数：60 分附近开始饱和
        s = int(round(100 * (1 - pow(2.71828, -v / 60.0))))
        scores[sym] = max(0, min(100, s))
    return scores


def format_news_md(
    news_by_symbol: Dict[str, List[NewsItem]],
    risk_scores: Optional[Dict[str, int]] = None,
    tz_name: str = "Asia/Shanghai",
    max_lines_per_symbol: int = 8,
) -> str:
    tz_local = tz.gettz(tz_name)
    lines: List[str] = []
    lines.append("## 新闻与风险")
    lines.append("")

    if risk_scores:
        lines.append("**新闻驱动风险评分（0-100）**")
        lines.append("")
        lines.append("| 品种 | 分数 |")
        lines.append("|---|---:|")
        for sym, s in sorted(risk_scores.items(), key=lambda x: x[0]):
            lines.append(f"| {sym} | {s} |")
        lines.append("")

    # 宏观要点：取所有品种新闻合并去重，按时间倒序取前 10
    all_items: Dict[str, NewsItem] = {}
    for sym, items in news_by_symbol.items():
        for it in items:
            k = it.headline.strip().lower()
            if k and k not in all_items:
                all_items[k] = it
    top = sorted(all_items.values(), key=lambda x: x.time, reverse=True)[:10]

    lines.append("### 今日宏观要点（标题级）")
    lines.append("")
    if not top:
        lines.append("-（未拉取到新闻：可能是未订阅新闻源、provider 不可用或 conId 无对应新闻）")
    else:
        for it in top:
            t = it.time.astimezone(tz_local).strftime("%m-%d %H:%M")
            lines.append(f"- {t} [{it.provider}] {it.headline}")
    lines.append("")

    lines.append("### 按品种分组")
    lines.append("")
    for sym, items in news_by_symbol.items():
        lines.append(f"#### {sym}")
        if not items:
            lines.append("-（无）")
            lines.append("")
            continue
        for it in items[:max_lines_per_symbol]:
            t = it.time.astimezone(tz_local).strftime("%m-%d %H:%M")
            lines.append(f"- {t} [{it.provider}] {it.headline}")
        lines.append("")

    return "\n".join(lines)

