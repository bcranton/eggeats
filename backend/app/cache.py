"""
Simple server-side in-memory TTL cache using cachetools.

This sits in front of expensive DB queries on public endpoints so that
concurrent users share one query result rather than each triggering their own.

Example: 500 simultaneous page loads → 1 DB query, not 500.

The cache lives in process memory, so it resets on deploy/restart (fine — the
DB is the source of truth). No Redis needed for this traffic level.

TTL is set to 5 minutes to match the browser Cache-Control headers, so
both layers stay in sync.
"""
import threading
from cachetools import TTLCache

# 5-minute TTL, max 256 cached entries (more than enough for our endpoints)
CACHE_TTL = 300
_cache: TTLCache = TTLCache(maxsize=256, ttl=CACHE_TTL)
_lock = threading.Lock()


def cache_get(key: str):
    with _lock:
        return _cache.get(key)


def cache_set(key: str, value) -> None:
    with _lock:
        _cache[key] = value


def cache_invalidate_prefix(prefix: str) -> None:
    """Removes all keys that start with the given prefix."""
    with _lock:
        keys_to_delete = [k for k in list(_cache.keys()) if k.startswith(prefix)]
        for k in keys_to_delete:
            del _cache[k]


def cache_clear() -> None:
    with _lock:
        _cache.clear()
