"""
Redis Store — short-term memory and caching layer.

Provides JSON-safe get/set, pub/sub, and key prefix scanning.
Gracefully degrades to in-memory dict if Redis is unavailable.
"""
import json
from typing import Any, Optional

try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class RedisStore:
    """
    Redis wrapper with JSON serialisation and graceful fallback.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._fallback: dict[str, str] = {}
        self._client: Optional[object] = None

        if _REDIS_AVAILABLE:
            try:
                self._client = redis.from_url(redis_url, decode_responses=True)
                self._client.ping()
            except Exception:
                self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    def set_json(self, key: str, value: Any, ttl: int = 0):
        """Set a JSON-serialisable value. ttl=0 means no expiry."""
        data = json.dumps(value, default=str)
        if self._client:
            try:
                if ttl > 0:
                    self._client.setex(key, ttl, data)
                else:
                    self._client.set(key, data)
                return
            except Exception:
                pass
        self._fallback[key] = data

    def get_json(self, key: str) -> Optional[Any]:
        """Get and deserialise a JSON value."""
        raw = None
        if self._client:
            try:
                raw = self._client.get(key)
            except Exception:
                pass
        if raw is None:
            raw = self._fallback.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def delete(self, key: str):
        if self._client:
            try:
                self._client.delete(key)
                return
            except Exception:
                pass
        self._fallback.pop(key, None)

    def get_by_prefix(self, prefix: str) -> dict:
        """Scan keys by prefix and return {short_key: value} dict."""
        result = {}
        if self._client:
            try:
                for key in self._client.scan_iter(match=f"{prefix}*", count=100):
                    short = key[len(prefix):]
                    val = self.get_json(key)
                    if val is not None:
                        result[short] = val
                return result
            except Exception:
                pass
        # Fallback
        for key, val in self._fallback.items():
            if key.startswith(prefix):
                short = key[len(prefix):]
                try:
                    result[short] = json.loads(val)
                except json.JSONDecodeError:
                    result[short] = val
        return result

    def publish(self, channel: str, event: dict):
        """Publish event to Redis pub/sub channel."""
        if self._client:
            try:
                self._client.publish(channel, json.dumps(event, default=str))
            except Exception:
                pass

    def health_check(self) -> dict:
        if self._client:
            try:
                self._client.ping()
                return {"status": "ok", "backend": "redis"}
            except Exception as e:
                return {"status": "degraded", "backend": "memory", "error": str(e)}
        return {"status": "degraded", "backend": "memory"}
