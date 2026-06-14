#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

# 说明：
# - IBKR 连接需要本机已启动 TWS/IB Gateway，并开启 API Socket
# - 本脚本仅做“投研/信号/回测摘要/报告”，不下单
from ib_insync import IB, Forex, util  # type: ignore

# 确保无论从哪里调用，都能导入同目录模块
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from news import aggregate_risk_scores, fetch_historical_news, format_news_md, list_news_providers  # noqa: E402
from jin10_web import fetch_flash_from_homepage  # noqa: E402


# ----------------------------
# 工具函数
# ----------------------------


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def pct_change(s: pd.Series) -> pd.Series:
    return s.pct_change().replace([np.inf, -np.inf], np.nan)


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def max_drawdown(equity: pd.Series) -> float:
    if equity.dropna().empty:
        return float("nan")
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def annualized_sharpe(returns: pd.Series, annualization: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 3:
        return float("nan")
    mu = r.mean() * annualization
    vol = r.std(ddof=0) * np.sqrt(annualization)
    return float(mu / vol) if vol > 0 else float("nan")


# ----------------------------
# 研究逻辑
# ----------------------------


@dataclass
class SymbolSpec:
    name: str
    type: str  # 目前仅支持 FX
    pair: str  # 例如 EURUSD / USDCNH


def build_contract(spec: SymbolSpec):
    if spec.type.upper() == "FX":
        return Forex(spec.pair)
    raise ValueError(f"不支持的合约类型: {spec.type}")


def enrich_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int, rsi_period: int, atr_period: int) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = out["close"].ewm(span=ema_fast, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=ema_slow, adjust=False).mean()
    out["rsi"] = compute_rsi(out["close"], period=rsi_period)
    out["atr"] = compute_atr(out, period=atr_period)
    return out


def regime_signal(last_row: pd.Series) -> Tuple[str, str]:
    """
    返回 (方向结论, 简短理由)：
    - 偏多：ema_fast > ema_slow 且 RSI 未明显超买
    - 偏空：ema_fast < ema_slow 且 RSI 未明显超卖
    - 观望：其余情况
    """
    ema_fast = float(last_row.get("ema_fast", np.nan))
    ema_slow = float(last_row.get("ema_slow", np.nan))
    rsi = float(last_row.get("rsi", np.nan))

    if np.isnan(ema_fast) or np.isnan(ema_slow) or np.isnan(rsi):
        return "观望", "指标不足（数据太短或缺失）"

    if ema_fast > ema_slow and rsi < 70:
        return "偏多", f"快线EMA在慢线EMA上方，RSI={rsi:.1f} 未明显超买"
    if ema_fast < ema_slow and rsi > 30:
        return "偏空", f"快线在慢线下方，RSI={rsi:.1f} 未明显超卖"
    return "观望", f"趋势/动能不一致（RSI={rsi:.1f}）"


def key_levels(df: pd.DataFrame, lookback: int = 20) -> Dict[str, float]:
    window = df.dropna().tail(lookback)
    if window.empty:
        return {}
    return {
        "近N高点": float(window["high"].max()),
        "近N低点": float(window["low"].min()),
    }


def pivot_points(prev: pd.Series) -> Dict[str, float]:
    """
    经典枢轴点（上一根K线的H/L/C）。
    """
    h, l, c = float(prev["high"]), float(prev["low"]), float(prev["close"])
    p = (h + l + c) / 3.0
    r1 = 2 * p - l
    s1 = 2 * p - h
    r2 = p + (h - l)
    s2 = p - (h - l)
    return {"P": p, "R1": r1, "S1": s1, "R2": r2, "S2": s2}


