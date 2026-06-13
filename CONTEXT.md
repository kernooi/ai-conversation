# AI Conversation - Project Context

> Handoff document for any assistant continuing this project.
> Read this before touching code.

## What This Project Is

A local, private AI voice + chat assistant. The goal is to clone a person's
voice and have a text/spoken conversation with them. Everything runs locally:
Ollama for chat, faster-whisper for speech-to-text, and CosyVoice3 for cloned
text-to-speech.

Current state:
- Chat works end to end through Ollama streaming.
- The Qwen thinking-model delay was fixed by sending `OLLAMA_THINK=false` to
  Ollama and only streaming visible content.
- STT is wired through `/transcribe`.
- TTS is now CosyVoice3, wired through the existing `/tts` endpoint.
- Image upload is built. The backend uses the configured Ollama vision model to
  extract image context, then feeds that context into the normal chat turn.

## Stack

| Layer | Technology | Notes |
|---|---|---|
| LLM | Ollama, configured by `backend/.env` `MODEL_NAME` | Current local model is `fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b` |
| Backend | FastAPI | SSE chat streaming, threadpool for blocking ML work |
| Frontend | Next.js 16, TypeScript, Tailwind | Main UI in `frontend/app/page.tsx` |
| STT | faster-whisper | Mic audio upload -> transcript |
| TTS | FunAudioLLM CosyVoice3 | Zero-shot voice cloning from reference audio + transcript |
| Vision | Ollama vision-capable model | `VISION_MODEL` blank means reuse `MODEL_NAME` |
| Image generation | ComfyUI + Flux Schnell | Local HTTP API at `COMFYUI_URL` |

The source of truth for runtime config is `backend/.env`, not README snippets.

## Important Environment Notes

- Use the backend venv at `backend/venv`.
- Python 3.11 is preferred for CUDA PyTorch compatibility.
- Ollama often runs as a Windows tray service. `ollama serve` failing with
  "address in use" usually means Ollama is already running.
- Port 8000 can be blocked by another process or Windows permissions. If
  `uvicorn --port 8000` fails with WinError 10013, use another port such as
  `8001` and update `frontend/.env.local`.
- CosyVoice3 model files are large. On this machine the active model path is
  `D:/ai-conversation-models/Fun-CosyVoice3-0.5B` because the C drive was full.

## Recommended Backend Setup

From `backend/`:

```cmd
py -3.11 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt
python -m pip install -r requirements-tts.txt
```

CosyVoice source is vendored at `backend/vendor/CosyVoice`. It was cloned from:

```cmd
git clone --depth 1 --recurse-submodules --shallow-submodules https://github.com/FunAudioLLM/CosyVoice.git backend\vendor\CosyVoice
```

Run:

```cmd
cd backend
venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

Frontend:

```cmd
cd frontend
npm install
npm run dev
```

## Repository Structure

```text
ai-conversation/
  CONTEXT.md
  README.md
  backend/
    main.py                  FastAPI endpoints and startup warm-up
    memory.py                Session summary + recent messages
    ollama_client.py         Ollama REST wrapper and streaming logs
    stt.py                   faster-whisper transcription
    tts.py                   CosyVoice3 voice cloning
    config.py                Pydantic settings from .env
    requirements.txt         Core backend + STT
    requirements-tts.txt     Optional CosyVoice3 TTS deps
    requirements-cosyvoice3.txt
    vendor/CosyVoice/        Vendored FunAudioLLM CosyVoice source
    voices/                  Reference clips and matching transcripts
  frontend/
    app/
      page.tsx
      lib/api.ts
      lib/useRecorder.ts
      lib/useSpeechQueue.ts
      components/
