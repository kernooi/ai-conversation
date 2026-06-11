import json
from typing import AsyncGenerator

import httpx

from config import settings


async def chat_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream chat response from Ollama, yielding text chunks."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_host}/api/chat",
            json={"model": settings.model_name, "messages": messages, "stream": True},
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
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={"model": settings.model_name, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json()["response"].strip()


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{settings.ollama_host}/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
