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
- Image/vision support is not built.

## Stack

| Layer | Technology | Notes |
|---|---|---|
| LLM | Ollama, configured by `backend/.env` `MODEL_NAME` | Current local model is `tripolskypetr/qwen3.5-uncensored-aggressive:9b` |
| Backend | FastAPI | SSE chat streaming, threadpool for blocking ML work |
| Frontend | Next.js 16, TypeScript, Tailwind | Main UI in `frontend/app/page.tsx` |
| STT | faster-whisper | Mic audio upload -> transcript |
| TTS | FunAudioLLM CosyVoice3 | Zero-shot voice cloning from reference audio + transcript |

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
- After load, test synthesis completed in about 8 seconds for a tiny Chinese
  phrase on this machine.
- `tts.py` uses a synthesis lock so overlapping sentence-level TTS requests do
  not fight over the same GPU.
- `WARM_UP_TTS=true` loads CosyVoice3 during backend startup if dependencies are
  available.

Known warning:
- If ONNXRuntime logs that `CUDAExecutionProvider` is unavailable, the ONNX
  preprocessing path is running on CPU. The main PyTorch model can still use
  CUDA. Installing a compatible `onnxruntime-gpu` can improve this later.

## Frontend Voice Flow

`frontend/app/lib/useSpeechQueue.ts` speaks assistant replies sentence by
sentence. It starts TTS for each completed sentence immediately while preserving
playback order, so the first audio does not wait for the full LLM reply.

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

- Vision/image input.
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
