from __future__ import annotations

from typing import Any, Dict, List, Optional

POSITIVE_CUES = ["上涨", "走高", "走强", "反弹", "攀升", "升值", "新高", "偏强"]
NEGATIVE_CUES = ["下跌", "走低", "走弱", "回落", "下挫", "贬值", "新低", "偏弱"]


ASSET_CONTEXT: Dict[str, Dict[str, Any]] = {
    "USD": {
        "asset_type": "currency",
        "canonical_code": "USD",
        "aliases": ["USD", "美元", "US Dollar", "美元指数", "DXY"],
        "drivers": ["美联储", "Fed", "FOMC", "非农", "CPI", "PCE", "美债收益率"],
    },
    "CNY": {
        "asset_type": "currency",
        "canonical_code": "CNY",
        "aliases": ["CNY", "CNH", "人民币", "在岸人民币", "离岸人民币", "人民币汇率"],
        "drivers": ["中国人民银行", "人民银行", "PBOC", "人民币中间价", "逆周期因子", "外汇存款准备金率", "中美利差"],
    },
    "CNH": {
        "asset_type": "currency",
        "canonical_code": "CNY",
        "aliases": ["CNH", "CNY", "离岸人民币", "在岸人民币", "人民币汇率"],
        "drivers": ["中国人民银行", "人民银行", "PBOC", "人民币中间价", "逆周期因子", "外汇存款准备金率", "中美利差"],
    },
    "EUR": {
        "asset_type": "currency",
        "canonical_code": "EUR",
        "aliases": ["EUR", "欧元", "Euro", "欧元区"],
        "drivers": ["欧洲央行", "ECB", "欧元区CPI", "欧元区GDP", "拉加德"],
    },
    "JPY": {
        "asset_type": "currency",
        "canonical_code": "JPY",
        "aliases": ["JPY", "日元", "Yen", "日本"],
        "drivers": ["日本央行", "BOJ", "日债收益率", "植田和男"],
    },
    "XAU": {
        "asset_type": "metal",
        "canonical_code": "XAU",
        "aliases": ["XAU", "黄金", "Gold", "伦敦金", "现货黄金"],
        "drivers": ["美联储", "Fed", "美元指数", "DXY", "通胀", "避险"],
    },
    "CL": {
        "asset_type": "commodity",
        "canonical_code": "CL",
        "aliases": ["CL", "原油", "WTI", "Brent", "Oil", "原油期货"],
        "drivers": ["OPEC", "欧佩克", "EIA", "API", "地缘政治", "库存"],
    },
    "USDCNY": {
        "asset_type": "forex",
        "canonical_code": "USDCNY",
        "base_currency": "USD",
        "quote_currency": "CNY",
        "aliases": [
            "USDCNY", "USD/CNY", "USDCNH", "USD/CNH",
            "美元兑人民币", "美元兑离岸人民币", "美元兑在岸人民币",
            "离岸人民币", "在岸人民币", "人民币汇率",
        ],
        "drivers": [
            "中国人民银行", "人民银行", "PBOC", "人民币中间价", "逆周期因子",
            "外汇存款准备金率", "中美利差", "美联储", "Fed", "美元指数", "DXY",
        ],
    },
    "USDCNH": {
        "asset_type": "forex",
        "canonical_code": "USDCNY",
        "base_currency": "USD",
        "quote_currency": "CNH",
        "aliases": [
            "USDCNH", "USD/CNH", "USDCNY", "USD/CNY",
            "美元兑离岸人民币", "美元兑人民币", "离岸人民币", "人民币汇率",
        ],
        "drivers": [
            "中国人民银行", "人民银行", "PBOC", "人民币中间价", "逆周期因子",
            "外汇存款准备金率", "中美利差", "美联储", "Fed", "美元指数", "DXY",
        ],
    },
    "EURUSD": {
        "asset_type": "forex",
        "canonical_code": "EURUSD",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "aliases": ["EURUSD", "EUR/USD", "欧元美元", "欧美"],
        "drivers": ["欧洲央行", "ECB", "美联储", "Fed", "欧元区CPI", "非农"],
    },
}


