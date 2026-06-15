from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.tv_history_cache import TTLCache, build_tv_history_cache_key


def test_build_tv_history_cache_key_is_stable_for_same_payload():
    key1 = build_tv_history_cache_key(
        symbol="a:688498",
        resolution="D",
        config_payload={
            "cl_config": {"enable_kchart_low_to_high": "1", "kline_type": "kline_default"},
            "frequency_low": "30m",
            "kchart_to_frequency": "d",
        },
    )
    key2 = build_tv_history_cache_key(
        symbol="a:688498",
        resolution="D",
        config_payload={
            "kchart_to_frequency": "d",
            "frequency_low": "30m",
            "cl_config": {"kline_type": "kline_default", "enable_kchart_low_to_high": "1"},
        },
    )

    assert key1 == key2


def test_build_tv_history_cache_key_changes_when_config_changes():
    key1 = build_tv_history_cache_key(
        symbol="a:688498",
        resolution="D",
        config_payload={"cl_config": {"enable_kchart_low_to_high": "1"}},
    )
    key2 = build_tv_history_cache_key(
        symbol="a:688498",
        resolution="D",
        config_payload={"cl_config": {"enable_kchart_low_to_high": "0"}},
    )

    assert key1 != key2


def test_ttl_cache_returns_value_before_expiry_and_expires_after_ttl():
    cache = TTLCache(max_entries=4)
    cache.set("foo", {"ok": True}, ttl_seconds=5, now=100.0)

    assert cache.get("foo", now=104.0) == {"ok": True}
    assert cache.get("foo", now=106.0) is None


def test_ttl_cache_prunes_oldest_entries_when_capacity_exceeded():
    cache = TTLCache(max_entries=2)
    cache.set("a", 1, ttl_seconds=10, now=1.0)
    cache.set("b", 2, ttl_seconds=10, now=2.0)
    cache.set("c", 3, ttl_seconds=10, now=3.0)

    assert cache.get("a", now=3.5) is None
    assert cache.get("b", now=3.5) == 2
    assert cache.get("c", now=3.5) == 3
