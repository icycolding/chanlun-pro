import hashlib
import json
from collections import OrderedDict
from typing import Any


class TTLCache:
    def __init__(self, max_entries: int = 64):
        self.max_entries = max(1, int(max_entries))
        self._store: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str, now: float) -> Any | None:
        self._prune(now)
        entry = self._store.get(key)
        if entry is None:
            return None
        if float(entry["expires_at"]) <= float(now):
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return entry["value"]

    def set(self, key: str, value: Any, ttl_seconds: float, now: float) -> None:
        self._prune(now)
        expires_at = float(now) + max(0.0, float(ttl_seconds))
        self._store[key] = {"value": value, "expires_at": expires_at}
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def _prune(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._store.items() if float(entry["expires_at"]) <= float(now)
        ]
        for key in expired_keys:
            self._store.pop(key, None)


def build_tv_history_cache_key(
    symbol: str, resolution: str, config_payload: dict[str, Any]
) -> str:
    payload = {
        "symbol": str(symbol or "").strip(),
        "resolution": str(resolution or "").strip(),
        "config": config_payload or {},
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(serialized.encode("utf-8")).hexdigest()
    return f"tv-history:{digest}"
