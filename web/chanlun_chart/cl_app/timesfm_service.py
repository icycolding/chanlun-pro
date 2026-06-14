#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import logging
import math
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

os.environ.setdefault("JAX_PLATFORMS", "cpu")

from chanlun.db import db

logger = logging.getLogger(__name__)

_TIMESFM_CACHE_PREFIX = "timesfm_forecast:"
_TIMESFM_CACHE_EXPIRE_SECONDS = 15 * 60
_TIMESFM_NATIVE_MODEL_LOCK = threading.Lock()
_TIMESFM_NATIVE_MODEL = None
_TIMESFM_NATIVE_MODEL_META: Dict[str, Any] = {}
_TIMESFM_IMPORTED_MODULE = None
_TIMESFM_IMPORTED_META: Dict[str, Any] = {}
_TIMESFM_NATIVE_RUNTIME_STATUS_LOCK = threading.Lock()
_TIMESFM_NATIVE_RUNTIME_STATUS: Dict[str, Any] = {}
_TIMESFM_NATIVE_RUNTIME_STATUS_TTL_SECONDS = 60


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _frequency_to_minutes(frequency: str) -> int:
    text = str(frequency or "").strip().lower()
    mapping = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "1h": 60,
        "4h": 240,
        "d": 1440,
    }
    return mapping.get(text, 5)


def _normalize_frequency(frequency: str) -> str:
    text = str(frequency or "").strip().lower()
    mapping = {
        "1h": "60m",
        "1d": "d",
    }
    return mapping.get(text, text or "5m")


def _frequency_label(frequency: str) -> str:
    return {
        "1m": "1分钟",
        "3m": "3分钟",
        "5m": "5分钟",
        "15m": "15分钟",
        "30m": "30分钟",
        "60m": "1小时",
        "1h": "1小时",
        "4h": "4小时",
        "d": "1日",
        "1d": "1日",
    }.get(str(frequency or "").strip().lower(), str(frequency or "").strip() or "5分钟")


def _minutes_label(total_minutes: int) -> str:
    total_minutes = max(int(total_minutes or 0), 1)
    if total_minutes % 1440 == 0:
        days = total_minutes // 1440
        return f"{days}日"
    if total_minutes % 60 == 0:
        hours = total_minutes // 60
        return f"{hours}小时"
    return f"{total_minutes}分钟"


def _candidate_timesfm_src_paths() -> List[str]:
    candidates: List[str] = []
    for path in [
        os.getenv("TIMESFM_LOCAL_SRC_PATH", "").strip(),
        "/Users/jiming/Documents/GitHub/timesfm/src",
    ]:
        if path and os.path.isdir(path) and path not in candidates:
            candidates.append(path)
    return candidates


def _import_timesfm_module() -> Any:
    global _TIMESFM_IMPORTED_MODULE, _TIMESFM_IMPORTED_META
    if _TIMESFM_IMPORTED_MODULE is not None:
        return _TIMESFM_IMPORTED_MODULE

    errors: List[str] = []
    candidates: List[Optional[str]] = _candidate_timesfm_src_paths() + [None]
    for candidate in candidates:
        try:
            if candidate and candidate not in sys.path:
                sys.path.insert(0, candidate)
            sys.modules.pop("timesfm", None)
            module = importlib.import_module("timesfm")
            module_file = str(getattr(module, "__file__", "") or "")
            if candidate and module_file and not module_file.startswith(candidate):
                raise RuntimeError(f"已找到模块但未命中候选源码目录: {module_file}")
            _TIMESFM_IMPORTED_MODULE = module
            _TIMESFM_IMPORTED_META = {
                "module_file": module_file,
                "module_source": "local_repo" if candidate else "site_package",
                "module_version": str(getattr(module, "__version__", "") or ""),
            }
            return module
        except Exception as exc:
            source = candidate or "site_package"
            errors.append(f"{source}: {exc}")
    raise RuntimeError(" ; ".join(errors) if errors else "TimesFM 模块不可用")


def _native_runtime_config() -> Dict[str, Any]:
    return {
        "model_name": os.getenv("TIMESFM_MODEL_NAME", "google/timesfm-2.5-200m-pytorch"),
        "max_context": max(_safe_int(os.getenv("TIMESFM_MAX_CONTEXT"), 1024), 256),
        "max_horizon": max(_safe_int(os.getenv("TIMESFM_MAX_HORIZON"), 256), 16),
        "per_core_batch_size": max(_safe_int(os.getenv("TIMESFM_BATCH_SIZE"), 8), 1),
    }


def _ensure_scaled_dot_product_attention_compat(torch_module: Any) -> None:
    functional = torch_module.nn.functional
    if hasattr(functional, "scaled_dot_product_attention"):
        return
    private_impl = getattr(functional, "_scaled_dot_product_attention", None)
    if private_impl is None:
        raise RuntimeError("当前 PyTorch 版本过低，缺少 scaled_dot_product_attention")

    def _compat_scaled_dot_product_attention(
        query: Any,
        key: Any,
        value: Any,
        attn_mask: Optional[Any] = None,
        dropout_p: float = 0.0,
        is_causal: bool = False,
        scale: Optional[float] = None,
        enable_gqa: bool = False,
    ) -> Any:
        if enable_gqa:
            raise RuntimeError("当前 PyTorch 兼容实现暂不支持 enable_gqa")
        scale_factor = float(scale) if scale is not None else 1.0 / math.sqrt(max(int(query.shape[-1]), 1))
        if is_causal:
            q_len = int(query.shape[-2])
            k_len = int(key.shape[-2])
            causal_mask = torch_module.tril(
                torch_module.ones((q_len, k_len), dtype=torch_module.bool, device=query.device)
            )
            if attn_mask is None:
                attn_mask = causal_mask
            elif getattr(attn_mask, "dtype", None) == torch_module.bool:
                attn_mask = torch_module.logical_and(attn_mask, causal_mask)
            else:
                causal_bias = torch_module.zeros((q_len, k_len), dtype=query.dtype, device=query.device)
                causal_bias = causal_bias.masked_fill(torch_module.logical_not(causal_mask), float("-inf"))
                attn_mask = attn_mask + causal_bias
        if attn_mask is not None and getattr(attn_mask, "dtype", None) == torch_module.bool:
            score_bias = torch_module.zeros_like(
                torch_module.matmul(query, key.transpose(-2, -1)),
                dtype=query.dtype,
            )
            score_bias = score_bias.masked_fill(torch_module.logical_not(attn_mask), float("-inf"))
        elif attn_mask is not None:
            score_bias = attn_mask
        else:
            score_bias = None
        scores = torch_module.matmul(query, key.transpose(-2, -1)) * scale_factor
        if score_bias is not None:
            scores = scores + score_bias
        weights = torch_module.softmax(scores, dim=-1)
        if dropout_p and float(dropout_p) > 0:
            weights = functional.dropout(weights, p=float(dropout_p), training=True)
        output = torch_module.matmul(weights, value)
        return output

    functional.scaled_dot_product_attention = _compat_scaled_dot_product_attention


