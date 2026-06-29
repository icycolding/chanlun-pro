from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Dict, Iterable, List, Sequence
from urllib.parse import urlencode

from .a_share_matches_tweet_notes import get_project_tweet_note
from .serenity_analysis_inputs import get_serenity_archive_metadata

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
_TWEETS_JSON_PATH = (
    _PROJECT_ROOT / "serenity-aleabitoreddit-main" / "data" / "aleabitoreddit_tweets.json"
)
_TWEETS_CACHE: List[Dict[str, Any]] | None = None
_TWEETS_CACHE_MTIME_NS: int | None = None

_TICKER_ALIASES = {
    "SIVE": ["SIVEF", "SIVE.ST"],
    "IQE": ["IQE.L"],
    "SOI": ["SOI.PA", "SOITEC"],
    "TSM": ["TSMC"],
    "LPK": ["LPKF"],
}


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_phrase(value: str) -> str:
    return _normalize_space(value).casefold()


def _text_for_match(tweet: Dict[str, Any]) -> str:
    return "\n".join(
        [
            str(tweet.get("text") or ""),
            str((tweet.get("quotedTweet") or {}).get("text") or ""),
        ]
    )


def _compile_ticker_pattern(token: str) -> re.Pattern[str] | None:
    normalized = str(token or "").strip().upper()
    if not normalized:
        return None
    escaped = re.escape(normalized)
    return re.compile(rf"(?<![A-Z0-9])(?:\$)?{escaped}(?![A-Z0-9])", re.IGNORECASE)


def _extract_company_terms(company_name: str, display_name: str) -> List[str]:
    candidates = []
    for raw in [display_name, company_name]:
        value = _normalize_space(raw)
        if not value:
            continue
        candidates.append(value)
        simplified = re.sub(r"\s*\(.*?\)\s*", " ", value)
        simplified = _normalize_space(
            re.sub(r"\b(AB|INC|CORPORATION|CORP|GROUP|HOLDINGS|LIMITED|LTD|PUBL)\b", " ", simplified, flags=re.IGNORECASE)
        )
        if simplified and simplified != value and len(simplified) >= 4:
            candidates.append(simplified)
    unique_terms = []
    seen = set()
    for term in candidates:
        key = term.casefold()
        if key in seen or len(term) < 4:
            continue
        seen.add(key)
        unique_terms.append(term)
    return unique_terms


def load_serenity_tweets() -> List[Dict[str, Any]]:
    global _TWEETS_CACHE, _TWEETS_CACHE_MTIME_NS
    current_mtime_ns = _TWEETS_JSON_PATH.stat().st_mtime_ns
    if _TWEETS_CACHE is not None and _TWEETS_CACHE_MTIME_NS == current_mtime_ns:
        return _TWEETS_CACHE

    with _TWEETS_JSON_PATH.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    _TWEETS_CACHE = payload if isinstance(payload, list) else []
    _TWEETS_CACHE_MTIME_NS = current_mtime_ns
    return _TWEETS_CACHE


def get_tweets_data_version() -> str:
    try:
        return str(_TWEETS_JSON_PATH.stat().st_mtime_ns)
    except FileNotFoundError:
        return "0"


def _clear_tweets_cache() -> None:
    global _TWEETS_CACHE, _TWEETS_CACHE_MTIME_NS
    _TWEETS_CACHE = None
    _TWEETS_CACHE_MTIME_NS = None


load_serenity_tweets.cache_clear = _clear_tweets_cache


def build_project_tweet_query(
    symbol: str,
    company_name: str,
    exchange: str = "",
    market: str = "",
    display_name: str = "",
) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    ticker_tokens = [normalized_symbol]
    ticker_tokens.extend(_TICKER_ALIASES.get(normalized_symbol, []))
    ticker_patterns = []
    for token in ticker_tokens:
        pattern = _compile_ticker_pattern(token)
        if pattern is not None:
            ticker_patterns.append((token, pattern))

    company_terms = _extract_company_terms(company_name, display_name)
    return {
        "symbol": normalized_symbol,
        "company_name": _normalize_space(company_name),
        "display_name": _normalize_space(display_name),
        "exchange": _normalize_space(exchange),
        "market": _normalize_space(market),
        "ticker_patterns": ticker_patterns,
        "company_terms": company_terms,
    }


def match_tweet_to_project_stock(tweet: Dict[str, Any], query: Dict[str, Any]) -> List[str]:
    haystack = _text_for_match(tweet)
    haystack_folded = haystack.casefold()
    reasons: List[str] = []

    for token, pattern in query.get("ticker_patterns", []):
        if pattern.search(haystack):
            label = "Ticker"
            if token != query.get("symbol"):
                label = f"Ticker Alias ({token})"
            reasons.append(label)

    for term in query.get("company_terms", []):
        if _normalize_phrase(term) in haystack_folded:
            reasons.append(f"Company Name ({term})")

    if "quotedtweet" not in "".join(reasons).lower():
        quoted_text = str((tweet.get("quotedTweet") or {}).get("text") or "")
        if quoted_text:
            quoted_folded = quoted_text.casefold()
            for term in query.get("company_terms", []):
                if _normalize_phrase(term) in quoted_folded:
                    reasons.append("Quoted Tweet")
                    break
            else:
                for _, pattern in query.get("ticker_patterns", []):
                    if pattern.search(quoted_text):
                        reasons.append("Quoted Tweet")
                        break

    deduped: List[str] = []
    seen = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return deduped


