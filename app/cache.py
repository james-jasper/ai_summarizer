import redis.asyncio as aioredis
import os
from dotenv import load_dotenv

load_dotenv()

_redis: aioredis.Redis | None = None

CACHE_TTL = 60 * 60 * 24  # 24 hours


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    return _redis


async def get_cached_summary(content_hash: str) -> str | None:
    r = get_redis()
    value = await r.get(f"summary:{content_hash}")
    return value.decode() if value else None


async def set_cached_summary(content_hash: str, summary: str) -> None:
    r = get_redis()
    await r.set(f"summary:{content_hash}", summary, ex=CACHE_TTL)
