# Async Content Summarizer

Accepts a URL or raw text, processes it asynchronously via a job queue, and returns an AI-generated summary using Ollama.

## Architecture

```
Client → FastAPI → PostgreSQL (job record) + RabbitMQ (queue)
                         ↓
                      Worker (RabbitMQ consumer)
                  (fetches URL if needed → Ollama → stores result → caches in Redis)
                         ↓
Client polls GET /status/:id → GET /result/:id
```

### Components

| Component  | Technology       | Role                                         |
|------------|------------------|----------------------------------------------|
| API        | FastAPI          | Accepts requests, manages jobs               |
| Worker     | Python + aio_pika| RabbitMQ consumer, processes jobs            |
| PostgreSQL | postgres:16      | Stores all job records permanently           |
| RabbitMQ   | rabbitmq:3       | Job queue between API and Worker             |
| Redis      | redis:7          | Cache for duplicate content (24h TTL)        |
| Ollama     | ollama/ollama    | Local LLM (llama3.2) for summarization       |

### Request Flow

**First time (cache miss):**
1. `POST /submit` → API hashes content → checks Redis → MISS
2. API inserts job into PostgreSQL (`status=queued`)
3. API publishes `job_id` to RabbitMQ → returns `job_id` immediately
4. Worker picks up `job_id` → fetches content from PostgreSQL
5. Worker sets `status=processing`
6. If URL → fetches page, strips HTML → extracts text (max 24000 chars)
7. Worker sends text to Ollama → gets summary (up to 60s)
8. Worker updates PostgreSQL (`status=completed`, saves summary)
9. Worker stores summary in Redis (`summary:<hash>`, TTL 24h)

**Same content again (cache hit):**
1. `POST /submit` → API hashes content → checks Redis → HIT
2. API inserts completed job directly into PostgreSQL (`cached=true`)
3. Returns `job_id` instantly — no RabbitMQ, no Ollama

## Prerequisites

- Docker + Docker Compose

## Setup

1. **Clone and start everything**
   ```bash
   docker compose up --build -d
   ```

2. **Pull the Ollama model** (first time only)
   ```bash
   docker compose exec ollama ollama pull llama3.2
   ```

3. **Configure environment** (optional)
   ```bash
   cp .env.example .env
   # Edit .env if needed (defaults work with docker-compose)
   ```

## API

### Submit content
```bash
POST /submit
{"url": "https://example.com/article"}
# or
{"text": "Long content to summarize..."}
```
Response: `{"job_id": "abc123", "status": "queued"}`

### Check status
```bash
GET /status/abc123
```
Response: `{"job_id": "abc123", "status": "completed", "created_at": "..."}`

### Get result
```bash
GET /result/abc123
```
Response:
```json
{
  "job_id": "abc123",
  "original_url": "https://example.com/article",
  "summary": "This article discusses...",
  "cached": false,
  "processing_time_ms": 2340
}
```

## Statuses
| Status     | Meaning                                  |
|------------|------------------------------------------|
| `queued`   | Job accepted, waiting for worker         |
| `processing` | Worker is actively processing          |
| `completed` | Summary ready                           |
| `failed`   | Error occurred (see `error` field)       |

## Caching
Identical content (same URL or same text) returns a cached result instantly without hitting Ollama again. Cache TTL is 24 hours and is stored in Redis.

## Logs

**View live logs:**
```bash
docker compose logs -f           # all containers
docker compose logs -f worker    # worker only
docker compose logs -f api       # api only
```

**Log files on host (api and worker):**
```
logs/api/api.log
logs/worker/worker.log
```

**Debugging order:**
1. `api` — did the request reach the app?
2. `rabbitmq` — did the job get queued?
3. `worker` — did the job get picked up?
4. `ollama` — did the LLM respond?
5. `postgres` — did the result get saved?

## Edge Cases Handled
- Missing both `url` and `text` → 422 validation error
- Invalid / unreachable URL → job marked `failed` with error message
- URL returns 403 → User-Agent spoofing applied automatically
- Ollama timeout (>60s) → job marked `failed`
- RabbitMQ unavailable at submit time → 503 response
- Duplicate content → instant cached response
- Job ID not found → 404