def _tweet_to_view_model(tweet: Dict[str, Any], match_reasons: Sequence[str]) -> Dict[str, Any]:
    metrics = tweet.get("metrics") or {}
    author = tweet.get("author") or {}
    quoted_tweet = tweet.get("quotedTweet") or {}
    tweet_id = str(tweet.get("id") or "")
    screen_name = str(author.get("screenName") or "aleabitoreddit")
    return {
        "id": tweet_id,
        "text": str(tweet.get("text") or ""),
        "text_zh": str(tweet.get("text_zh") or ""),
        "quoted_text": str(quoted_tweet.get("text") or ""),
        "quoted_text_zh": str(quoted_tweet.get("text_zh") or ""),
        "created_at_local": str(tweet.get("createdAtLocal") or ""),
        "created_at_iso": str(tweet.get("createdAtISO") or ""),
        "url": f"https://x.com/{screen_name}/status/{tweet_id}" if tweet_id else "",
        "likes": int(metrics.get("likes") or 0),
        "retweets": int(metrics.get("retweets") or 0),
        "replies": int(metrics.get("replies") or 0),
        "quotes": int(metrics.get("quotes") or 0),
        "views": int(metrics.get("views") or 0),
        "match_reasons": list(match_reasons),
    }


def find_related_tweets_for_stock(
    symbol: str,
    company_name: str,
    exchange: str = "",
    market: str = "",
    display_name: str = "",
) -> List[Dict[str, Any]]:
    query = build_project_tweet_query(symbol, company_name, exchange, market, display_name)
    matched: List[Dict[str, Any]] = []
    seen_ids = set()
    for tweet in load_serenity_tweets():
        reasons = match_tweet_to_project_stock(tweet, query)
        tweet_id = str(tweet.get("id") or "")
        if not reasons or not tweet_id or tweet_id in seen_ids:
            continue
        seen_ids.add(tweet_id)
        matched.append(_tweet_to_view_model(tweet, reasons))
    matched.sort(key=lambda item: item.get("created_at_iso") or "", reverse=True)
    return matched


def build_tweet_detail_url(
    symbol: str,
    company_name: str,
    exchange: str = "",
    market: str = "",
    display_name: str = "",
) -> str:
    params = {
        "company_name": _normalize_space(company_name),
        "exchange": _normalize_space(exchange),
        "market": _normalize_space(market),
        "display_name": _normalize_space(display_name),
    }
    query = urlencode({k: v for k, v in params.items() if v})
    base = f"/a_share_matches/tweets/{symbol}"
    return f"{base}?{query}" if query else base


def build_tweet_summary_for_stock(
    symbol: str,
    company_name: str,
    exchange: str = "",
    market: str = "",
    display_name: str = "",
) -> Dict[str, Any]:
    tweets = find_related_tweets_for_stock(symbol, company_name, exchange, market, display_name)
    latest_mention_at = tweets[0]["created_at_local"] if tweets else ""
    return {
        "symbol": str(symbol or "").strip(),
        "mention_count": len(tweets),
        "latest_mention_at": latest_mention_at,
        "detail_url": build_tweet_detail_url(symbol, company_name, exchange, market, display_name),
    }


def build_tweet_summaries(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for item in items or []:
        summaries.append(
            build_tweet_summary_for_stock(
                symbol=str(item.get("symbol") or "").strip(),
                company_name=str(item.get("company_name") or "").strip(),
                exchange=str(item.get("exchange") or "").strip(),
                market=str(item.get("market") or "").strip(),
                display_name=str(item.get("display_name") or "").strip(),
            )
        )
    return summaries


def build_tweet_detail_payload(
    symbol: str,
    company_name: str,
    exchange: str = "",
    market: str = "",
    display_name: str = "",
) -> Dict[str, Any]:
    tweets = find_related_tweets_for_stock(symbol, company_name, exchange, market, display_name)
    latest_mention_at = tweets[0]["created_at_local"] if tweets else ""
    note = get_project_tweet_note(symbol)
    archive_metadata = get_serenity_archive_metadata()
    return {
        "symbol": str(symbol or "").strip(),
        "company_name": _normalize_space(company_name),
        "exchange": _normalize_space(exchange),
        "market": _normalize_space(market),
        "display_name": _normalize_space(display_name),
        "mention_count": len(tweets),
        "latest_mention_at": latest_mention_at,
        "overview_title": str(note.get("overview_title") or ""),
        "overview_summary": str(note.get("overview_summary") or ""),
        "why_serenity_likes_it": str(note.get("why_serenity_likes_it") or ""),
        "industry_chain": dict(note.get("industry_chain") or {}),
        "stage_view": dict(note.get("stage_view") or {}),
        "market_cap_view": dict(note.get("market_cap_view") or {}),
        "timeline_sections": list(note.get("timeline_sections") or []),
        "tweets": tweets,
        "data_version": get_tweets_data_version(),
        "source_scope": archive_metadata.get("source_scope") or "serenity_x_archive_only",
        "archive_updated_at": archive_metadata.get("archive_updated_at") or "",
        "latest_archive_at": archive_metadata.get("latest_archive_at") or "",
        "source_status": archive_metadata.get("status") or "unavailable",
        "coverage_note": archive_metadata.get("coverage_note")
        or "当前仅覆盖 Serenity 的 X/Twitter 档案，不代表全网讨论，也不含实时行情。",
    }