```

## Backend Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Ollama model availability and running-model diagnostics |
| POST | `/chat/stream` | Primary SSE chat endpoint |
| POST | `/chat` | Non-streaming fallback |
| DELETE | `/session/{id}` | Clear memory for one session |
| POST | `/transcribe` | Uploaded audio -> `{text, language}` |
| POST | `/vision/analyze` | Uploaded image -> `{description, model}` |
| GET | `/image/status` | ComfyUI availability and image-gen config |
| POST | `/image/generate` | Conversation prompt/context -> generated PNG |
| GET | `/voices` | List available reference voices |
| POST | `/tts` | `{text, voice?, language?}` -> WAV audio |

## LLM Performance Settings

Key settings in `backend/.env`:

```env
KEEP_ALIVE=30m
NUM_CTX=4096
NUM_PREDICT=400
TEMPERATURE=0.8
OLLAMA_THINK=false
WARM_UP_ON_START=true
```

`OLLAMA_THINK=false` is important for Qwen/thinking-capable models. Without it,
Ollama can stream hidden thinking while the website waits for visible content,
which makes the UI look stuck.

`ollama_client.py` logs stream timings:

```text
[ollama] stream elapsed=... first_content=... eval_tok_s=...
```

## Vision / Image Upload

Image upload is implemented in the frontend input bar. The image button accepts
up to four local images, shows thumbnails in the user message, and sends each
image to `POST /vision/analyze` before the chat turn starts.

Backend flow:
- `main.py` exposes `/vision/analyze`.
- `ollama_client.analyze_image(...)` sends the image as base64 in Ollama's
  chat `images` field.
- The vision model returns a factual description and OCR-style text extraction.
- `page.tsx` passes that description as `image_context` to `/chat/stream`.
- The normal conversation model then replies with the image context included in
  the user turn.

Config:

```env
# Blank means reuse MODEL_NAME. Set a separate vision model only if needed.
VISION_MODEL=
VISION_KEEP_ALIVE=10m
VISION_NUM_CTX=4096
VISION_NUM_PREDICT=700
VISION_MAX_IMAGE_MB=8
```

Current health check confirmed:

```text
vision_model=fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b
vision_model_available=true
```

Tested with a generated PNG containing a red square and the text `TEST 42`; the
vision endpoint correctly identified the text and shape.

## Image Generation: ComfyUI + Flux Schnell

Image generation is implemented but requires a running ComfyUI server. Frontend
flow:
- User uploads/talks about an image or explicitly asks for an image.
- The chat turn runs normally.
- If the turn is visual/action-oriented, `page.tsx` calls `/image/generate`.
- The returned PNG is attached to the assistant message.

Backend flow:
- `comfyui_client.py` queues a ComfyUI workflow through `POST /prompt`.
- It polls `/history/{prompt_id}` and fetches the image through `/view`.
- Default workflow uses `CheckpointLoaderSimple`, `KSampler`, `VAEDecode`, and
  `SaveImage`.
- If a custom API workflow is needed, set `COMFYUI_WORKFLOW_PATH` to an exported
  ComfyUI API JSON file.

Config:

```env
COMFYUI_URL=http://127.0.0.1:8188
COMFYUI_CHECKPOINT=flux1-schnell-fp8.safetensors
COMFYUI_WORKFLOW_PATH=
IMAGE_GEN_WIDTH=768
IMAGE_GEN_HEIGHT=512
IMAGE_GEN_STEPS=4
IMAGE_GEN_CFG=1.0
IMAGE_GEN_SAMPLER=euler
IMAGE_GEN_SCHEDULER=simple
IMAGE_GEN_TIMEOUT=300
IMAGE_GEN_REFERENCE_DENOISE=0.82
```

If the chat turn includes uploaded images, the first uploaded image is sent to
ComfyUI as a real visual reference. The built-in reference workflow uploads the
image through `/upload/image`, loads it with `LoadImage`, scales it to the target
size, encodes it with `VAEEncode`, then runs the Flux sampler with
`IMAGE_GEN_REFERENCE_DENOISE`. Lower denoise preserves the uploaded image more;
higher denoise follows the new prompt/action more strongly.

Suggested ComfyUI startup for an RTX 4070:

```cmd
python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --disable-dynamic-vram --lowvram --fp8_e4m3fn-unet --fp8_e4m3fn-text-enc --reserve-vram 1
```

If supported by the local ComfyUI build, add Sage Attention:

```cmd
python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --disable-dynamic-vram --lowvram --fp8_e4m3fn-unet --fp8_e4m3fn-text-enc --reserve-vram 1 --use-sage-attention
```

ComfyUI's own startup flag reference notes that `--fp8_e4m3fn-unet` stores the
diffusion model in fp8, `--fp8_e4m3fn-text-enc` stores the text encoder in fp8,
`--use-sage-attention` enables Sage attention, and `--lowvram` can run text
encoders on CPU in non-dynamic VRAM mode. The suggested command includes
`--disable-dynamic-vram` so `--lowvram` actually applies. Keep `--reserve-vram 1`
so Ollama/TTS have some room on the 4070.

The default checkpoint workflow expects a Flux Schnell checkpoint named
`flux1-schnell-fp8.safetensors` in ComfyUI's `models/checkpoints`. If your Flux
setup uses separate UNet/CLIP/VAE loader nodes instead of a checkpoint, export
that workflow as API JSON and point `COMFYUI_WORKFLOW_PATH` at it.

Current local status: `/image/status` reports ComfyUI is not running at
`http://127.0.0.1:8188`.

## TTS: CosyVoice3

Active backend engine: `backend/tts.py`.

