import asyncio
import httpx
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from app.logger import get_logger

load_dotenv()

log = get_logger("summarizer")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
FETCH_TIMEOUT = 15  # seconds
LLM_TIMEOUT = 60    # seconds


async def fetch_url_content(url: str) -> str:
    log.debug(f"Fetching URL: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            log.debug(f"URL fetch OK | status={response.status_code} | size={len(response.text)} chars")
        except httpx.HTTPStatusError as e:
            log.error(f"URL fetch failed | HTTP {e.response.status_code} | url={url}")
            raise ValueError(f"URL returned HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            log.error(f"URL fetch failed | connection error | url={url} | error={e}")
            raise ValueError(f"Failed to fetch URL: {e}")

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    if not text.strip():
        log.error(f"No readable content found at URL: {url}")
        raise ValueError("No readable content found at URL")

    truncated = text[:24000]
    log.debug(f"Extracted {len(truncated)} chars after cleaning (original {len(text)} chars)")
    return truncated


async def summarize_text(text: str) -> str:
    log.debug(f"Calling Ollama | model={OLLAMA_MODEL} | url={OLLAMA_BASE_URL} | text_len={len(text)}")

    prompt = (
        "Please provide a concise, clear summary of the following content. "
        "Focus on the key points and main ideas.\n\n"
        f"Content:\n{text}\n\nSummary:"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        try:
            response = await asyncio.wait_for(
                client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload),
                timeout=LLM_TIMEOUT,
            )
            response.raise_for_status()
            log.debug(f"Ollama responded | status={response.status_code}")
        except asyncio.TimeoutError:
            log.error(f"Ollama timed out after {LLM_TIMEOUT}s | model={OLLAMA_MODEL}")
            raise TimeoutError("LLM request timed out after 60 seconds")
        except httpx.RequestError as e:
            log.error(f"Could not connect to Ollama at {OLLAMA_BASE_URL} | error={e}")
            raise ConnectionError(f"Could not connect to Ollama: {e}")

    data = response.json()
    summary = data.get("message", {}).get("content", "").strip()

    if not summary:
        log.error(f"Ollama returned empty response | raw={data}")
        raise ValueError("LLM returned an empty response")

    log.debug(f"Summary generated | length={len(summary)} chars")
    return summary