def _get_native_model():
    global _TIMESFM_NATIVE_MODEL, _TIMESFM_NATIVE_MODEL_META
    if _TIMESFM_NATIVE_MODEL is not None:
        return _TIMESFM_NATIVE_MODEL, dict(_TIMESFM_NATIVE_MODEL_META)

    with _TIMESFM_NATIVE_MODEL_LOCK:
        if _TIMESFM_NATIVE_MODEL is not None:
            return _TIMESFM_NATIVE_MODEL, dict(_TIMESFM_NATIVE_MODEL_META)

        timesfm = _import_timesfm_module()
        runtime = _native_runtime_config()

        try:
            import torch  # type: ignore

            torch.set_float32_matmul_precision("high")
            _ensure_scaled_dot_product_attention_compat(torch)
        except Exception:
            raise

        if not hasattr(timesfm, "TimesFM_2p5_200M_torch"):
            raise RuntimeError("当前 TimesFM 环境缺少 TimesFM_2p5_200M_torch")

        model = _load_native_timesfm_model(timesfm.TimesFM_2p5_200M_torch, runtime["model_name"])
        model.compile(
            timesfm.ForecastConfig(
                max_context=runtime["max_context"],
                max_horizon=runtime["max_horizon"],
                normalize_inputs=True,
                per_core_batch_size=runtime["per_core_batch_size"],
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
                return_backcast=True,
            )
        )
        _TIMESFM_NATIVE_MODEL = model
        _TIMESFM_NATIVE_MODEL_META = {
            **_TIMESFM_IMPORTED_META,
            "model_name": runtime["model_name"],
            "max_context": runtime["max_context"],
            "max_horizon": runtime["max_horizon"],
            "per_core_batch_size": runtime["per_core_batch_size"],
            "device": getattr(getattr(model, "model", None), "device", None) or getattr(model, "device", "cpu"),
            "torch_available": torch is not None,
        }
        return _TIMESFM_NATIVE_MODEL, dict(_TIMESFM_NATIVE_MODEL_META)


def _load_native_timesfm_model(model_cls: Any, model_name: str) -> Any:
    last_error: Optional[Exception] = None
    from_pretrained = getattr(model_cls, "from_pretrained", None)
    if callable(from_pretrained):
        try:
            return from_pretrained(model_name)
        except TypeError as exc:
            last_error = exc
            if "unexpected keyword argument 'proxies'" not in str(exc):
                raise
            logger.warning("TimesFM from_pretrained 与当前 huggingface_hub proxies 参数不兼容，回退到兼容加载路径")
        except Exception as exc:
            last_error = exc
            raise

    compat_loader = getattr(model_cls, "_from_pretrained", None)
    if callable(compat_loader):
        compat_kwargs = {
            "model_id": model_name,
            "revision": None,
            "cache_dir": None,
            "force_download": False,
            "local_files_only": False,
            "token": None,
            "config": None,
        }
        try:
            signature = inspect.signature(compat_loader)
            accepts_var_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
            )
            filtered_kwargs = compat_kwargs if accepts_var_kwargs else {
                key: value for key, value in compat_kwargs.items() if key in signature.parameters
            }
        except (TypeError, ValueError):
            filtered_kwargs = compat_kwargs
        return compat_loader(**filtered_kwargs)

    if last_error is not None:
        raise last_error
    raise RuntimeError("当前 TimesFM 模型类缺少可用的预训练加载方法")


def get_timesfm_native_runtime_status(force_refresh: bool = False) -> Dict[str, Any]:
    now_ts = time.time()
    with _TIMESFM_NATIVE_RUNTIME_STATUS_LOCK:
        cached = dict(_TIMESFM_NATIVE_RUNTIME_STATUS)
    cached_checked_at = _safe_float(cached.get("checked_at"), 0.0)
    if (
        not force_refresh
        and cached.get("available") is not None
        and now_ts - cached_checked_at < _TIMESFM_NATIVE_RUNTIME_STATUS_TTL_SECONDS
    ):
        return cached

    try:
        _, meta = _get_native_model()
        status = {
            "available": True,
            "reason": "",
            "checked_at": now_ts,
            "meta": dict(meta),
        }
    except Exception as exc:
        status = {
            "available": False,
            "reason": f"TimesFM 原生模型不可用: {exc}",
            "checked_at": now_ts,
            "meta": dict(_TIMESFM_IMPORTED_META),
        }

    with _TIMESFM_NATIVE_RUNTIME_STATUS_LOCK:
        _TIMESFM_NATIVE_RUNTIME_STATUS.clear()
        _TIMESFM_NATIVE_RUNTIME_STATUS.update(status)
    return dict(status)


def _build_horizon_meta(frequency: str, horizon_bars: int) -> Dict[str, Any]:
    normalized_frequency = _normalize_frequency(frequency)
    total_minutes = _frequency_to_minutes(normalized_frequency) * max(int(horizon_bars or 1), 1)
    return {
        "horizon_bars": max(int(horizon_bars or 1), 1),
        "horizon_minutes": total_minutes,
        "horizon_label": _minutes_label(total_minutes),
        "frequency": normalized_frequency,
        "frequency_label": _frequency_label(normalized_frequency),
    }


def _serialize_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def _bar_close(bar: Dict[str, Any]) -> float:
    return _safe_float(bar.get("close"))


def _bar_open(bar: Dict[str, Any]) -> float:
    return _safe_float(bar.get("open"))


def _bar_high(bar: Dict[str, Any]) -> float:
    return _safe_float(bar.get("high"))


def _bar_low(bar: Dict[str, Any]) -> float:
    return _safe_float(bar.get("low"))


def _bar_volume(bar: Dict[str, Any]) -> float:
    return _safe_float(bar.get("volume"))


def _bar_dt(bar: Dict[str, Any]) -> str:
    dt_value = bar.get("dt") or bar.get("datetime") or bar.get("time")
    return _serialize_datetime(dt_value)


def _mean(values: List[float], default: float = 0.0) -> float:
    cleaned = [_safe_float(item) for item in values if item is not None]
    if not cleaned:
        return default
    return sum(cleaned) / len(cleaned)


def _median(values: List[float], default: float = 0.0) -> float:
    cleaned = sorted(_safe_float(item) for item in values if item is not None)
    if not cleaned:
        return default
    mid = len(cleaned) // 2
    if len(cleaned) % 2 == 1:
        return cleaned[mid]
    return (cleaned[mid - 1] + cleaned[mid]) / 2.0


