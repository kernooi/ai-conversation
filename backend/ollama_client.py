import json
from typing import AsyncGenerator

import httpx

from config import settings

# A single shared client avoids reopening TCP connections on every request.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _options() -> dict:
    return {
        "num_ctx": settings.num_ctx,
        "num_predict": settings.num_predict,
        "temperature": settings.temperature,
    }


async def chat_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream chat response from Ollama, yielding text chunks."""
    client = _get_client()
    async with client.stream(
        "POST",
        f"{settings.ollama_host}/api/chat",
        json={
            "model": settings.model_name,
            "messages": messages,
            "stream": True,
            "keep_alive": settings.keep_alive,
            "options": _options(),
        },
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                yield content
            if data.get("done", False):
                return


async def chat(messages: list[dict]) -> str:
    chunks: list[str] = []
    async for chunk in chat_stream(messages):
        chunks.append(chunk)
    return "".join(chunks)


async def summarize(history_text: str, existing_summary: str = "") -> str:
    prior = f"Previous summary:\n{existing_summary}\n\n" if existing_summary else ""
    prompt = (
        f"{prior}Summarize this conversation in 2-3 sentences. "
        f"Keep key topics and context.\n\n{history_text}\n\nSummary:"
    )
    client = _get_client()
    response = await client.post(
        f"{settings.ollama_host}/api/generate",
        json={
            "model": settings.model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": settings.keep_alive,
            "options": {"num_ctx": settings.num_ctx, "num_predict": 128},
        },
    )
    response.raise_for_status()
    return response.json()["response"].strip()


async def list_models() -> list[str]:
    client = _get_client()
    response = await client.get(f"{settings.ollama_host}/api/tags", timeout=5.0)
    response.raise_for_status()
    return [m["name"] for m in response.json().get("models", [])]


async def warm_up() -> None:
    """Load the model into VRAM at startup so the first real request is fast."""
    client = _get_client()
    await client.post(
        f"{settings.ollama_host}/api/chat",
        json={
            "model": settings.model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "keep_alive": settings.keep_alive,
            "options": {"num_ctx": settings.num_ctx, "num_predict": 1},
        },
        timeout=300.0,
    )
