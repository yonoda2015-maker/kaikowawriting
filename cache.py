"""
シンプルなTTLキャッシュ。
- RSSフィード取得結果のキャッシュ（5分）
- スタイル分析結果のキャッシュ（DB保存で永続化）
スレッドセーフ（threading.Lock使用）。
"""
import time
import threading
from typing import Any
from logger_config import logger


class TTLCache:
    """TTL付きのインメモリキャッシュ。"""

    def __init__(self, default_ttl: int = 300) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                logger.debug(f"Cache expired: {key}")
                return None
            logger.debug(f"Cache hit: {key}")
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._store[key] = (value, time.time() + ttl)
            logger.debug(f"Cache set: {key} (TTL={ttl}s)")

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            logger.info("Cache cleared")

    def size(self) -> int:
        with self._lock:
            return len(self._store)


# グローバルキャッシュインスタンス
rss_cache    = TTLCache(default_ttl=300)   # RSS: 5分
style_cache  = TTLCache(default_ttl=3600)  # スタイル分析: 1時間
trend_cache  = TTLCache(default_ttl=600)   # トレンド: 10分
