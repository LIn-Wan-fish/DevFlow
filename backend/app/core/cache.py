"""跨进程共享的缓存与锁。

**为什么需要**:多副本部署时,任何「进程内记住的东西」都会退化成「每个副本各记一份」。
本项目里真正受影响的只有两处 —— GitHub 的 ETag 缓存,以及周报调度器,
但它们的症状很不一样:前者只是命中率下降(不致命),后者是**每个副本都跑一遍调度**
(白烧模型调用)。所以缓存和锁放在同一个抽象里。

**诚实降级**:没配 `REDIS_URL` 时退回进程内实现,并在启动时明确警告
「当前是单进程模式,多副本下会重复执行」—— 而不是假装分布式可用。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class Cache(Protocol):
    """缓存与锁。两个实现:Redis(跨进程)与进程内(单机)。"""

    name: str

    async def get_json(self, key: str) -> Any | None: ...

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None: ...

    async def acquire_lock(self, name: str, ttl: int) -> bool: ...

    async def release_lock(self, name: str) -> None: ...

    async def healthy(self) -> bool: ...


class MemoryCache:
    """进程内实现。**只在单副本下正确** —— 多副本会各存一份、各跑一遍。"""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[float | None, str]] = {}
        self._locks: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return False
        expires_at, _ = entry
        if expires_at is not None and expires_at < time.time():
            self._data.pop(key, None)
            return False
        return True

    async def get_json(self, key: str) -> Any | None:
        if not self._alive(key):
            return None
        return json.loads(self._data[key][1])

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + ttl if ttl else None
        self._data[key] = (expires_at, json.dumps(value))

    async def acquire_lock(self, name: str, ttl: int) -> bool:
        now = time.time()
        held = self._locks.get(name)
        if held is not None and held > now:
            return False
        self._locks[name] = now + ttl
        return True

    async def release_lock(self, name: str) -> None:
        self._locks.pop(name, None)

    async def healthy(self) -> bool:
        return True


class RedisCache:
    """Redis 实现。多副本下唯一正确的那一个。"""

    name = "redis"

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        # decode_responses=True:直接用 str 存取,省掉到处 encode/decode
        self._client = aioredis.from_url(url, decode_responses=True)

    async def get_json(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._client.set(key, json.dumps(value), ex=ttl)

    async def acquire_lock(self, name: str, ttl: int) -> bool:
        """SET NX EX —— 一条命令完成「不存在才写入并带过期」,天然原子。

        **必须带过期时间**:持锁进程被 kill 时,锁要能自己过期,
        否则周报调度会永久停摆(比重复执行更糟)。
        """
        return bool(await self._client.set(f"lock:{name}", "1", nx=True, ex=ttl))

    async def release_lock(self, name: str) -> None:
        await self._client.delete(f"lock:{name}")

    async def healthy(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception:  # noqa: BLE001
            return False


_cache: Cache | None = None


def get_cache() -> Cache:
    """拿到缓存实例(进程内单例)。

    没配 REDIS_URL 就退回进程内 —— **并且每次都只是警告,不抛异常**:
    单机跑 Demo 本来就该能起来,不能因为没装 Redis 就崩。
    """
    global _cache
    if _cache is None:
        if settings.redis_url:
            _cache = RedisCache(settings.redis_url)
            logger.info("缓存后端:Redis(%s)", settings.redis_url)
        else:
            _cache = MemoryCache()
            logger.warning(
                "未配置 REDIS_URL,缓存与调度锁退回**进程内**实现 —— "
                "单副本没问题,多副本下周报调度会在每个副本各跑一遍。"
            )
    return _cache


def reset_cache() -> None:
    """单测用:换掉全局实例。"""
    global _cache
    _cache = None