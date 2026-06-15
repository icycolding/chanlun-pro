from __future__ import annotations

from typing import Any, Mapping


_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_lite_chart_request(args: Mapping[str, Any]) -> bool:
    value = str(args.get("lite_chart", "") or "").strip().lower()
    return value in _TRUE_VALUES


def apply_lite_chart_config_override(
    cl_config: Mapping[str, Any], lite_chart: bool
) -> dict[str, Any]:
    normalized = dict(cl_config or {})
    if not lite_chart:
        return normalized

    normalized["enable_kchart_low_to_high"] = "0"
    return normalized