def deduplicate_terms(terms: List[str]) -> List[str]:
    cleaned_terms = []
    seen = set()
    for term in terms:
        normalized = str(term or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned_terms.append(normalized)
    return cleaned_terms


def normalize_asset_code(product_code: Optional[str]) -> str:
    code = str(product_code or "").strip().upper()
    if "." in code:
        code = code.split(".")[-1]
    return code.replace("/", "").replace("-", "").replace(" ", "")


def get_asset_profile(asset_code: Optional[str]) -> Dict[str, Any]:
    normalized_code = normalize_asset_code(asset_code)
    return ASSET_CONTEXT.get(normalized_code, {})


def get_asset_context_terms(asset_code: Optional[str]) -> Dict[str, Any]:
    profile = get_asset_profile(asset_code)
    if profile:
        return profile
    normalized_code = normalize_asset_code(asset_code)
    return {
        "asset_type": "unknown",
        "canonical_code": normalized_code,
        "aliases": [normalized_code] if normalized_code else [],
        "drivers": [],
    }


def infer_news_asset_links(
    title: str,
    body: str,
    product_info: Optional[Dict[str, Any]] = None,
    product_code: Optional[str] = None,
) -> Dict[str, Any]:
    text = f"{title or ''}\n{body or ''}".lower()
    direct_assets: List[str] = []
    driver_assets: List[str] = []
    matched_terms: List[str] = []
    direct_asset_hits: Dict[str, Dict[str, Any]] = {}

    candidate_codes = deduplicate_terms(
        [
            normalize_asset_code(product_code),
            normalize_asset_code((product_info or {}).get("original_code")),
            normalize_asset_code((product_info or {}).get("symbol")),
            normalize_asset_code((product_info or {}).get("canonical_code")),
            "USDCNY" if "人民币" in text and "美元" in text else "",
        ]
    )

    for asset_code, profile in ASSET_CONTEXT.items():
        alias_hits = [alias for alias in profile.get("aliases", []) if alias and alias.lower() in text]

        if asset_code in candidate_codes:
            alias_hits = alias_hits + [asset_code]

        if alias_hits:
            canonical_code = profile.get("canonical_code", asset_code)
            direct_assets.append(canonical_code)
            direct_asset_hits[canonical_code] = profile
            matched_terms.extend(alias_hits[:6])

    if direct_asset_hits:
        for canonical_code, profile in direct_asset_hits.items():
            driver_hits = [
                driver for driver in profile.get("drivers", [])
                if driver and driver.lower() in text
            ]
            if driver_hits:
                driver_assets.append(canonical_code)
                matched_terms.extend(driver_hits[:6])
    else:
        for asset_code, profile in ASSET_CONTEXT.items():
            driver_hits = [
                driver for driver in profile.get("drivers", [])
                if driver and driver.lower() in text
            ]
            if driver_hits:
                driver_assets.append(profile.get("canonical_code", asset_code))
                matched_terms.extend(driver_hits[:6])

    direct_assets = deduplicate_terms(direct_assets)
    driver_assets = deduplicate_terms(driver_assets)

    return {
        "direct_assets": direct_assets,
        "driver_assets": driver_assets,
        "matched_terms": deduplicate_terms(matched_terms)[:20],
    }


def build_asset_link_rows(
    news_id: str,
    title: str,
    body: str,
    product_info: Optional[Dict[str, Any]] = None,
    product_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    links = infer_news_asset_links(
        title=title,
        body=body,
        product_info=product_info,
        product_code=product_code,
    )
    rows: List[Dict[str, Any]] = []

    for asset in links.get("direct_assets", []):
        rows.append(
            {
                "news_id": news_id,
                "asset_code": asset,
                "canonical_asset": asset,
                "relation_type": "direct",
                "confidence": 0.95,
                "reason": "新闻文本直接命中资产别名",
                "matched_terms": links.get("matched_terms", []),
            }
        )

    for asset in links.get("driver_assets", []):
        rows.append(
            {
                "news_id": news_id,
                "asset_code": asset,
                "canonical_asset": asset,
                "relation_type": "driver",
                "confidence": 0.72,
                "reason": "新闻文本命中资产驱动因子",
                "matched_terms": links.get("matched_terms", []),
            }
        )

    return rows


def _count_phrase_hits(text: str, aliases: List[str], positive: bool) -> int:
    cues = POSITIVE_CUES if positive else NEGATIVE_CUES
    hits = 0
    for alias in aliases:
        alias_lower = str(alias or "").lower()
        if not alias_lower:
            continue
        for cue in cues:
            cue_lower = cue.lower()
            if f"{alias_lower}{cue_lower}" in text or f"{cue_lower}{alias_lower}" in text:
                hits += 1
    return hits


def infer_asset_impact_direction(
    title: str,
    body: str,
    canonical_asset: str,
) -> Dict[str, Any]:
    text = f"{title or ''}\n{body or ''}".lower()
    profile = get_asset_profile(canonical_asset)
    if not profile:
        return {"impact_direction": "neutral", "direction_score": 0.0, "reason": "缺少资产画像"}

    bullish_score = 0
    bearish_score = 0

    aliases = profile.get("aliases", [])
    bullish_score += _count_phrase_hits(text, aliases, positive=True)
    bearish_score += _count_phrase_hits(text, aliases, positive=False)

    if profile.get("asset_type") == "forex":
        base_aliases = get_asset_context_terms(profile.get("base_currency", "")).get("aliases", [])
        quote_aliases = get_asset_context_terms(profile.get("quote_currency", "")).get("aliases", [])

        bullish_score += _count_phrase_hits(text, base_aliases, positive=True)
        bullish_score += _count_phrase_hits(text, quote_aliases, positive=False)
        bearish_score += _count_phrase_hits(text, base_aliases, positive=False)
        bearish_score += _count_phrase_hits(text, quote_aliases, positive=True)

    if bullish_score > bearish_score:
        return {
            "impact_direction": "bullish",
            "direction_score": float(bullish_score - bearish_score),
            "reason": "文本中利多短语多于利空短语",
        }
    if bearish_score > bullish_score:
        return {
            "impact_direction": "bearish",
            "direction_score": float(bearish_score - bullish_score),
            "reason": "文本中利空短语多于利多短语",
        }
    return {
        "impact_direction": "neutral",
        "direction_score": 0.0,
        "reason": "未识别到明确方向性短语",
    }
