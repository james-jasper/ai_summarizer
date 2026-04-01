import asyncio
import time
import aio_pika
import os
from dotenv import load_dotenv

from app.database import (
    get_pool,
    get_job_input,
    update_job_processing,
    update_job_completed,
    update_job_failed,
)
from app.cache import get_cached_summary, set_cached_summary
from app.summarizer import fetch_url_content, summarize_text
from app.logger import get_logger

load_dotenv()

log = get_logger("worker")

QUEUE_NAME = os.getenv("QUEUE_NAME", "summarizer_jobs")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")


async def process_job(job_id: str) -> None:
    log.info(f"Picked up job {job_id}")

    row = await get_job_input(job_id)
    if not row:
        log.warning(f"Job {job_id} not found in DB — skipping")
        return

    input_type = row["input_type"]
    input_data = row["input_data"]
    log.info(f"Job {job_id} | type={input_type} | input={input_data[:80]!r}")

    await update_job_processing(job_id)
    start = time.monotonic()

    try:
        if input_type == "url":
            log.debug(f"Job {job_id} | fetching URL: {input_data}")
            text = await fetch_url_content(input_data)
            log.debug(f"Job {job_id} | fetched {len(text)} chars")
        else:
            text = input_data
            log.debug(f"Job {job_id} | raw text {len(text)} chars")

        log.debug(f"Job {job_id} | sending to Ollama...")
        summary = await summarize_text(text)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        await update_job_completed(job_id, summary, elapsed_ms)

        pool = await get_pool()
        async with pool.acquire() as conn:
            row2 = await conn.fetchrow("SELECT content_hash FROM jobs WHERE id=$1", job_id)
            if row2 and row2["content_hash"]:
                await set_cached_summary(row2["content_hash"], summary)
                log.debug(f"Job {job_id} | cached in Redis")

        log.info(f"Job {job_id} | COMPLETED in {elapsed_ms}ms")

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.exception(f"Job {job_id} | FAILED after {elapsed_ms}ms — {e}")
        await update_job_failed(job_id, str(e))


async def main():
    await get_pool()

    log.info(f"Connecting to RabbitMQ at {RABBITMQ_URL}")
    for attempt in range(1, 11):
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            break
        except Exception as e:
            log.warning(f"RabbitMQ not ready (attempt {attempt}/10): {e}")
            if attempt == 10:
                raise
            await asyncio.sleep(3)


    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)

        log.info(f"Waiting for jobs on queue '{QUEUE_NAME}'...")

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    job_id = message.body.decode()
                    await process_job(job_id)


if __name__ == "__main__":
    asyncio.run(main())
