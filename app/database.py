import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'queued',
    input_type      TEXT NOT NULL,
    input_data      TEXT NOT NULL,
    content_hash    TEXT,
    summary         TEXT,
    error           TEXT,
    cached          BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    processing_time_ms BIGINT
);
"""


async def get_pool() -> asyncpg.Pool:
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"), min_size=2, max_size=10)
            async with _pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def insert_job(job_id: str, input_type: str, input_data: str, content_hash: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs (id, status, input_type, input_data, content_hash)
            VALUES ($1, 'queued', $2, $3, $4)
            """,
            job_id, input_type, input_data, content_hash,
        )


async def insert_cached_job(
    job_id: str, input_type: str, input_data: str, content_hash: str, summary: str
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs (id, status, input_type, input_data, content_hash, summary, cached, processing_time_ms)
            VALUES ($1, 'completed', $2, $3, $4, $5, TRUE, 0)
            """,
            job_id, input_type, input_data, content_hash, summary,
        )


async def get_job_status(job_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, status, created_at FROM jobs WHERE id = $1", job_id
        )


async def get_job_result(job_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, input_type, input_data, summary, cached, processing_time_ms, error FROM jobs WHERE id = $1",
            job_id,
        )


async def update_job_processing(job_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET status='processing', updated_at=now() WHERE id=$1", job_id
        )


async def update_job_completed(job_id: str, summary: str, processing_time_ms: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET status='completed', summary=$2, processing_time_ms=$3, updated_at=now()
            WHERE id=$1
            """,
            job_id, summary, processing_time_ms,
        )


async def update_job_failed(job_id: str, error: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET status='failed', error=$2, updated_at=now() WHERE id=$1",
            job_id, error,
        )


async def get_job_input(job_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT input_type, input_data FROM jobs WHERE id=$1", job_id
        )