CosyVoice3 runs in zero-shot cloning mode by default:

```env
TTS_MODEL=cosyvoice3
TTS_DEVICE=auto
TTS_LANGUAGE=zh-cn
VOICES_DIR=voices
DEFAULT_VOICE=default
COSYVOICE_REPO_DIR=vendor/CosyVoice
COSYVOICE_MODEL_DIR=D:/ai-conversation-models/Fun-CosyVoice3-0.5B
COSYVOICE_MODEL_REPO=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
COSYVOICE_AUTO_DOWNLOAD=true
COSYVOICE_MODE=zero_shot
COSYVOICE_SYSTEM_PROMPT=You are a helpful assistant.
COSYVOICE_SPEED=1.0
COSYVOICE_FP16=true
COSYVOICE_PREFIX_LANGUAGE_TOKENS=false
COSYVOICE_TEXT_FRONTEND=false
```

Required model files include:

```text
cosyvoice3.yaml
llm.pt
llm.rl.pt
flow.pt
hift.pt
campplus.onnx
speech_tokenizer_v3.onnx
speech_tokenizer_v3.batch.onnx
```

The app auto-downloads the model from Hugging Face if files are missing and
`COSYVOICE_AUTO_DOWNLOAD=true`.

Voice references:
- Put audio in `backend/voices/default.wav`, `default.mp3`, etc.
- Put the exact matching transcript in `backend/voices/default.txt`.
- Supported audio extensions: `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.aac`.
- Non-wav files are converted to cached wav using pydub/ffmpeg.

Important: CosyVoice3 quality depends heavily on the reference transcript being
exact. The current `voices/default.txt` was auto-generated by Whisper and should
be manually corrected against the reference clip.

Performance:
- First TTS call can take around 50 seconds because CosyVoice3 loads the model.
- After load, repeated HTTP `/tts` tests completed in about 3-5 seconds for
  short Chinese phrases on this machine.
- `tts.py` caches CosyVoice3 zero-shot speaker features with
  `model.add_zero_shot_spk(...)` and reuses the resulting `zero_shot_spk_id` for
  later requests. If logs show `[tts] cached CosyVoice3 speaker ...` for every
  line, the backend is restarting or the voice file/transcript changed.
- `tts.py` uses a synthesis lock so overlapping sentence-level TTS requests do
  not fight over the same GPU.
- `WARM_UP_TTS=true` loads CosyVoice3 during backend startup if dependencies are
  available.

Known warning:
- If ONNXRuntime logs that `CUDAExecutionProvider` is unavailable, the ONNX
  preprocessing path is running on CPU. The main PyTorch model can still use
  CUDA. Installing a compatible `onnxruntime-gpu` can improve this later.

## Frontend Voice Flow

`frontend/app/page.tsx` batches speech chunks before calling `/tts`: up to two
sentences or around 90 characters per request. This avoids paying CosyVoice3
overhead for every tiny sentence. `frontend/app/lib/useSpeechQueue.ts` still
starts each queued chunk immediately while preserving playback order, so the
next chunk can synthesize while the current chunk plays.

`ApiError` in `frontend/app/lib/api.ts` preserves `/tts` HTTP status codes. A
412 from `/tts` disables speech for that turn and shows one useful error instead
of retrying every sentence.

## STT

`backend/stt.py` uses faster-whisper with lazy loading and warm-up. Defaults:

```env
WHISPER_MODEL=base
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=auto
```

The active `.env` keeps Whisper on CPU:

```env
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

This is intentional on Windows. Loading faster-whisper/CTranslate2 before
PyTorch CosyVoice3 caused a `cudnnGetLibConfig` symbol failure in the same
backend process. Startup therefore warms TTS before STT, and Whisper stays on
CPU to reserve CUDA for CosyVoice3, which is the heavier and more
latency-sensitive voice component.

Set `WHISPER_LANGUAGE=zh` if Chinese auto-detection is unstable.

## Things Not Built

- Full duplex voice / barge-in WebSocket flow.
- Intra-sentence audio streaming from CosyVoice3. Current implementation streams
  text from Ollama and starts TTS at sentence boundaries.

## Gotchas

- Restart the backend after changing `.env`; Pydantic settings are loaded at
  process start.
- If `/tts` returns 412, the reference voice or transcript is missing or the
  CosyVoice3 model path is incomplete.
- If `/tts` returns 500 and mentions text normalization, keep
  `COSYVOICE_TEXT_FRONTEND=false` for now.
- Keep `NUM_CTX` and `NUM_PREDICT` modest for speed.
- Do not revert unrelated dirty files. This workspace may include local changes
  and generated caches.
