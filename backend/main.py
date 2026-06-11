import json

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import memory
import ollama_client
from config import settings

app = FastAPI(title="AI Conversation Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _maybe_summarize(session_id: str) -> None:
    if not memory.should_summarize(session_id, settings.summarize_after):
        return
    session = memory.get_or_create(session_id)
    old_messages = memory.pop_old_messages(session_id, settings.keep_recent)
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in old_messages
    )
    try:
        summary = await ollama_client.summarize(history_text, session.summary)
        memory.apply_summary(session_id, summary)
    except Exception:
        # Summarization failure is non-critical — silently skip
        pass


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    try:
        models = await ollama_client.list_models()
        model_available = any(settings.model_name in m for m in models)
        return {
            "status": "ok",
            "model": settings.model_name,
            "model_available": model_available,
            "available_models": models,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Non-streaming chat endpoint (fallback)."""
    memory.add_message(req.session_id, "user", req.message)
    context = memory.build_context(req.session_id)

    try:
        response = await ollama_client.chat(context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    memory.add_message(req.session_id, "assistant", response)
    await _maybe_summarize(req.session_id)

    return ChatResponse(response=response, session_id=req.session_id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, background_tasks: BackgroundTasks):
    """SSE streaming chat endpoint. Yields JSON-encoded text chunks."""
    memory.add_message(req.session_id, "user", req.message)
    context = memory.build_context(req.session_id)
    collected: list[str] = []

    async def generate():
        try:
            async for chunk in ollama_client.chat_stream(context):
                collected.append(chunk)
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    async def persist():
        full = "".join(collected)
        if full:
            memory.add_message(req.session_id, "assistant", full)
            await _maybe_summarize(req.session_id)

    background_tasks.add_task(persist)
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    memory.sessions.pop(session_id, None)
    return {"cleared": session_id}
