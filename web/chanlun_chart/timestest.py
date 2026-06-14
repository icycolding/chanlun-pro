import importlib
import math
import os
import sys
from pathlib import Path

import numpy as np
import torch


def _candidate_timesfm_src_paths():
    candidates = []
    for path in [
        os.getenv("TIMESFM_LOCAL_SRC_PATH", "").strip(),
        "/Users/jiming/Documents/GitHub/timesfm/src",
        str(Path(__file__).resolve().parents[3] / "timesfm" / "src"),
    ]:
        if path and Path(path).is_dir() and path not in candidates:
            candidates.append(path)
    return candidates


def _import_timesfm():
    errors = []
    for candidate in _candidate_timesfm_src_paths() + [None]:
        try:
            if candidate and candidate not in sys.path:
                sys.path.insert(0, candidate)
            sys.modules.pop("timesfm", None)
            module = importlib.import_module("timesfm")
            module_file = str(getattr(module, "__file__", "") or "")
            if candidate and module_file and not module_file.startswith(candidate):
                raise RuntimeError(f"已加载到非预期 TimesFM 模块: {module_file}")
            if not hasattr(module, "TimesFM_2p5_200M_torch"):
                raise RuntimeError(f"当前 TimesFM 缺少 TimesFM_2p5_200M_torch: {module_file}")
            return module
        except Exception as exc:
            errors.append(f"{candidate or 'site_package'}: {exc}")
    raise RuntimeError(" ; ".join(errors))


timesfm = _import_timesfm()


def _ensure_scaled_dot_product_attention_compat():
    functional = torch.nn.functional
    if hasattr(functional, "scaled_dot_product_attention"):
        return

    def _compat_scaled_dot_product_attention(
        query,
        key,
        value,
        attn_mask=None,
        dropout_p=0.0,
        is_causal=False,
        scale=None,
        enable_gqa=False,
    ):
        if enable_gqa:
            raise RuntimeError("当前 PyTorch 兼容实现暂不支持 enable_gqa")
        scale_factor = float(scale) if scale is not None else 1.0 / math.sqrt(max(int(query.shape[-1]), 1))
        if is_causal:
            q_len = int(query.shape[-2])
            k_len = int(key.shape[-2])
            causal_mask = torch.tril(torch.ones((q_len, k_len), dtype=torch.bool, device=query.device))
            if attn_mask is None:
                attn_mask = causal_mask
            elif getattr(attn_mask, "dtype", None) == torch.bool:
                attn_mask = torch.logical_and(attn_mask, causal_mask)
            else:
                causal_bias = torch.zeros((q_len, k_len), dtype=query.dtype, device=query.device)
                causal_bias = causal_bias.masked_fill(torch.logical_not(causal_mask), float("-inf"))
                attn_mask = attn_mask + causal_bias
        scores = torch.matmul(query, key.transpose(-2, -1)) * scale_factor
        if attn_mask is not None and getattr(attn_mask, "dtype", None) == torch.bool:
            score_bias = torch.zeros_like(scores, dtype=query.dtype)
            score_bias = score_bias.masked_fill(torch.logical_not(attn_mask), float("-inf"))
            scores = scores + score_bias
        elif attn_mask is not None:
            scores = scores + attn_mask
        weights = torch.softmax(scores, dim=-1)
        if dropout_p and float(dropout_p) > 0:
            weights = functional.dropout(weights, p=float(dropout_p), training=True)
        return torch.matmul(weights, value)

    functional.scaled_dot_product_attention = _compat_scaled_dot_product_attention


torch.set_float32_matmul_precision("high")
_ensure_scaled_dot_product_attention_compat()

model = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")

model.compile(
    timesfm.ForecastConfig(
        max_context=1024,
        max_horizon=256,
        normalize_inputs=True,
        use_continuous_quantile_head=True,
        force_flip_invariance=True,
        infer_is_positive=True,
        fix_quantile_crossing=True,
    )
)
point_forecast, quantile_forecast = model.forecast(
    horizon=12,
    inputs=[
        np.linspace(0, 1, 100),
        np.sin(np.linspace(0, 20, 67)),
    ],  # Two dummy inputs
)
print("timesfm_file=", timesfm.__file__)
print("point_shape=", point_forecast.shape)
print("quantile_shape=", quantile_forecast.shape)
