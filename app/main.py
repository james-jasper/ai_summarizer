import hashlib
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.cache import get_cached_summary
from app.database import (
    close_pool,
    get_job_result,
    get_job_status,
    get_pool,
    insert_cached_job,
    insert_job,
)
from app.models import ResultResponse, StatusResponse, SubmitRequest, SubmitResponse
from app.queue import publish_job
from app.logger import get_logger

log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up — initialising DB pool")
    await get_pool()
    yield
    log.info("Shutting down — closing DB pool")
    await close_pool()


app = FastAPI(title="Async Content Summarizer", lifespan=lifespan)


def _hash_content(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@app.post("/submit", response_model=SubmitResponse, status_code=202)
async def submit(request: SubmitRequest):
    input_type = "url" if request.url else "text"
    input_data = request.url or request.text
    content_hash = _hash_content(input_data)
    job_id = str(uuid.uuid4())

    log.info(f"Submit request | job_id={job_id} | type={input_type} | input={input_data[:80]!r}")

    cached_summary = await get_cached_summary(content_hash)
    if cached_summary:
        log.info(f"Cache HIT | job_id={job_id} | hash={content_hash[:12]}")
        await insert_cached_job(job_id, input_type, input_data, content_hash, cached_summary)
        return SubmitResponse(job_id=job_id, status="completed")

    log.debug(f"Cache MISS | hash={content_hash[:12]}")
    await insert_job(job_id, input_type, input_data, content_hash)

    try:
        await publish_job(job_id)
        log.info(f"Job {job_id} queued in RabbitMQ")
    except Exception as e:
        log.error(f"Failed to publish job {job_id} to queue | error={e}")
        raise HTTPException(status_code=503, detail=f"Queue unavailable: {e}")

    return SubmitResponse(job_id=job_id, status="queued")


@app.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str):
    log.debug(f"Status check | job_id={job_id}")
    row = await get_job_status(job_id)
    if not row:
        log.warning(f"Status check | job_id={job_id} not found")
        raise HTTPException(status_code=404, detail="Job not found")
    return StatusResponse(
        job_id=row["id"],
        status=row["status"],
        created_at=row["created_at"],
    )


@app.get("/result/{job_id}", response_model=ResultResponse)
async def get_result(job_id: str):
    log.debug(f"Result fetch | job_id={job_id}")
    row = await get_job_result(job_id)
    if not row:
        log.warning(f"Result fetch | job_id={job_id} not found")
        raise HTTPException(status_code=404, detail="Job not found")

    original_url = row["input_data"] if row["input_type"] == "url" else None

    return ResultResponse(
        job_id=row["id"],
        original_url=original_url,
        summary=row["summary"],
        cached=row["cached"],
        processing_time_ms=row["processing_time_ms"],
        error=row["error"],
    )