def simple_trend_backtest(df: pd.DataFrame, annualization: int = 252) -> Dict[str, Any]:
    """
    极简趋势回测（仅用于投研摘要，不是生产级策略）：
    pos_t = sign(ema_fast - ema_slow)
    strat_ret_{t+1} = pos_t * ret_{t+1}
    """
    d = df.dropna().copy()
    if len(d) < 60:
        return {"enabled": True, "note": "数据不足，跳过"}

    d["ret"] = pct_change(d["close"])
    d["pos"] = np.sign(d["ema_fast"] - d["ema_slow"]).replace(0, np.nan).ffill().fillna(0.0)
    d["strat_ret"] = d["pos"].shift(1) * d["ret"]
    d["equity"] = (1.0 + d["strat_ret"].fillna(0.0)).cumprod()

    wins = (d["strat_ret"] > 0).sum()
    losses = (d["strat_ret"] < 0).sum()
    total = int(wins + losses)
    win_rate = float(wins / total) if total > 0 else float("nan")

    return {
        "enabled": True,
        "trades": total,
        "win_rate": win_rate,
        "avg_daily_ret": float(d["strat_ret"].mean()),
        "sharpe": annualized_sharpe(d["strat_ret"], annualization=annualization),
        "max_drawdown": max_drawdown(d["equity"]),
        "last_pos": float(d["pos"].iloc[-1]),
    }


def plot_chart(df: pd.DataFrame, title: str, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")  # 服务器/无桌面环境也可绘图
    import matplotlib.pyplot as plt  # 延迟导入，避免无图环境报错影响主流程

    d = df.dropna().tail(260).copy()
    if d.empty:
        return

    fig = plt.figure(figsize=(10, 6))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)

    ax1.plot(d["date"], d["close"], label="Close", linewidth=1.2)
    if "ema_fast" in d:
        ax1.plot(d["date"], d["ema_fast"], label="EMA_fast", linewidth=1.0)
    if "ema_slow" in d:
        ax1.plot(d["date"], d["ema_slow"], label="EMA_slow", linewidth=1.0)
    ax1.set_title(title)
    ax1.grid(True, alpha=0.2)
    ax1.legend(loc="upper left")

    ax2.plot(d["date"], d["rsi"], label="RSI", linewidth=1.0, color="#cc5500")
    ax2.axhline(70, color="red", linestyle="--", linewidth=0.8, alpha=0.6)
    ax2.axhline(30, color="green", linestyle="--", linewidth=0.8, alpha=0.6)
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.2)
    ax2.legend(loc="upper left")

    for label in ax1.get_xticklabels():
        label.set_visible(False)
    fig.autofmt_xdate()

    ensure_dir(out_png.parent)
    fig.savefig(out_png, dpi=160, bbox_inches="tight")
    plt.close(fig)


# ----------------------------
# 报告生成
# ----------------------------


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def render_symbol_section(
    spec: SymbolSpec,
    df: pd.DataFrame,
    lookback: int,
    bt_cfg: Dict[str, Any],
    chart_rel_path: Optional[str],
) -> str:
    last = df.dropna().iloc[-1]
    prev = df.dropna().iloc[-2] if len(df.dropna()) >= 2 else None

    bias, reason = regime_signal(last)
    levels = key_levels(df, lookback=lookback)
    pivots = pivot_points(prev) if prev is not None else {}

    lines: List[str] = []
    lines.append(f"## {md_escape(spec.name)}")
    lines.append("")
    lines.append(f"- 结论：**{bias}**")
    lines.append(f"- 理由：{reason}")
    lines.append(f"- 最新收盘：{float(last['close']):.5f}")
    lines.append(f"- ATR({int(bt_cfg.get('atr_period', 14))})：{float(last.get('atr', np.nan)):.5f}")
    lines.append("")

    if chart_rel_path:
        lines.append(f"![{md_escape(spec.name)}]({chart_rel_path})")
        lines.append("")

    if levels:
        lines.append("**关键位（近N高低点）**")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|---|---:|")
        for k, v in levels.items():
            lines.append(f"| {md_escape(k)} | {v:.5f} |")
        lines.append("")

    if pivots:
        lines.append("**枢轴点（上一根K线）**")
        lines.append("")
        lines.append("| P | R1 | S1 | R2 | S2 |")
        lines.append("|---:|---:|---:|---:|---:|")
        lines.append(
            f"| {pivots['P']:.5f} | {pivots['R1']:.5f} | {pivots['S1']:.5f} | {pivots['R2']:.5f} | {pivots['S2']:.5f} |"
        )
        lines.append("")

    if bt_cfg.get("enabled", True):
        bt = simple_trend_backtest(df, annualization=int(bt_cfg.get("annualization", 252)))
        lines.append("**回测摘要（极简趋势，仅供参考）**")
        lines.append("")
        if bt.get("note"):
            lines.append(f"- {bt['note']}")
        else:
            lines.append(
                f"- 交易次数：{bt['trades']}，胜率：{bt['win_rate']*100:.1f}%"
            )
            lines.append(
                f"- 平均日收益：{bt['avg_daily_ret']*100:.3f}%；Sharpe（年化）：{bt['sharpe']:.2f}；最大回撤：{bt['max_drawdown']*100:.1f}%"
            )
        lines.append("")

    # 简易交易计划（以 ATR 作为止损尺度）
    atr = float(last.get("atr", np.nan))
    if not np.isnan(atr):
        sl = 1.5 * atr
        tp = 2.0 * atr
        lines.append("**交易计划（示例，按 ATR 尺度）**")
        lines.append("")
        lines.append(f"- 入场：等待价格触发关键位/枢轴位的确认（你可自行替换成更明确规则）")
        lines.append(f"- 止损：约 1.5×ATR ≈ {sl:.5f}")
        lines.append(f"- 止盈：约 2.0×ATR ≈ {tp:.5f}")
        lines.append("")

    return "\n".join(lines)


