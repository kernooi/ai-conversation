import json
import time
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


def think_setting() -> bool | str:
    value = settings.ollama_think
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", "none", ""}:
            return False
        return normalized
    return value


def _chat_payload(messages: list[dict], stream: bool, options: dict | None = None) -> dict:
    return {
        "model": settings.model_name,
        "messages": messages,
        "stream": stream,
        "think": think_setting(),
        "keep_alive": settings.keep_alive,
        "options": options or _options(),
    }


def _log_stream_stats(
    *,
    elapsed: float,
    first_content_at: float | None,
    content_chars: int,
    thinking_chars: int,
    final_stats: dict,
) -> None:
    eval_count = final_stats.get("eval_count") or 0
    eval_duration = final_stats.get("eval_duration") or 0
    prompt_count = final_stats.get("prompt_eval_count") or 0
    prompt_duration = final_stats.get("prompt_eval_duration") or 0
    token_rate = eval_count / (eval_duration / 1_000_000_000) if eval_duration else 0
    prompt_rate = prompt_count / (prompt_duration / 1_000_000_000) if prompt_duration else 0
    first = f"{first_content_at:.2f}s" if first_content_at is not None else "none"
    print(
        "[ollama] stream "
        f"elapsed={elapsed:.2f}s first_content={first} "
        f"content_chars={content_chars} hidden_thinking_chars={thinking_chars} "
        f"eval_tokens={eval_count} eval_tok_s={token_rate:.1f} "
        f"prompt_tokens={prompt_count} prompt_tok_s={prompt_rate:.1f}",
        flush=True,
    )


async def chat_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream chat response from Ollama, yielding text chunks."""
    client = _get_client()
    started = time.perf_counter()
    first_content_at: float | None = None
    content_chars = 0
    thinking_chars = 0
    final_stats: dict = {}

    try:
        async with client.stream(
            "POST",
            f"{settings.ollama_host}/api/chat",
            json=_chat_payload(messages, stream=True),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                message = data.get("message", {})
                thinking = message.get("thinking", "")
                if thinking:
                    thinking_chars += len(thinking)

                content = message.get("content", "")
                if content:
                    if first_content_at is None:
                        first_content_at = time.perf_counter() - started
                    content_chars += len(content)
                    yield content

                if data.get("done", False):
                    final_stats = data
                    return
    finally:
        _log_stream_stats(
            elapsed=time.perf_counter() - started,
            first_content_at=first_content_at,
            content_chars=content_chars,
            thinking_chars=thinking_chars,
            final_stats=final_stats,
        )


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
            "think": think_setting(),
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


async def list_running_models() -> list[dict]:
    client = _get_client()
    response = await client.get(f"{settings.ollama_host}/api/ps", timeout=5.0)
    response.raise_for_status()
    running = []
    for model in response.json().get("models", []):
        size = model.get("size")
        size_vram = model.get("size_vram")
        vram_percent = None
        if size and size_vram:
            vram_percent = round((size_vram / size) * 100, 1)
        running.append(
            {
                "name": model.get("name") or model.get("model"),
                "context": model.get("context_length"),
                "size": size,
                "size_vram": size_vram,
                "vram_percent": vram_percent,
                "until": model.get("expires_at"),
            }
        )
    return running


async def warm_up() -> None:
    """Load the model into VRAM at startup so the first real request is fast."""
    client = _get_client()
    await client.post(
        f"{settings.ollama_host}/api/chat",
        json=_chat_payload(
            [{"role": "user", "content": "hi"}],
            stream=False,
            options={"num_ctx": settings.num_ctx, "num_predict": 1},
        ),
        timeout=300.0,
    )
