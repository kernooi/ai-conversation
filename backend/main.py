import json
import os
import tempfile
import uuid
from asyncio import create_task
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import comfyui_client
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
    image_context: str | None = None


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


class VisionResponse(BaseModel):
    description: str
    model: str


class ImageGenerateRequest(BaseModel):
    prompt: str
    image_context: str | None = None
    assistant_response: str | None = None
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    reference_image_bytes: bytes | None = None
    reference_image_filename: str | None = None
    reference_image_content_type: str | None = None


class ImageJobResponse(BaseModel):
    job_id: str
    status: str


class ImageJobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None = None


# Helpers

image_generation_jobs: dict[str, dict] = {}

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


def _chat_user_content(message: str, image_context: str | None = None) -> str:
    clean = message.strip()
    context = (image_context or "").strip()
    if not context:
        return clean
    return (
        f"{clean}\n\n"
        "[Image context extracted by the local vision model. Use this as visual "
        "grounding for the conversation, but do not mention this note unless "
        "the user asks how you saw the image.]\n"
        f"{context}"
    )


async def _ensure_vision_model_available() -> None:
    models = await ollama_client.list_models()
    vision_model = ollama_client.vision_model_name()
    if not any(vision_model == m or vision_model in m for m in models):
        raise HTTPException(
            status_code=412,
            detail=(
                f"Vision model '{vision_model}' is not available in Ollama. "
                f"Run: ollama pull {vision_model}"
            ),
        )


