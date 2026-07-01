#!/usr/bin/env python3
"""Quality gate for serenity-aleabitoreddit-main/aistocks_research.json.

按每条 entry 自带的 `schema_version` 分级校验：
- v1（无 schema_version 或 <2）：宽松规则（fit_status/代码/≥2 证据/无占位）。
- v2（schema_version>=2）：强校验全部结构化视图组 + 证据分层 + 置信 + 情景 + 估值判定。

Exit code 0 = pass, 1 = 有条目不合格。

Usage:
    python scripts/validate_serenity_research.py [path/to/aistocks_research.json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[1]
    / "serenity-aleabitoreddit-main"
    / "aistocks_research.json"
)
_PLACEHOLDERS_V1 = ("待补充", "待研究", "待行情源", "TODO", "N/A", "暂无")
_PLACEHOLDERS_V2 = _PLACEHOLDERS_V1 + ("待验证", "强|中|弱", "低估|合理|高估", "高|中|低")
_VALID_FIT = {"fit", "partial_fit", "not_fit", "watch"}
_VALID_LABEL = {"强", "中", "弱"}
_VALID_VERDICT = {"低估", "合理", "高估"}
_VALID_CONF = {"高", "中", "低"}
_CODE_RE = re.compile(r"^(sh|sz|bj|hk)?\d{5,6}$", re.IGNORECASE)


def _txt(value) -> str:
    return str(value).strip() if value is not None else ""


def _entry_version(entry: dict) -> int:
    try:
        return int(entry.get("schema_version", 1))
    except (TypeError, ValueError):
        return 1


def _check_common(entry: dict) -> list[str]:
    errors: list[str] = []
    if entry.get("fit_status") not in _VALID_FIT:
        errors.append(f"fit_status 非法: {entry.get('fit_status')!r}")
    if not _txt(entry.get("fit_reason_short")):
        errors.append("缺 fit_reason_short")
    code = _txt(entry.get("code_verified")) or _txt(entry.get("code_in_xlsx"))
    if not code or not _CODE_RE.match(code):
        errors.append(f"缺合法已校验代码 code_verified (got {code!r})")
    return errors


def _check_evidence(entry: dict, *, min_count: int, require_tier: bool) -> list[str]:
    errors: list[str] = []
    sources = entry.get("evidence_sources") or []
    http_sources = [s for s in sources if str((s or {}).get("url", "")).startswith("http")]
    if len(http_sources) < min_count:
        errors.append(f"证据来源不足 {min_count} 条 http (got {len(http_sources)})")
    if require_tier:
        for idx, s in enumerate(http_sources):
            tier = (s or {}).get("tier")
            if tier not in (1, 2, 3, "1", "2", "3"):
                errors.append(f"证据[{idx}] 缺合法 tier(1/2/3) (got {tier!r})")
    return errors


def _need(entry: dict, group: str, field: str, errors: list[str]) -> None:
    val = _txt((entry.get(group) or {}).get(field))
    if not val:
        errors.append(f"{group}.{field} 为空")


_CERT_RESULTS = {"yes", "partial", "no", "na"}
_CERT_MAX_NA = 6  # na 超过此数视为滥用逃避判断


def _check_certification(entry: dict) -> list[str]:
    errors: list[str] = []
    cert = entry.get("serenity_certification")
    if not isinstance(cert, dict) or not cert:
        return ["缺 serenity_certification（Serenity 方法论认证）"]
    if _txt(cert.get("verdict")) not in _VALID_FIT:
        errors.append(f"serenity_certification.verdict 非法: {cert.get('verdict')!r}")
    if not _txt(cert.get("score")):
        errors.append("serenity_certification.score 为空")
    if not _txt(cert.get("bottleneck_map")):
        errors.append("serenity_certification.bottleneck_map 为空")
    checklist = cert.get("checklist") or []
    if len(checklist) != 14:
        errors.append(f"serenity_certification.checklist 须为 14 条 (got {len(checklist)})")
    na_count = 0
    for item in checklist:
        item = item or {}
        rid = item.get("id")
        result = _txt(item.get("result"))
        if result not in _CERT_RESULTS:
            errors.append(f"认证第 {rid} 条 result 非法(yes/partial/no/na): {result!r}")
        if result == "na":
            na_count += 1
        if not _txt(item.get("evidence")):
            errors.append(f"认证第 {rid} 条缺 evidence")
    if na_count > _CERT_MAX_NA:
        errors.append(f"认证 na 过多({na_count}>{_CERT_MAX_NA})，疑似逃避判断")
    # fit_status 须与认证 verdict 一致
    if _txt(entry.get("fit_status")) != _txt(cert.get("verdict")):
        errors.append(
            f"fit_status({entry.get('fit_status')!r}) 与认证 verdict({cert.get('verdict')!r}) 不一致"
        )
    return errors


def _check_v2(entry: dict) -> list[str]:
    errors: list[str] = []

    # 详情页核心视图组
    _need(entry, "selection_reason", "summary", errors)
    for grp in ("scarcity_view", "capacity_view", "pricing_view"):
        label = _txt((entry.get(grp) or {}).get("label"))
        detail = _txt((entry.get(grp) or {}).get("detail"))
        if not any(x in label for x in _VALID_LABEL):
            errors.append(f"{grp}.label 须含 强/中/弱 (got {label!r})")
        if not detail:
            errors.append(f"{grp}.detail 为空")
    _need(entry, "segment_market_view", "market_size_text", errors)
    _need(entry, "sector_context_view", "sector_name", errors)
    _need(entry, "industry_chain_view", "choke_point_note", errors)
    _need(entry, "market_cap_research", "current_text", errors)

    # 新增 8 维
    fin = entry.get("financials_view") or {}
    if not (fin.get("revenue_segments") or _txt(fin.get("revenue_trend_3y"))):
        errors.append("financials_view 缺营收分部/3Y 趋势")
    moat_dur = _txt((entry.get("moat_view") or {}).get("durability"))
    if not any(x in moat_dur for x in _VALID_LABEL):
        errors.append(f"moat_view.durability 须含 强/中/弱 (got {moat_dur!r})")
    verdict = _txt((entry.get("valuation_view") or {}).get("verdict"))
    if not any(x in verdict for x in _VALID_VERDICT):
        errors.append(f"valuation_view.verdict 须含 低估/合理/高估 (got {verdict!r})")
    if not (entry.get("catalysts_view") or []):
        errors.append("catalysts_view 为空（需 12 月催化）")
    if not (entry.get("risks_view") or []):
        errors.append("risks_view 为空（需风险 Top）")
    _need(entry, "thesis_view", "variant_perception", errors)
    scen = entry.get("scenario_view") or {}
    for leg in ("bull", "base", "bear"):
        if not _txt((scen.get(leg) or {}).get("drivers")):
            errors.append(f"scenario_view.{leg}.drivers 为空")
    conf = _txt((entry.get("confidence") or {}).get("overall"))
    if not any(x in conf for x in _VALID_CONF):
        errors.append(f"confidence.overall 须含 高/中/低 (got {conf!r})")

    if _entry_version(entry) >= 3:  # v3 起强制 Serenity 方法论认证
        errors.extend(_check_certification(entry))
    errors.extend(_check_common(entry))
    errors.extend(_check_evidence(entry, min_count=3, require_tier=True))
    return errors


def _check_entry(name: str, entry: dict) -> list[str]:
    version = _entry_version(entry)
    if version >= 2:
        errors = _check_v2(entry)
        placeholders = _PLACEHOLDERS_V2
    else:
        errors = _check_common(entry)
        errors.extend(_check_evidence(entry, min_count=2, require_tier=False))
        placeholders = _PLACEHOLDERS_V1

    blob = json.dumps(entry, ensure_ascii=False)
    hit = next((p for p in placeholders if p in blob), None)
    if hit:
        errors.append(f"仍含占位符 {hit!r}")

    return [f"[{name} v{version}] {e}" for e in errors]


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else _DEFAULT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"FAIL: 无法读取/解析 {path}: {exc}")
        return 1

    entries = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    if not entries:
        print("FAIL: 无任何研究条目")
        return 1

    all_errors: list[str] = []
    for name, entry in entries.items():
        all_errors.extend(_check_entry(name, entry))

    if all_errors:
        print(f"FAIL: {len(entries)} 条中 {len(all_errors)} 项不合格:")
        for err in all_errors:
            print("  -", err)
        return 1

    print(f"PASS: {len(entries)} 条研究全部合格。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
