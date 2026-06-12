import json
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import memory
import ollama_client
import stt
import tts
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Preload models into VRAM at startup so the first request of each kind
    # isn't a cold load. Run GPU-heavy warm-ups one at a time; loading Ollama,
    # Whisper, and CosyVoice3 concurrently can stall or OOM a single GPU.
    async def run_warmer(name: str, coro) -> None:
        print(f"[warm-up] preloading: {name}...")
        try:
            await coro
        except Exception as e:
            print(f"[warm-up] {name} skipped: {e}")

    if settings.warm_up_on_start:
        await run_warmer("LLM", ollama_client.warm_up())
    if settings.warm_up_tts:
        if tts.available():
            await run_warmer("TTS", run_in_threadpool(tts.warm_up))
        else:
            print("[warm-up] TTS skipped: CosyVoice3 source/deps not available")
    if settings.warm_up_stt:
        await run_warmer("STT", run_in_threadpool(stt.warm_up))
    print("[warm-up] done")

    yield
    await ollama_client.aclose()


app = FastAPI(title="AI Conversation Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request / response models

class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


class TranscribeResponse(BaseModel):
    text: str
    language: str


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None
    language: str | None = None


# Helpers

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
        # Summarization failure is non-critical; silently skip.
        pass


# Routes

@app.get("/health")
async def health():
    try:
        models = await ollama_client.list_models()
        try:
            running_models = await ollama_client.list_running_models()
        except Exception as e:
            running_models = [{"error": str(e)}]
        model_available = any(settings.model_name in m for m in models)
        return {
            "status": "ok",
            "model": settings.model_name,
            "model_available": model_available,
            "ollama_options": {
                "think": ollama_client.think_setting(),
                "keep_alive": settings.keep_alive,
                "num_ctx": settings.num_ctx,
                "num_predict": settings.num_predict,
                "temperature": settings.temperature,
            },
            "running_models": running_models,
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


# Voice: speech-to-text

@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)):
    """Transcribe uploaded audio (webm/wav/mp3/etc.) to text via Whisper."""
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    tmp_path = os.path.join(tempfile.gettempdir(), f"stt_{uuid.uuid4().hex}{suffix}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(await audio.read())
        result = await run_in_threadpool(stt.transcribe, tmp_path)
        return TranscribeResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# Voice: text-to-speech (cloning)

@app.get("/voices")
async def voices():
    """List available reference voices for cloning."""
    return {"voices": tts.list_voices(), "default": settings.default_voice}


@app.post("/tts")
async def synthesize(req: TTSRequest, background_tasks: BackgroundTasks):
    """Synthesize speech in a cloned voice. Returns a wav file."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")

    out_path = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4().hex}.wav")
    try:
        await run_in_threadpool(tts.synthesize, req.text, out_path, req.voice, req.language)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except tts.TTSConfigError as e:
        raise HTTPException(status_code=412, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    # Clean up the temp file after the response is sent
    background_tasks.add_task(lambda: os.path.exists(out_path) and os.remove(out_path))
    return FileResponse(out_path, media_type="audio/wav", filename="speech.wav")