def _compute_returns(price_bars: List[Dict[str, Any]]) -> List[float]:
    closes = [_bar_close(bar) for bar in price_bars]
    returns: List[float] = []
    for idx in range(1, len(closes)):
        prev_close = max(abs(closes[idx - 1]), 1e-9)
        returns.append((closes[idx] - closes[idx - 1]) / prev_close)
    return returns


def _series_digest(series: List[float]) -> str:
    payload = json.dumps([round(item, 8) for item in series], ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _ohlcv_covariate_digest(covariates: Dict[str, List[float]]) -> str:
    payload = json.dumps(
        {key: [round(_safe_float(item), 8) for item in values] for key, values in sorted(covariates.items())},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _build_ohlcv_dynamic_covariates(
    context_bars: List[Dict[str, Any]],
    horizon_bars: int,
) -> Dict[str, Any]:
    if not context_bars:
        return {
            "enabled": False,
            "dynamic_numerical_covariates": {},
            "feature_names": [],
            "projection_method": "",
            "digest": "",
            "recent_summary": {},
        }

    open_gap_path: List[float] = []
    high_spread_path: List[float] = []
    low_spread_path: List[float] = []
    volume_ratio_path: List[float] = []
    candle_body_path: List[float] = []

    for idx, bar in enumerate(context_bars):
        close_price = _bar_close(bar)
        prev_close = _bar_close(context_bars[idx - 1]) if idx > 0 else close_price
        safe_prev_close = max(abs(prev_close), 1e-9)
        safe_close = max(abs(close_price), 1e-9)

        open_gap_path.append((_bar_open(bar) - prev_close) / safe_prev_close)
        high_spread_path.append((_bar_high(bar) - close_price) / safe_close)
        low_spread_path.append((_bar_low(bar) - close_price) / safe_close)
        candle_body_path.append((close_price - _bar_open(bar)) / safe_prev_close)

        rolling_volumes = [_bar_volume(item) for item in context_bars[max(0, idx - 19) : idx + 1]]
        volume_baseline = max(_median(rolling_volumes, default=1.0), 1e-9)
        volume_ratio_path.append((_bar_volume(bar) / volume_baseline) - 1.0)

    recent_window = max(4, min(len(context_bars), 12))
    open_gap_future = [_mean(open_gap_path[-recent_window:])] * horizon_bars
    high_spread_future = [max(_mean(high_spread_path[-recent_window:]), 0.0)] * horizon_bars
    low_spread_future = [min(_mean(low_spread_path[-recent_window:]), 0.0)] * horizon_bars
    volume_ratio_future = [_mean(volume_ratio_path[-recent_window:])] * horizon_bars
    candle_body_future = [_mean(candle_body_path[-recent_window:])] * horizon_bars

    dynamic_numerical_covariates = {
        "ohlcv_open_gap_pct": [open_gap_path + open_gap_future],
        "ohlcv_high_spread_pct": [high_spread_path + high_spread_future],
        "ohlcv_low_spread_pct": [low_spread_path + low_spread_future],
        "ohlcv_volume_ratio": [volume_ratio_path + volume_ratio_future],
        "ohlcv_candle_body_pct": [candle_body_path + candle_body_future],
    }
    feature_names = list(dynamic_numerical_covariates.keys())
    return {
        "enabled": True,
        "dynamic_numerical_covariates": dynamic_numerical_covariates,
        "feature_names": feature_names,
        "projection_method": "recent_profile_carry_forward",
        "digest": _ohlcv_covariate_digest({key: values[0] for key, values in dynamic_numerical_covariates.items()}),
        "recent_summary": {
            "open_gap_pct": round(_mean(open_gap_path[-recent_window:]) * 100, 4),
            "high_spread_pct": round(_mean(high_spread_path[-recent_window:]) * 100, 4),
            "low_spread_pct": round(_mean(low_spread_path[-recent_window:]) * 100, 4),
            "volume_ratio_pct": round(_mean(volume_ratio_path[-recent_window:]) * 100, 4),
            "candle_body_pct": round(_mean(candle_body_path[-recent_window:]) * 100, 4),
            "recent_window": recent_window,
        },
    }


def build_timesfm_input(
    price_bars: List[Dict[str, Any]],
    market: str,
    code: str,
    frequency: str,
    horizon_bars: int,
    context_length: int = 120,
    covariates: Optional[Dict[str, Any]] = None,
    context_end: Optional[Any] = None,
) -> Dict[str, Any]:
    if not price_bars:
        raise ValueError("缺少价格数据")
    effective_context_length = max(10, min(int(context_length or 120), len(price_bars)))
    context_bars = price_bars[-effective_context_length:]
    series = [_bar_close(bar) for bar in context_bars]
    if len(series) < 10:
        raise ValueError("价格上下文不足，无法构建预测输入")
    covariates = covariates or {}
    use_price_covariates = bool(covariates.get("use_price_covariates"))
    price_covariate_bundle = (
        _build_ohlcv_dynamic_covariates(context_bars=context_bars, horizon_bars=int(horizon_bars))
        if use_price_covariates
        else {
            "enabled": False,
            "dynamic_numerical_covariates": {},
            "feature_names": [],
            "projection_method": "",
            "digest": "",
            "recent_summary": {},
        }
    )
    final_context_end = context_end or context_bars[-1].get("dt")
    return {
        "market": (market or "").strip(),
        "code": (code or "").strip().upper(),
        "frequency": _normalize_frequency(frequency),
        "horizon_bars": int(horizon_bars),
        "context_length": effective_context_length,
        "context_end": _serialize_datetime(final_context_end),
        "series": series,
        "series_digest": _series_digest(series),
        "covariates": covariates,
        "price_covariates_enabled": price_covariate_bundle.get("enabled", False),
        "price_covariate_feature_names": price_covariate_bundle.get("feature_names", []),
        "price_covariate_projection_method": price_covariate_bundle.get("projection_method", ""),
        "price_covariate_recent_summary": price_covariate_bundle.get("recent_summary", {}),
        "price_covariate_digest": price_covariate_bundle.get("digest", ""),
        "price_dynamic_covariates": price_covariate_bundle.get("dynamic_numerical_covariates", {}),
    }

def _pct_from_prices(prices: List[float], base_price: float) -> List[float]:
    safe_base = max(abs(base_price), 1e-9)
    return [round(((price - base_price) / safe_base) * 100, 4) for price in prices]


def _build_quantile_dict_from_prices(
    quantile_prices: Dict[str, List[float]],
    latest_price: float,
) -> Dict[str, List[float]]:
    return {
        key: _pct_from_prices([_safe_float(value) for value in values], latest_price)
        for key, values in quantile_prices.items()
    }


def _build_display_band_from_quantiles(quantiles_pct: Dict[str, Any]) -> str:
    return f"{_safe_float(quantiles_pct.get('p10')):+.3f}% ~ {_safe_float(quantiles_pct.get('p90')):+.3f}%"


def _recent_move_baseline_pct(series: List[float], horizon_bars: int) -> float:
    if len(series) < 2:
        return max(0.02, math.sqrt(max(int(horizon_bars or 1), 1)) * 0.01)
    returns_pct = [abs(item) * 100.0 for item in _compute_returns([{"close": value} for value in series])]
    if not returns_pct:
        return max(0.02, math.sqrt(max(int(horizon_bars or 1), 1)) * 0.01)
    trailing = returns_pct[-min(len(returns_pct), max(12, int(horizon_bars or 1) * 8)) :]
    baseline_one_bar = max(_median(trailing, default=0.02), 0.005)
    return max(baseline_one_bar * math.sqrt(max(int(horizon_bars or 1), 1)), 0.02)


def _path_direction_consistency(forecast_path_pct: List[float], direction: str) -> float:
    if not forecast_path_pct or direction not in {"bullish", "bearish"}:
        return 0.5
    weighted_total = 0.0
    weighted_match = 0.0
    for idx, value in enumerate(forecast_path_pct):
        weight = float(idx + 1)
        weighted_total += weight
        numeric = _safe_float(value)
        if (direction == "bullish" and numeric > 0) or (direction == "bearish" and numeric < 0):
            weighted_match += weight
        elif abs(numeric) <= 1e-9:
            weighted_match += weight * 0.35
    if weighted_total <= 0:
        return 0.5
    return round(weighted_match / weighted_total, 4)


def _quantile_direction_consensus(
    direction: str,
    p10: float,
    p50: float,
    p90: float,
    direction_threshold: float,
) -> float:
    quantiles = [p10, p50, p90]
    if direction == "bullish":
        matches = [1.0 if value > direction_threshold else 0.4 if value >= 0 else 0.0 for value in quantiles]
    elif direction == "bearish":
        matches = [1.0 if value < -direction_threshold else 0.4 if value <= 0 else 0.0 for value in quantiles]
    else:
        matches = [1.0 if abs(value) <= direction_threshold else 0.0 for value in quantiles]
    return round(sum(matches) / max(len(matches), 1), 4)


def _slice_forecast_tail(raw_output: Any, horizon_bars: int) -> Any:
    if raw_output is None:
        return []
    batch = raw_output[0] if len(raw_output) else []
    if len(batch) <= horizon_bars:
        return batch
    return batch[-horizon_bars:]


def _build_native_xreg_covariates(model_input: Dict[str, Any]) -> Dict[str, Any]:
    series = [_safe_float(item) for item in model_input.get("series", [])]
    covariates = model_input.get("covariates", {}) or {}
    horizon_bars = max(int(model_input.get("horizon_bars", 1) or 1), 1)
    context_length = len(series)
    total_length = context_length + horizon_bars
    has_explicit_event_signal = any(
        key in covariates
        for key in [
            "news_bias_score",
            "cross_asset_bias",
            "scenario_bias",
            "price_bias",
            "direct_news_count",
            "driver_news_count",
            "route",
        ]
    )
    use_event_covariates = bool(covariates.get("use_event_covariates")) or has_explicit_event_signal
    use_price_covariates = bool(model_input.get("price_covariates_enabled"))
    if not use_event_covariates and not use_price_covariates:
        return {
            "enabled": False,
            "dynamic_numerical_covariates": {},
            "static_numerical_covariates": {},
            "static_categorical_covariates": {},
            "feature_names": [],
            "event_covariates_enabled": False,
            "price_covariates_enabled": False,
            "price_feature_names": [],
            "projection_method": "",
        }

    recent_returns = _compute_returns([{"close": value} for value in series])
    padded_returns = [0.0] + recent_returns
    if len(padded_returns) < context_length:
        padded_returns = [0.0] * (context_length - len(padded_returns)) + padded_returns
    else:
        padded_returns = padded_returns[-context_length:]
    last_return = padded_returns[-1] if padded_returns else 0.0

    def constant_path(value: Any) -> List[float]:
        numeric = _safe_float(value)
        return [numeric] * total_length

    dynamic_numerical_covariates: Dict[str, List[List[float]]] = {
        "recent_return": [padded_returns + [last_return] * horizon_bars],
        "time_index": [[float(idx) / max(total_length - 1, 1) for idx in range(total_length)]],
    }
    feature_names = ["recent_return", "time_index"]
    static_numerical_covariates: Dict[str, List[float]] = {}

    if use_event_covariates:
        dynamic_numerical_covariates.update(
            {
                "news_bias_score": [constant_path(covariates.get("news_bias_score"))],
                "cross_asset_bias": [constant_path(covariates.get("cross_asset_bias"))],
                "scenario_bias": [constant_path(covariates.get("scenario_bias"))],
                "price_bias": [constant_path(covariates.get("price_bias"))],
            }
        )
        feature_names.extend(
            [
                "news_bias_score",
                "cross_asset_bias",
                "scenario_bias",
                "price_bias",
            ]
        )
        static_numerical_covariates.update(
            {
                "direct_news_count": [_safe_float(covariates.get("direct_news_count"))],
                "driver_news_count": [_safe_float(covariates.get("driver_news_count"))],
            }
        )

    price_dynamic_covariates = model_input.get("price_dynamic_covariates", {}) or {}
    if use_price_covariates and price_dynamic_covariates:
        dynamic_numerical_covariates.update(price_dynamic_covariates)
        feature_names.extend(list(price_dynamic_covariates.keys()))
        static_numerical_covariates["ohlcv_feature_count"] = [float(len(price_dynamic_covariates))]

    static_categorical_covariates = {
        "market": [str(model_input.get("market", "") or "unknown")],
        "route": [str(covariates.get("route", "") or "balanced_monitoring")],
        "target_field": ["close"],
    }
    return {
        "enabled": True,
        "dynamic_numerical_covariates": dynamic_numerical_covariates,
        "static_numerical_covariates": static_numerical_covariates,
        "static_categorical_covariates": static_categorical_covariates,
        "feature_names": feature_names,
        "event_covariates_enabled": use_event_covariates,
        "price_covariates_enabled": use_price_covariates,
        "price_feature_names": list(price_dynamic_covariates.keys()),
        "projection_method": str(model_input.get("price_covariate_projection_method", "") or ""),
    }


def _build_native_result(
    model_input: Dict[str, Any],
    point_prices: List[float],
    quantile_prices: Dict[str, List[float]],
    backend: str,
    backend_meta: Dict[str, Any],
    xreg_used: bool,
    xreg_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    series = [_safe_float(item) for item in model_input.get("series", [])]
    latest_price = max(abs(series[-1]), 1e-9)
    horizon_bars = int(model_input.get("horizon_bars", len(point_prices)) or len(point_prices))
    frequency = _normalize_frequency(model_input.get("frequency", "5m"))
    horizon_meta = _build_horizon_meta(frequency, horizon_bars)
    point_forecast_pct_path = _pct_from_prices(point_prices, latest_price)
    quantile_pct_path = _build_quantile_dict_from_prices(quantile_prices, latest_price)
    expected_return_pct = point_forecast_pct_path[-1] if point_forecast_pct_path else 0.0
    p10 = quantile_pct_path.get("p10", [expected_return_pct])[-1] if quantile_pct_path.get("p10") else expected_return_pct
    p50 = quantile_pct_path.get("p50", [expected_return_pct])[-1] if quantile_pct_path.get("p50") else expected_return_pct
    p90 = quantile_pct_path.get("p90", [expected_return_pct])[-1] if quantile_pct_path.get("p90") else expected_return_pct
    baseline_move_pct = _recent_move_baseline_pct(series, horizon_bars)
    direction_threshold = max(baseline_move_pct * 0.15, 0.003)
    direction = "bullish" if p50 > direction_threshold else "bearish" if p50 < -direction_threshold else "neutral"
    interval_width = abs(p90 - p10)
    dispersion_score = _clamp(interval_width / max(abs(expected_return_pct), interval_width, 1e-6), 0.08, 1.2)
    path_consistency = _path_direction_consistency(point_forecast_pct_path, direction)
    quantile_consensus = _quantile_direction_consensus(direction, p10, p50, p90, direction_threshold)
    signal_scale = max(interval_width * 0.85, baseline_move_pct, direction_threshold * 2.0)
    signal_strength = abs(p50) / max(signal_scale, 1e-6)
    if direction == "neutral":
        range_compression = max(0.0, 1.0 - min(interval_width / max(baseline_move_pct * 1.35, 0.03), 1.0))
        continuation_probability = _clamp(0.4 + range_compression * 0.12, 0.28, 0.58)
    else:
        continuation_probability = _clamp(
            0.48
            + min(signal_strength, 2.4) * 0.16
            + max(0.0, path_consistency - 0.5) * 0.24
            + max(0.0, quantile_consensus - 0.34) * 0.18,
            0.05,
            0.95,
        )
    reversal_risk = _clamp(
        1.0
        - continuation_probability
        + max(0.0, 0.55 - path_consistency) * 0.2
        + max(0.0, 0.7 - quantile_consensus) * 0.12,
        0.05,
        0.95,
    )
    confidence = _classify_confidence(dispersion_score, continuation_probability)
    uncertainty = _classify_uncertainty(dispersion_score)
    regime = _classify_regime(expected_return_pct / max(interval_width, 1e-6), dispersion_score)
    quantiles_pct = {
        "p10": round(p10, 4),
        "p50": round(p50, 4),
        "p90": round(p90, 4),
    }
    summary = (
        f"未来{horizon_meta['horizon_label']}偏{'上行' if direction == 'bullish' else '下行' if direction == 'bearish' else '震荡'}，"
        f"延续概率{round(continuation_probability * 100)}%，"
        f"中位预期{expected_return_pct:+.3f}% ，区间[{quantiles_pct['p10']:+.3f}%, {quantiles_pct['p90']:+.3f}%]。"
    )
    xreg_meta = xreg_meta or {}
    return {
        "available": True,
        "backend": backend,
        "source": backend,
        "degraded": False,
        "degrade_message": "",
        "market": model_input.get("market", ""),
        "code": model_input.get("code", ""),
        "frequency": frequency,
        "horizon_bars": horizon_bars,
        "horizon_minutes": horizon_meta["horizon_minutes"],
        "horizon_label": horizon_meta["horizon_label"],
        "frequency_label": horizon_meta["frequency_label"],
        "context_length": model_input.get("context_length", len(series)),
        "context_end": model_input.get("context_end", ""),
        "latest_price": round(latest_price, 6),
        "direction": direction,
        "expected_return_pct": round(expected_return_pct, 4),
        "expected_price": round(_safe_float(point_prices[-1]) if point_prices else latest_price, 6),
        "point_forecast_pct_path": point_forecast_pct_path,
        "point_forecast_price_path": [round(_safe_float(value), 6) for value in point_prices],
        "quantiles_pct": quantiles_pct,
        "quantile_forecast_pct_path": quantile_pct_path,
        "quantile_forecast_price_path": {
            key: [round(_safe_float(value), 6) for value in values]
            for key, values in quantile_prices.items()
        },
        "continuation_probability": round(continuation_probability, 4),
        "reversal_risk": round(reversal_risk, 4),
        "dispersion_score": round(dispersion_score, 4),
        "baseline_move_pct": round(baseline_move_pct, 4),
        "direction_threshold_pct": round(direction_threshold, 4),
        "path_consistency": round(path_consistency, 4),
        "quantile_consensus": round(quantile_consensus, 4),
        "forecast_confidence": confidence,
        "uncertainty_level": uncertainty,
        "regime": regime,
        "summary": summary,
        "display_band": _build_display_band_from_quantiles(quantiles_pct),
        "native_model": backend_meta.get("model_name", ""),
        "native_model_source": backend_meta.get("module_source", ""),
        "native_module_file": backend_meta.get("module_file", ""),
        "xreg_used": xreg_used,
        "target_series_field": "close",
        "event_covariates_used": bool(xreg_meta.get("event_covariates_enabled")),
        "price_covariates_used": bool(xreg_meta.get("price_covariates_enabled")),
        "dynamic_covariate_fields": list(xreg_meta.get("feature_names", [])),
        "price_covariate_fields": list(xreg_meta.get("price_feature_names", [])),
        "price_covariate_projection": str(xreg_meta.get("projection_method", "") or ""),
    }


def _build_forecast_cache_key(model_input: Dict[str, Any]) -> str:
    normalized = json.dumps(
        {
            "market": model_input.get("market"),
            "code": model_input.get("code"),
            "frequency": model_input.get("frequency"),
            "horizon_bars": model_input.get("horizon_bars"),
            "context_length": model_input.get("context_length"),
            "context_end": model_input.get("context_end"),
            "series_digest": model_input.get("series_digest"),
            "covariates": model_input.get("covariates"),
            "price_covariate_digest": model_input.get("price_covariate_digest", ""),
            "model_version": "timesfm_native_v4",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"{_TIMESFM_CACHE_PREFIX}{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"


def _load_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    try:
        payload = db.cache_get(cache_key)
    except Exception as exc:
        logger.warning("读取 TimesFM 缓存失败: %s", exc)
        return None
    if not payload:
        return None
    result = dict(payload)
    native_status = result.get("native_status") or {}
    native_enabled = bool(native_status.get("enabled"))
    backend = str(result.get("backend", "") or "")
    if backend == "timesfm_proxy":
        return None
    if not native_enabled and backend in {"timesfm_native", "timesfm_native_xreg", "timesfm_native_unavailable"}:
        runtime_status = get_timesfm_native_runtime_status()
        if runtime_status.get("available") and backend == "timesfm_native_unavailable":
            return None
    result["source"] = "timesfm_cache"
    return result


def _save_cache(cache_key: str, payload: Dict[str, Any]) -> None:
    try:
        db.cache_set(
            cache_key,
            payload,
            expire=int(time.time()) + _TIMESFM_CACHE_EXPIRE_SECONDS,
        )
    except Exception as exc:
        logger.warning("保存 TimesFM 缓存失败: %s", exc)


def _classify_confidence(dispersion_score: float, continuation_probability: float) -> str:
    if dispersion_score <= 0.35 and continuation_probability >= 0.68:
        return "high"
    if dispersion_score <= 0.7 and continuation_probability >= 0.56:
        return "medium"
    return "low"


def _classify_uncertainty(dispersion_score: float) -> str:
    if dispersion_score >= 0.85:
        return "high"
    if dispersion_score >= 0.45:
        return "medium"
    return "low"


def _classify_regime(momentum_score: float, dispersion_score: float) -> str:
    if dispersion_score >= 0.9:
        return "volatile"
    if abs(momentum_score) >= 1.3:
        return "trend_follow"
    if abs(momentum_score) <= 0.45:
        return "range"
    return "transition"


def _timesfm_predict_native(model_input: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        import numpy as np  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "reason": f"TimesFM 原生依赖不可用: {exc}",
        }

    try:
        model, backend_meta = _get_native_model()
    except Exception as exc:
        logger.warning("加载 TimesFM 原生模型失败: %s", exc)
        return {
            "available": False,
            "reason": f"TimesFM 原生模型不可用: {exc}",
        }

    series = [_safe_float(item) for item in model_input.get("series", [])]
    if len(series) < 10:
        return {
            "available": False,
            "reason": "TimesFM 原生推理需要至少 10 个上下文点",
        }

    horizon_bars = max(int(model_input.get("horizon_bars", 1) or 1), 1)
    context = np.asarray(series, dtype=np.float32)
    if not len(context):
        return {
            "available": False,
            "reason": "TimesFM 原生输入为空",
        }

    try:
        xreg_covariates = _build_native_xreg_covariates(model_input)
        xreg_used = False
        backend_meta = dict(backend_meta)
        try:
            if (
                xreg_covariates.get("enabled")
                and hasattr(model, "forecast_with_covariates")
                and importlib.util.find_spec("jax") is not None
            ):
                point_forecast, quantile_forecast = model.forecast_with_covariates(
                    inputs=[context],
                    dynamic_numerical_covariates=xreg_covariates["dynamic_numerical_covariates"],
                    static_numerical_covariates=xreg_covariates["static_numerical_covariates"],
                    static_categorical_covariates=xreg_covariates["static_categorical_covariates"],
                    xreg_mode="xreg + timesfm",
                    normalize_xreg_target_per_input=True,
                )
                xreg_used = True
            elif xreg_covariates.get("enabled"):
                raise RuntimeError("当前环境未安装 XReg 依赖 jax 或模型不支持协变量推理")
            else:
                point_forecast, quantile_forecast = model.forecast(horizon=horizon_bars, inputs=[context])
        except Exception as exc:
            backend_meta["xreg_reason"] = str(exc)
            point_forecast, quantile_forecast = model.forecast(horizon=horizon_bars, inputs=[context])

        point_array = np.asarray(_slice_forecast_tail(point_forecast, horizon_bars)).reshape(-1)
        quantile_array = np.asarray(_slice_forecast_tail(quantile_forecast, horizon_bars))
        quantile_prices = {
            "mean": [float(value) for value in np.asarray(quantile_array[:, 0]).reshape(-1)],
            "p10": [float(value) for value in np.asarray(quantile_array[:, 1]).reshape(-1)],
            "p50": [float(value) for value in np.asarray(quantile_array[:, 5]).reshape(-1)],
            "p90": [float(value) for value in np.asarray(quantile_array[:, 9]).reshape(-1)],
        }
        result = _build_native_result(
            model_input=model_input,
            point_prices=[float(value) for value in point_array],
            quantile_prices=quantile_prices,
            backend="timesfm_native_xreg" if xreg_used else "timesfm_native",
            backend_meta=backend_meta,
            xreg_used=xreg_used,
            xreg_meta=xreg_covariates,
        )
        if backend_meta.get("xreg_reason"):
            result["degrade_message"] = f"原生预测已启用，XReg 未生效: {backend_meta['xreg_reason']}"
        return result
    except Exception as exc:
        logger.warning("TimesFM 原生推理失败: %s", exc)
        return {
            "available": False,
            "reason": f"TimesFM 原生推理失败: {exc}",
        }


def _build_native_unavailable_result(model_input: Dict[str, Any], reason: str) -> Dict[str, Any]:
    series = model_input.get("series", []) or []
    latest_price = _safe_float(series[-1]) if series else 0.0
    frequency = _normalize_frequency(str(model_input.get("frequency", "5m") or "5m"))
    horizon_bars = max(_safe_int(model_input.get("horizon_bars"), 1), 1)
    horizon_meta = _build_horizon_meta(frequency, horizon_bars)
    message = reason or "TimesFM 原生模型不可用"
    return {
        "available": False,
        "backend": "timesfm_native_unavailable",
        "source": "timesfm_native_unavailable",
        "degraded": False,
        "degrade_message": "",
        "error_message": message,
        "market": model_input.get("market", ""),
        "code": model_input.get("code", ""),
        "frequency": frequency,
        "horizon_bars": horizon_bars,
        "horizon_minutes": horizon_meta["horizon_minutes"],
        "horizon_label": horizon_meta["horizon_label"],
        "frequency_label": horizon_meta["frequency_label"],
        "context_length": model_input.get("context_length", len(series)),
        "context_end": model_input.get("context_end", ""),
        "latest_price": round(latest_price, 6),
        "direction": "neutral",
        "expected_return_pct": 0.0,
        "expected_price": round(latest_price, 6),
        "point_forecast_pct_path": [],
        "point_forecast_price_path": [],
        "quantiles_pct": {"p10": 0.0, "p50": 0.0, "p90": 0.0},
        "quantile_forecast_pct_path": {"mean": [], "p10": [], "p50": [], "p90": []},
        "quantile_forecast_price_path": {"mean": [], "p10": [], "p50": [], "p90": []},
        "continuation_probability": 0.0,
        "reversal_risk": 0.0,
        "dispersion_score": 0.0,
        "forecast_confidence": "unavailable",
        "uncertainty_level": "high",
        "regime": "unavailable",
        "summary": f"原生 TimesFM 不可用，无法生成未来{horizon_meta['horizon_label']}预测。",
        "display_band": "--",
        "native_model": str(_TIMESFM_NATIVE_MODEL_META.get("model_name", "") or ""),
        "native_model_source": str(_TIMESFM_NATIVE_MODEL_META.get("module_source", "") or _TIMESFM_IMPORTED_META.get("module_source", "")),
        "native_module_file": str(_TIMESFM_NATIVE_MODEL_META.get("module_file", "") or _TIMESFM_IMPORTED_META.get("module_file", "")),
        "xreg_used": False,
        "target_series_field": "close",
        "event_covariates_used": False,
        "price_covariates_used": False,
        "dynamic_covariate_fields": [],
        "price_covariate_fields": [],
        "price_covariate_projection": "",
        "native_status": {
            "enabled": False,
            "backend": "timesfm_native_unavailable",
            "message": message,
        },
    }


def predict_timesfm(model_input: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
    cache_key = _build_forecast_cache_key(model_input)
    if use_cache:
        cached = _load_cache(cache_key)
        if cached:
            return cached

    native_result = _timesfm_predict_native(model_input)
    if native_result and native_result.get("available"):
        result = native_result
    else:
        result = _build_native_unavailable_result(model_input, (native_result or {}).get("reason", ""))
    if result.get("backend") in {"timesfm_native", "timesfm_native_xreg"}:
        result["native_status"] = {
            "enabled": True,
            "backend": result.get("backend"),
            "message": result.get("degrade_message", "") or "",
        }

    cache_payload = dict(result)
    cache_payload["source"] = cache_payload.get("source") or "timesfm_compute"
    _save_cache(cache_key, cache_payload)
    return dict(cache_payload)


def _build_news_bias_score(
    direct_news: Optional[List[Dict[str, Any]]] = None,
    driver_news: Optional[List[Dict[str, Any]]] = None,
) -> float:
    def score(items: Optional[List[Dict[str, Any]]]) -> float:
        total = 0.0
        for item in items or []:
            sign = 1.0 if item.get("impact_direction") == "bullish" else -1.0 if item.get("impact_direction") == "bearish" else 0.0
            total += sign * max(0.3, _safe_float(item.get("importance_score", 0.0), 0.0))
        return total

    return score(direct_news) * 0.75 + score(driver_news) * 0.35


def _build_cross_asset_bias(cross_asset_watch: Any) -> float:
    if isinstance(cross_asset_watch, dict):
        items = cross_asset_watch.get("items", [])
    elif isinstance(cross_asset_watch, list):
        items = cross_asset_watch
    else:
        items = []
    total = 0.0
    for item in items[:3]:
        aligned = item.get("alignment") == "aligned"
        if not aligned:
            continue
        direction = item.get("direction", "neutral")
        sign = 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else 0.0
        total += sign * max(0.2, _safe_float(item.get("change_30m_pct", 0.0)) / 100.0)
    return total


def _build_scenario_bias(scenario_route: Optional[Dict[str, Any]] = None) -> float:
    route = (scenario_route or {}).get("route", "")
    mapping = {
        "price_news_resonance": 0.35,
        "news_catalyst": 0.2,
        "cross_asset_propagation": 0.18,
        "historical_followthrough": 0.28,
        "price_dislocation": -0.08,
        "balanced_monitoring": 0.0,
    }
    return mapping.get(route, 0.0)


def build_timesfm_covariates(
    price_state: Optional[Dict[str, Any]] = None,
    direct_news: Optional[List[Dict[str, Any]]] = None,
    driver_news: Optional[List[Dict[str, Any]]] = None,
    cross_asset_watch: Optional[Any] = None,
    scenario_route: Optional[Dict[str, Any]] = None,
    pricing_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    price_state = price_state or {}
    pricing_summary = pricing_summary or {}
    price_bias = (_safe_float(price_state.get("change_30m_pct")) / 100.0) * 0.6
    future_bias_text = str(pricing_summary.get("future_bias", "") or "")
    if "上行" in future_bias_text:
        price_bias += 0.0006
    elif "下行" in future_bias_text:
        price_bias -= 0.0006

    return {
        "use_event_covariates": True,
        "use_price_covariates": True,
        "news_bias_score": round(_build_news_bias_score(direct_news, driver_news), 6),
        "cross_asset_bias": round(_build_cross_asset_bias(cross_asset_watch), 6),
        "scenario_bias": round(_build_scenario_bias(scenario_route), 6),
        "price_bias": round(price_bias, 6),
        "direct_news_count": len(direct_news or []),
        "driver_news_count": len(driver_news or []),
        "route": (scenario_route or {}).get("route", ""),
    }


def generate_timesfm_forecast_bundle(
    price_bars: List[Dict[str, Any]],
    market: str,
    code: str,
    frequency: str = "5m",
    horizons: Optional[List[int]] = None,
    context_length: int = 120,
    covariates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not price_bars:
        return {
            "available": False,
            "backend": "timesfm_proxy",
            "degraded": True,
            "degrade_message": "缺少价格数据，无法生成 TimesFM 预测",
            "summary": "价格数据不足，暂无法生成预测。",
        }

    normalized_frequency = _normalize_frequency(frequency)
    horizons = horizons or [1, 4]
    forecasts: Dict[str, Dict[str, Any]] = {}
    summaries: List[str] = []
    for horizon_bars in horizons:
        model_input = build_timesfm_input(
            price_bars=price_bars,
            market=market,
            code=code,
            frequency=normalized_frequency,
            horizon_bars=horizon_bars,
            context_length=context_length,
            covariates=covariates,
        )
        forecast = predict_timesfm(model_input)
        forecasts[str(horizon_bars)] = forecast
        summaries.append(forecast.get("summary", ""))

    first = forecasts[str(horizons[0])] if horizons else {}
    second = forecasts[str(horizons[1])] if len(horizons) > 1 else first
    summary = "；".join(item for item in [first.get("summary", ""), second.get("summary", "")] if item)
    return {
        "available": all(item.get("available") for item in forecasts.values()),
        "backend": first.get("backend", "timesfm_proxy"),
        "source": first.get("source", "timesfm_proxy"),
        "degraded": any(item.get("degraded") for item in forecasts.values()),
        "degrade_message": first.get("degrade_message", ""),
        "frequency": normalized_frequency,
        "frequency_label": _frequency_label(normalized_frequency),
        "context_length": first.get("context_length", 0),
        "context_end": first.get("context_end", ""),
        "summary": summary,
        "forecast_primary": first,
        "forecast_secondary": second,
        "forecast_30m": first,
        "forecast_120m": second,
        "forecast_labels": {
            "primary": first.get("horizon_label", ""),
            "secondary": second.get("horizon_label", ""),
        },
        "backend_details": {
            "native_model": first.get("native_model", ""),
            "native_model_source": first.get("native_model_source", ""),
            "native_module_file": first.get("native_module_file", ""),
            "xreg_used": bool(first.get("xreg_used")),
            "target_series_field": first.get("target_series_field", "close"),
            "event_covariates_used": bool(first.get("event_covariates_used")),
            "price_covariates_used": bool(first.get("price_covariates_used")),
            "dynamic_covariate_fields": list(first.get("dynamic_covariate_fields", []) or []),
            "price_covariate_fields": list(first.get("price_covariate_fields", []) or []),
            "price_covariate_projection": first.get("price_covariate_projection", ""),
            "native_enabled": bool((first.get("native_status") or {}).get("enabled")),
            "native_backend": (first.get("native_status") or {}).get("backend", ""),
            "native_message": (first.get("native_status") or {}).get("message", ""),
        },
        "by_horizon": forecasts,
    }


def build_event_forecast(
    price_bars: List[Dict[str, Any]],
    market: str,
    code: str,
    frequency: str,
    event_time: Any,
    actual_follow_primary_pct: Optional[float] = None,
    actual_follow_secondary_pct: Optional[float] = None,
    primary_horizon_bars: int = 1,
    secondary_horizon_bars: int = 4,
    actual_follow_30m_pct: Optional[float] = None,
    actual_follow_120m_pct: Optional[float] = None,
    covariates: Optional[Dict[str, Any]] = None,
    context_length: Optional[int] = None,
) -> Dict[str, Any]:
    event_time_text = _serialize_datetime(event_time)
    context_bars = [bar for bar in price_bars if _bar_dt(bar) <= event_time_text]
    if len(context_bars) < 10:
        return {
            "available": False,
            "summary": "事件前价格上下文不足，无法生成反事实预测。",
            "event_time": event_time_text,
        }
    bundle = generate_timesfm_forecast_bundle(
        price_bars=context_bars,
        market=market,
        code=code,
        frequency=frequency,
        horizons=[primary_horizon_bars, secondary_horizon_bars],
        context_length=max(10, min(int(context_length or 120), len(context_bars))),
        covariates=covariates,
    )
    if not bundle.get("available"):
        failure_message = str(
            bundle.get("error_message")
            or ((bundle.get("backend_details") or {}).get("native_message"))
            or bundle.get("summary")
            or "原生 TimesFM 不可用，无法生成反事实预测。"
        ).strip()
        return {
            **bundle,
            "available": False,
            "event_time": event_time_text,
            "error_message": failure_message,
            "summary": failure_message,
        }
    forecast_primary = bundle.get("forecast_primary", {}) or bundle.get("forecast_30m", {})
    forecast_secondary = bundle.get("forecast_secondary", {}) or bundle.get("forecast_120m", {})
    primary_label = forecast_primary.get("horizon_label", "下一周期")
    secondary_label = forecast_secondary.get("horizon_label", "4周期")
    actual_primary = _safe_float(actual_follow_primary_pct if actual_follow_primary_pct is not None else actual_follow_30m_pct)
    actual_secondary = _safe_float(actual_follow_secondary_pct if actual_follow_secondary_pct is not None else actual_follow_120m_pct)
    expected_primary = _safe_float(forecast_primary.get("expected_return_pct"))
    expected_secondary = _safe_float(forecast_secondary.get("expected_return_pct"))
    surprise_score = abs(actual_secondary - expected_secondary) + abs(actual_primary - expected_primary) * 0.6
    return {
        **bundle,
        "event_time": event_time_text,
        "primary_label": primary_label,
        "secondary_label": secondary_label,
        "actual_follow_primary_pct": round(actual_primary, 4),
        "actual_follow_secondary_pct": round(actual_secondary, 4),
        "forecast_error_primary_pct": round(actual_primary - expected_primary, 4),
        "forecast_error_secondary_pct": round(actual_secondary - expected_secondary, 4),
        "actual_follow_30m_pct": round(actual_primary, 4),
        "actual_follow_120m_pct": round(actual_secondary, 4),
        "forecast_error_30m_pct": round(actual_primary - expected_primary, 4),
        "forecast_error_120m_pct": round(actual_secondary - expected_secondary, 4),
        "surprise_score": round(surprise_score, 4),
        "summary": (
            f"事件后{primary_label}实际{actual_primary:+.3f}% / 预测{expected_primary:+.3f}% ，"
            f"{secondary_label}实际{actual_secondary:+.3f}% / 预测{expected_secondary:+.3f}% 。"
        ),
    }


def build_forecast_risk_overlay(bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    bundle = bundle or {}
    forecast_primary = bundle.get("forecast_primary", {}) or bundle.get("forecast_30m", {}) or {}
    forecast_secondary = bundle.get("forecast_secondary", {}) or bundle.get("forecast_120m", {}) or {}
    primary_label = forecast_primary.get("horizon_label", "下一周期")
    secondary_label = forecast_secondary.get("horizon_label", "4周期")
    uncertainty = forecast_primary.get("uncertainty_level") or forecast_secondary.get("uncertainty_level") or "medium"
    level = "high" if uncertainty == "high" else "medium" if uncertainty == "medium" else "low"
    focus_points: List[str] = []
    invalidations: List[str] = []

    if forecast_primary.get("dispersion_score", 0) >= 0.85:
        focus_points.append(f"{primary_label}区间较宽，优先等待第二信号确认")
        invalidations.append("预测分歧继续扩大")
    if forecast_secondary.get("reversal_risk", 0) >= 0.45:
        focus_points.append(f"{secondary_label}反转风险偏高，不宜把短线方向直接外推")
        invalidations.append(f"{secondary_label}反转风险抬升")
    if forecast_primary.get("direction") == "neutral":
        focus_points.append(f"{primary_label}中位路径不明确，适合轻仓或只观察")

    summary = (
        f"TimesFM 预测显示{primary_label}{forecast_primary.get('direction', 'neutral')}、"
        f"{primary_label}延续概率{round(_safe_float(forecast_primary.get('continuation_probability')) * 100)}%，"
        f"当前不确定性为{uncertainty}。"
    )
    return {
        "level": level,
        "summary": summary,
        "focus_points": focus_points[:3],
        "invalidations": invalidations[:3],
    }