def try_write_pdf(md_path: Path) -> Optional[Path]:
    pdf_path = md_path.with_suffix(".pdf")
    try:
        subprocess.run(
            ["pandoc", str(md_path), "-o", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return pdf_path
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError:
        return None


# ----------------------------
# 主流程
# ----------------------------


def fetch_history(ib: IB, contract, duration: str, bar_size: str, what_to_show: str, use_rth: bool) -> pd.DataFrame:
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
        formatDate=1,
        keepUpToDate=False,
    )
    df = util.df(bars)
    if df.empty:
        return df

    # 统一字段名
    df = df.rename(columns={"date": "date"})
    # 确保 date 是 datetime
    df["date"] = pd.to_datetime(df["date"])
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="IBKR 外汇/黄金自动投研：拉数据→指标/回测→生成Markdown/可选PDF")
    parser.add_argument("--config", required=True, help="配置文件路径（yaml）")
    parser.add_argument("--as-of", default=None, help="报告日期（YYYY-MM-DD），用于目录命名")
    parser.add_argument("--pdf", action="store_true", help="尝试生成PDF（需要pandoc）")
    args = parser.parse_args()

    cfg_path = Path(args.config).expanduser().resolve()
    cfg = load_yaml(cfg_path)

    as_of = dt.date.today()
    if args.as_of:
        as_of = dt.date.fromisoformat(args.as_of)

    ib_cfg = cfg["ibkr"]
    data_cfg = cfg["data"]
    universe_cfg = cfg["universe"]
    research_cfg = cfg["research"]
    backtest_cfg = cfg.get("backtest", {"enabled": True, "annualization": 252})
    out_cfg = cfg.get("output", {"reports_dir": "reports", "write_pdf": False})
    news_cfg = cfg.get("news", {"enabled": False})

    reports_root = Path(out_cfg.get("reports_dir", "reports"))
    report_dir = reports_root / as_of.isoformat()
    assets_dir = report_dir / "assets"
    ensure_dir(assets_dir)

    symbols = [
        SymbolSpec(name=s["name"], type=s["type"], pair=s["pair"])
        for s in universe_cfg.get("symbols", [])
    ]
    if not symbols:
        raise SystemExit("配置中 universe.symbols 为空")

    ib = IB()
    ib.connect(
        host=str(ib_cfg.get("host", "127.0.0.1")),
        port=int(ib_cfg.get("port", 7497)),
        clientId=int(ib_cfg.get("client_id", 17)),
        timeout=float(ib_cfg.get("connect_timeout_sec", 10)),
    )

    sections: List[str] = []
    summary_lines: List[str] = []
    news_by_symbol: Dict[str, list] = {}
    source = str(news_cfg.get("source", "ibkr")).lower()

    # 新闻 providers（只探测一次）
    providers: List[str] = []
    if bool(news_cfg.get("enabled", False)) and source == "ibkr":
        manual = news_cfg.get("providers", [])
        if isinstance(manual, list) and manual:
            providers = [str(x) for x in manual]
        else:
            try:
                providers = [code for code, _name in list_news_providers(ib)]
            except Exception:
                providers = []

    for spec in symbols:
        contract = build_contract(spec)
        ib.qualifyContracts(contract)

        raw = fetch_history(
            ib,
            contract,
            duration=str(data_cfg.get("duration", "5 Y")),
            bar_size=str(data_cfg.get("bar_size", "1 day")),
            what_to_show=str(data_cfg.get("what_to_show", "MIDPOINT")),
            use_rth=bool(data_cfg.get("use_rth", False)),
        )
        if raw.empty:
            summary_lines.append(f"- {spec.name}: 拉取失败/无数据")
            continue

        # 新闻（IBKR：按品种 conId 拉取标题）
        if bool(news_cfg.get("enabled", False)) and source == "ibkr":
            try:
                con_id = int(contract.conId)  # qualify 后应有 conId
            except Exception:
                con_id = 0
            if con_id > 0 and providers:
                items = fetch_historical_news(
                    ib=ib,
                    con_id=con_id,
                    provider_codes=providers,
                    lookback_hours=int(news_cfg.get("lookback_hours", 24)),
                    max_items=int(news_cfg.get("max_items_per_symbol", 15)),
                )
                news_by_symbol[spec.name] = items
            else:
                news_by_symbol[spec.name] = []

        df = enrich_indicators(
            raw,
            ema_fast=int(research_cfg.get("ema_fast", 20)),
            ema_slow=int(research_cfg.get("ema_slow", 50)),
            rsi_period=int(research_cfg.get("rsi_period", 14)),
            atr_period=int(research_cfg.get("atr_period", 14)),
        )

        # 图表
        chart_png = assets_dir / f"{spec.name}.png"
        plot_chart(df, title=f"{spec.name} ({data_cfg.get('bar_size', '1 day')})", out_png=chart_png)
        chart_rel = f"assets/{chart_png.name}" if chart_png.exists() else None

        # 小结
        last = df.dropna().iloc[-1]
        bias, _ = regime_signal(last)
        summary_lines.append(f"- {spec.name}: **{bias}**（Close={float(last['close']):.5f}）")

        # 章节
        sections.append(
            render_symbol_section(
                spec=spec,
                df=df,
                lookback=int(research_cfg.get("key_level_lookback", 20)),
                bt_cfg={**backtest_cfg, "atr_period": int(research_cfg.get("atr_period", 14))},
                chart_rel_path=chart_rel,
            )
        )

    ib.disconnect()

    # 新闻（jin10_web：抓取首页快讯，再按关键词映射到品种）
    if bool(news_cfg.get("enabled", False)) and source == "jin10_web":
        try:
            jin_cfg = cfg.get("jin10_web", {})
            url = str(jin_cfg.get("url", "https://www.jin10.com/"))
            all_items = fetch_flash_from_homepage(url=url)
        except Exception:
            all_items = []

        # 用 news.classify_relevance 的关键词规则做“按品种分组”
        from news import classify_relevance  # 延迟导入避免循环依赖

        max_items = int(news_cfg.get("max_items_per_symbol", 15))
        lookback_hours = int(news_cfg.get("lookback_hours", 24))
        cutoff = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))) - dt.timedelta(hours=lookback_hours)

        for spec in symbols:
            sym = spec.name
            picked = []
            for it in all_items:
                if it.time < cutoff:
                    continue
                if classify_relevance(it.headline).get(sym, 0) > 0:
                    picked.append(it)
            news_by_symbol[sym] = picked[:max_items]

    # 新闻章节（放在总览之后、各品种分析之前）
    news_section = ""
    if bool(news_cfg.get("enabled", False)) and news_by_symbol:
        try:
            risk_scores = aggregate_risk_scores(news_by_symbol)
        except Exception:
            risk_scores = None
        news_section = format_news_md(
            news_by_symbol=news_by_symbol,
            risk_scores=risk_scores,
            tz_name=str(news_cfg.get("timezone", "Asia/Shanghai")),
        )

    header = [
        f"# IBKR 自动投研日报（{as_of.isoformat()}）",
        "",
        "## 总览",
        "",
        *summary_lines,
        "",
        "---",
        "",
        news_section,
        "",
        "---",
        "",
    ]

    md = "\n".join(header + sections) + "\n"
    md_path = report_dir / "report.md"
    md_path.write_text(md, encoding="utf-8")

    write_pdf = bool(out_cfg.get("write_pdf", False)) or bool(args.pdf)
    if write_pdf:
        try_write_pdf(md_path)

    print(f"OK: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
