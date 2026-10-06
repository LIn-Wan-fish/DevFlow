"""跨进程缓存与调度锁。"""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.core import cache as cache_module
from app.core.cache import MemoryCache, RedisCache, get_cache
from app.reports import scheduler


@pytest.fixture(autouse=True)
def _reset():
    cache_module.reset_cache()
    yield
    cache_module.reset_cache()


# --------------------------------------------------------------------------- 基本行为


async def test_读写与过期():
    c = MemoryCache()
    await c.set_json("k", {"a": 1})
    assert await c.get_json("k") == {"a": 1}
    assert await c.get_json("nope") is None

    await c.set_json("short", "v", ttl=1)
    assert await c.get_json("short") == "v"
    await asyncio.sleep(1.1)
    assert await c.get_json("short") is None, "过期后必须读不到"


async def test_锁是互斥的():
    c = MemoryCache()
    assert await c.acquire_lock("L", ttl=60) is True
    assert await c.acquire_lock("L", ttl=60) is False, "同一把锁第二次必须抢不到"
    await c.release_lock("L")
    assert await c.acquire_lock("L", ttl=60) is True, "释放后应该能再抢到"


async def test_锁会自己过期():
    """持锁进程被 kill 时锁必须能自己过期 —— 否则调度永久停摆,比重复执行更糟。"""
    c = MemoryCache()
    assert await c.acquire_lock("L", ttl=1) is True
    await asyncio.sleep(1.1)
    assert await c.acquire_lock("L", ttl=1) is True, "过期后别人应该能接手"


def test_没配_redis_时退回进程内实现(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "")
    assert isinstance(get_cache(), MemoryCache)


def test_配了_redis_时用_redis_实现(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:6379/0")
    assert isinstance(get_cache(), RedisCache)


def test_拿到的实例是同一个():
    assert get_cache() is get_cache()


# --------------------------------------------------------------------------- 调度锁


async def test_别的副本持锁时本轮跳过(monkeypatch):
    """回归:没有锁的话,3 个副本会各自判定「该出周报了」,把模型调用重复烧一遍。"""
    calls: list[int] = []
    monkeypatch.setattr(scheduler, "check_once", lambda *a, **k: calls.append(1) or 0)

    shared = MemoryCache()
    await shared.acquire_lock(scheduler.LOCK_NAME, ttl=60)   # 模拟别的副本正持有
    monkeypatch.setattr(scheduler, "get_cache", lambda: shared)
    monkeypatch.setattr(settings, "weekly_report_check_seconds", 1)

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run(stop))
    await asyncio.sleep(0.3)
    stop.set()
    await task

    assert calls == [], "锁在别人手里时,本副本不该执行检查"


async def test_没有竞争时正常执行(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(scheduler, "check_once", lambda *a, **k: calls.append(1) or 0)
    monkeypatch.setattr(scheduler, "get_cache", MemoryCache)
    monkeypatch.setattr(settings, "weekly_report_check_seconds", 1)

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run(stop))
    await asyncio.sleep(0.3)
    stop.set()
    await task

    assert calls, "没人持锁时应当执行检查"


async def test_执行完会释放锁(monkeypatch):
    """只查一次就放锁,让下一个周期的副本有机会接手。"""
    monkeypatch.setattr(scheduler, "check_once", lambda *a, **k: 0)
    shared = MemoryCache()
    monkeypatch.setattr(scheduler, "get_cache", lambda: shared)
    monkeypatch.setattr(settings, "weekly_report_check_seconds", 1)

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run(stop))
    await asyncio.sleep(0.2)
    # 此刻锁应当已经被释放,别的副本能抢到
    assert await shared.acquire_lock(scheduler.LOCK_NAME, ttl=60) is True
    stop.set()
    await task


async def test_检查抛异常也要放锁(monkeypatch):
    """否则一次异常会让调度永久停摆。"""
    def boom(*_a, **_k):
        raise RuntimeError("模拟检查失败")

    monkeypatch.setattr(scheduler, "check_once", boom)
    shared = MemoryCache()
    monkeypatch.setattr(scheduler, "get_cache", lambda: shared)
    monkeypatch.setattr(settings, "weekly_report_check_seconds", 1)

    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run(stop))
    await asyncio.sleep(0.3)
    stop.set()
    await task

    assert await shared.acquire_lock(scheduler.LOCK_NAME, ttl=60) is True, "异常后锁必须被释放"


# --------------------------------------------------------------------------- 真 Redis


async def test_真_redis_可用时行为一致():
    """容器里 redis 服务是起着的,直接打一遍真实现,别只测假的。"""
    real = RedisCache("redis://redis:6379/0")
    if not await real.healthy():
        pytest.skip("当前环境没有可用的 Redis")

    await real.set_json("test:key", {"n": 1}, ttl=30)
    assert await real.get_json("test:key") == {"n": 1}
    assert await real.acquire_lock("test:lock", ttl=30) is True
    assert await real.acquire_lock("test:lock", ttl=30) is False
    await real.release_lock("test:lock")
    assert await real.acquire_lock("test:lock", ttl=30) is True
    await real.release_lock("test:lock")


async def test_两个_redis_客户端共享数据():
    """这条才是多副本的本质:不同进程看到同一份缓存。"""
    a = RedisCache("redis://redis:6379/0")
    if not await a.healthy():
        pytest.skip("当前环境没有可用的 Redis")
    b = RedisCache("redis://redis:6379/0")

    await a.set_json("test:shared", {"from": "a"}, ttl=30)
    assert await b.get_json("test:shared") == {"from": "a"}, "另一个客户端必须看得到"

    assert await a.acquire_lock("test:cross", ttl=30) is True
    assert await b.acquire_lock("test:cross", ttl=30) is False, "跨客户端也要互斥"
    await a.release_lock("test:cross")