def _truncate(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def _build_image_generation_prompt(req: ImageGenerateRequest) -> str:
    prompt = _truncate(req.prompt, 450)
    image_context = _truncate(req.image_context or "", 900)
    assistant_response = _truncate(req.assistant_response or "", 450)
    parts = [
        "Generate one clear image that illustrates the current conversation.",
        "Use a natural, cinematic, high-quality composition with a clear subject and readable action.",
        f"User request: {prompt}",
    ]
    if req.reference_image_bytes:
        parts.append(
            "Use the uploaded reference image pixels as the primary visual reference. "
            "Preserve the main subject's visible identity, colors, markings, clothing, "
            "and distinctive features while applying the requested change."
        )
    if image_context:
        parts.append(
            "Reference visual context from uploaded image. Preserve key visible traits when relevant: "
            f"{image_context}"
        )
    if assistant_response:
        parts.append(f"Conversation context: {assistant_response}")
    parts.append("No watermark, no UI, no caption text unless the user explicitly requested text.")
    return "\n".join(parts)


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
        vision_model = ollama_client.vision_model_name()
        vision_model_available = any(vision_model == m or vision_model in m for m in models)
        return {
            "status": "ok",
            "model": settings.model_name,
            "model_available": model_available,
            "vision_model": vision_model,
            "vision_model_available": vision_model_available,
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
    user_content = _chat_user_content(req.message, req.image_context)
    memory.add_message(req.session_id, "user", user_content)
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
    user_content = _chat_user_content(req.message, req.image_context)
    memory.add_message(req.session_id, "user", user_content)
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


# Vision: image understanding

@app.post("/vision/analyze", response_model=VisionResponse)
async def analyze_image(
    image: UploadFile = File(...),
    prompt: str = Form(""),
):
    """Analyze an uploaded image with the configured Ollama vision model."""
    content_type = image.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="file must be an image")

    data = await image.read()
    max_bytes = settings.vision_max_image_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"image is too large; limit is {settings.vision_max_image_mb} MB",
        )
    if not data:
        raise HTTPException(status_code=400, detail="image is empty")

    await _ensure_vision_model_available()
    try:
        description = await ollama_client.analyze_image(data, prompt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vision model error: {e}")

    if not description:
        raise HTTPException(status_code=502, detail="Vision model returned no description")
    return VisionResponse(description=description, model=ollama_client.vision_model_name())


# Image generation: ComfyUI + Flux Schnell

@app.get("/image/status")
async def image_status():
    """Check whether ComfyUI is reachable."""
    try:
        status = await comfyui_client.health()
        return {
            **status,
            "checkpoint": settings.comfyui_checkpoint,
            "width": settings.image_gen_width,
            "height": settings.image_gen_height,
            "steps": settings.image_gen_steps,
            "reference_denoise": settings.image_gen_reference_denoise,
        }
    except Exception as e:
        return {
            "available": False,
            "url": settings.comfyui_url,
            "detail": str(e),
        }


@app.post("/image/generate")
async def generate_image(req: ImageGenerateRequest):
    """Generate a relevant image with ComfyUI and return a PNG."""
    if not req.prompt.strip() and not (req.image_context or "").strip():
        raise HTTPException(status_code=400, detail="prompt or image_context is required")

    prompt = _build_image_generation_prompt(req)
    negative = (
        "low quality, blurry, distorted, deformed, extra limbs, bad anatomy, "
        "watermark, logo, signature, oversaturated, noisy"
    )
    try:
        image_bytes = await comfyui_client.generate_image(
            prompt=prompt,
            negative=negative,
            width=req.width,
            height=req.height,
            seed=req.seed,
            reference_image_bytes=req.reference_image_bytes,
            reference_image_filename=req.reference_image_filename,
            reference_image_content_type=req.reference_image_content_type,
        )
    except comfyui_client.ComfyUIError as e:
        raise HTTPException(
            status_code=412,
            detail=(
                f"{e}. Start ComfyUI on {settings.comfyui_url} with a Flux Schnell "
                f"checkpoint named '{settings.comfyui_checkpoint}', or update "
                "COMFYUI_URL/COMFYUI_CHECKPOINT/COMFYUI_WORKFLOW_PATH in backend/.env."
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {e}")

    return Response(content=image_bytes, media_type="image/png")


async def _run_image_generation_job(job_id: str, req: ImageGenerateRequest) -> None:
    prompt = _build_image_generation_prompt(req)
    negative = (
        "low quality, blurry, distorted, deformed, extra limbs, bad anatomy, "
        "watermark, logo, signature, oversaturated, noisy"
    )
    image_generation_jobs[job_id]["status"] = "running"
    try:
        image_generation_jobs[job_id]["image"] = await comfyui_client.generate_image(
            prompt=prompt,
            negative=negative,
            width=req.width,
            height=req.height,
            seed=req.seed,
            reference_image_bytes=req.reference_image_bytes,
            reference_image_filename=req.reference_image_filename,
            reference_image_content_type=req.reference_image_content_type,
        )
        image_generation_jobs[job_id]["status"] = "done"
    except Exception as e:
        image_generation_jobs[job_id]["status"] = "error"
        image_generation_jobs[job_id]["error"] = str(e) or repr(e)


async def _image_request_from_http(request: Request) -> ImageGenerateRequest:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        reference_image = form.get("reference_image")
        reference_bytes = None
        reference_filename = None
        reference_content_type = None

        if hasattr(reference_image, "read"):
            reference_content_type = getattr(reference_image, "content_type", None)
            if reference_content_type and not reference_content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="reference_image must be an image")
            reference_bytes = await reference_image.read()
            max_bytes = settings.vision_max_image_mb * 1024 * 1024
            if len(reference_bytes) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"reference_image is too large; limit is {settings.vision_max_image_mb} MB",
                )
            reference_filename = getattr(reference_image, "filename", None)

        return ImageGenerateRequest(
            prompt=str(form.get("prompt") or ""),
            image_context=str(form.get("image_context") or "") or None,
            assistant_response=str(form.get("assistant_response") or "") or None,
            width=int(form["width"]) if form.get("width") else None,
            height=int(form["height"]) if form.get("height") else None,
            seed=int(form["seed"]) if form.get("seed") else None,
            reference_image_bytes=reference_bytes,
            reference_image_filename=reference_filename,
            reference_image_content_type=reference_content_type,
        )

    payload = await request.json()
    return ImageGenerateRequest(**payload)


@app.post("/image/generate/start", response_model=ImageJobResponse)
async def start_image_generation(request: Request):
    """Start image generation in the background and return a short-lived job id."""
    req = await _image_request_from_http(request)
    if not req.prompt.strip() and not (req.image_context or "").strip():
        raise HTTPException(status_code=400, detail="prompt or image_context is required")

    job_id = uuid.uuid4().hex
    image_generation_jobs[job_id] = {"status": "queued", "image": None, "error": None}
    create_task(_run_image_generation_job(job_id, req))
    return ImageJobResponse(job_id=job_id, status="queued")


@app.get("/image/generate/{job_id}", response_model=ImageJobStatusResponse)
async def image_generation_status(job_id: str):
    """Return status for a queued image generation job."""
    job = image_generation_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="image generation job not found")
    return ImageJobStatusResponse(
        job_id=job_id,
        status=job["status"],
        error=job.get("error"),
    )


@app.get("/image/generate/{job_id}/result")
async def image_generation_result(job_id: str):
    """Return the generated image once a job has completed."""
    job = image_generation_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="image generation job not found")
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job.get("error") or "image generation failed")
    if job["status"] != "done" or not job.get("image"):
        raise HTTPException(status_code=202, detail="image generation is not ready")
    return Response(content=job["image"], media_type="image/png")


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
