# AI Conversation — Project Context

> Handoff document for any AI assistant continuing this project.
> Read this fully before touching any file.

---

## What this project is

A local, private AI voice + chat assistant. The end goal is to clone a person's voice and have a real-time conversation with them — text and spoken. Everything runs locally (no cloud APIs).

**Current phase:** Text chat works end-to-end. Voice pipeline (STT + TTS with voice cloning) is **built, wired into the UI, and GPU-optimized** (latent caching, sentence-streaming, warm-up, auto-send voice). The remaining gap is hardware: the current dev PC has **no GPU**, so the TTS half can't be runtime-tested here — chat + STT run on CPU. Code auto-detects GPU vs CPU, so moving to the GPU box needs no code changes. Image/vision support is **not built** (deliberately deferred).

---

## Stack

| Layer | Technology | Notes |
|---|---|---|
| LLM | `qwen3:8b` via Ollama (current) | Text-only (no vision). |
| Backend | FastAPI (Python) | Async, SSE streaming, threadpool for blocking ML calls |
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind) | See `frontend/AGENTS.md` — this is Next 16, APIs may differ from training data |
| STT | faster-whisper | **Built.** Records mic → uploads → transcribes |
| TTS | Coqui XTTS v2 (`coqui-tts` fork) | **Built.** Voice cloning from a reference clip |

**Model note:** the LLM has been swapped several times (MythoMax → `tripolskypetr/qwen3.5-uncensored-aggressive:9b` → `qwen3:8b`). The README may reference older models; the **source of truth is `backend/.env`** (`MODEL_NAME`). All models used so far are text-only — **no vision**. Verify a model's capabilities with `ollama show <model>` before assuming image support.

---

## Hardware & environment reality (IMPORTANT)

- **Target hardware:** RTX 4070 (CUDA). The code defaults to `auto` for both Whisper and XTTS — uses CUDA if present, else CPU. No per-machine editing needed.
- **Current dev PC has NO GPU.** XTTS (PyTorch) is therefore not functional here; chat + STT run on CPU.
- **Python 3.13 blocker:** the system Python is 3.13. PyTorch's CUDA wheels do **not** exist for 3.13 yet — `pip install torch --index-url .../cu121` fails with "No matching distribution". **Resolution path agreed: use Python 3.11 in a venv** for the backend, install CUDA torch first, then `requirements.txt`.
- `faster-whisper` installed fine and works on CPU. Only the **TTS half** is blocked by the missing torch.
- **Windows PATH quirk:** `python`/`pip` work in **cmd** but not in the PowerShell terminal on this machine. Run backend commands from **cmd**, or use a venv.
- Ollama auto-starts as a Windows tray app — `ollama serve` failing with "address in use" is **normal** (it's already running). Use `ollama list` to confirm.

### Recommended backend setup on the GPU machine (Python 3.11)
One-time setup:
```cmd
cd backend
py -3.11 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt
python -m pip install -r requirements-tts.txt   # voice output (XTTS) — optional
```
Order matters: install **CUDA torch first** so `coqui-tts` doesn't pull a CPU build.

Every run after that (new terminal): `venv\Scripts\activate` then `uvicorn main:app --reload --port 8000`. Creating the venv and the pip installs are one-time only.

### CPU-only fallback (no GPU)
XTTS on CPU is too slow for conversation (~15–30s/reply). Options discussed but not implemented:
- Switch TTS engine to **Piper** (fast on CPU, no cloning) behind a config flag — recommended for CPU boxes.
- Or set `TTS_DEVICE=cpu` and accept the slowness for testing only.

---

## Repository structure

```
ai-conversation/
├── CONTEXT.md             # This file
├── README.md              # Quick run notes (may lag behind; .env is source of truth)
├── backend/
│   ├── main.py            # FastAPI app — all endpoints + startup warm-up (lifespan)
│   ├── memory.py          # Session memory (summary + recent messages)
│   ├── ollama_client.py   # Ollama REST wrapper (httpx async, keep_alive, warm_up)
│   ├── stt.py             # faster-whisper transcription (lazy-load, warm_up)
│   ├── tts.py             # XTTS v2 voice cloning (lazy-load, format conversion, warm_up, GPU lock)
│   ├── config.py          # Pydantic settings (reads .env)
│   ├── requirements.txt        # Core: chat + STT (no torch; installs on 3.11–3.13)
│   ├── requirements-tts.txt    # Optional: XTTS voice output (needs torch)
│   ├── .env               # Real config (gitignored)
│   ├── .env.example       # Template
│   └── voices/            # Reference voice clips for cloning (.mp3/.wav/etc.) + README
└── frontend/
    └── app/
        ├── page.tsx                    # Main page: chat state, sentence-streaming TTS
        ├── lib/
        │   ├── api.ts                  # chat, stream, clearSession, transcribe, tts, voices
        │   ├── types.ts                # Message, Session, ChatRequest, ChatResponse
        │   ├── useRecorder.ts          # Mic recording hook (MediaRecorder)
        │   └── useSpeechQueue.ts       # Ordered, overlapping sentence-by-sentence TTS playback
        └── components/
            ├── ChatWindow.tsx          # Scrollable message list + typing indicator
            ├── MessageBubble.tsx       # User/AI bubbles with streaming cursor
            ├── ChatInput.tsx           # Textarea + mic; auto-sends spoken messages
            └── VoiceControls.tsx       # Voice-mode toggle + cloned-voice picker (header)
```

---

## How to run

**Prerequisites:** Ollama installed + model pulled, Python 3.11 (for TTS/GPU; see above), Node 18+

1. **Ollama** (auto-starts): `ollama list` to confirm the model in `.env` is present.
2. **Backend** (from cmd / venv): `uvicorn main:app --reload --port 8000`
   - On boot it **warms up** the LLM, Whisper, and XTTS concurrently — expect a pause, then `[warm-up] done`.
   - Verify: `http://localhost:8000/health` → `"model_available": true`.
3. **Frontend:** `cd frontend && npm install && npm run dev` → `http://localhost:3000`

**Before TTS works:** drop a reference clip at `backend/voices/default.<ext>` (mp3/wav/m4a/ogg/flac/aac, 6–30s clean speech). Conversion needs **ffmpeg** on PATH.

---

## Backend design

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Ollama connection + model availability |
| POST | `/chat/stream` | **Primary** chat endpoint — SSE streaming |
| POST | `/chat` | Fallback non-streaming chat |
| DELETE | `/session/{id}` | Clear session memory |
| POST | `/transcribe` | Audio file (multipart) → `{text, language}` via Whisper |
| GET | `/voices` | List reference voices `{voices: [...], default}` |
| POST | `/tts` | `{text, voice?, language?}` → wav file (cloned voice) |

### Memory system
`SessionData = {summary: str, messages: list}`. Context sent to the model = system prompt + **last 8 messages** only. When a session exceeds `SUMMARIZE_AFTER` (12), the oldest `N - KEEP_RECENT` (6) messages are summarized via a second Ollama call and folded into `summary`, which is injected into the system prompt thereafter.

### Streaming (SSE)
`/chat/stream` yields `data: "<json-string-chunk>"\n\n`, errors as `data: {"error": ...}`, ends with `data: [DONE]`. Memory persistence runs in a `BackgroundTask` after the stream so it never blocks the response.

### Performance work (already done) — tuned for GPU
- **Device auto-detection**: `WHISPER_DEVICE` / `TTS_DEVICE` / `WHISPER_COMPUTE_TYPE` default to `auto` → CUDA + float16 on a GPU box, CPU + int8 on the laptop. Same `.env` works on both machines.
- **Warm-up at startup** (`main.py` lifespan): LLM + Whisper + XTTS preloaded concurrently via `asyncio.gather` + `run_in_threadpool`. TTS warm-up self-skips if torch isn't installed (`tts.available()`). Toggles: `WARM_UP_ON_START`, `WARM_UP_STT`, `WARM_UP_TTS`.
- **XTTS speaker-latent caching** (`tts.py` `_get_latents`): speaker conditioning latents are computed **once per voice** (keyed by clip path+mtime) and reused. Synthesis uses the low-level `model.inference()` fast path with a safe fallback to `tts_to_file` if the Coqui internal API differs. This is the main per-sentence GPU speed win.
- **`keep_alive` (30m)** on Ollama calls so the model stays in VRAM between turns (no cold reloads).
- **`num_predict` (400)** caps reply length; **`num_ctx` (4096)** keeps prompt processing fast.
- **Shared httpx client** reused across requests.
- **Sentence-streaming TTS** (the big voice win): the frontend extracts complete sentences from the token stream as they arrive and speaks each one while the rest is still generating. Time-to-first-audio ≈ first sentence + its synthesis, not the whole reply.
- **GPU synthesis lock** in `tts.py` (`threading.Lock`) serializes XTTS calls so overlapping per-sentence requests don't collide on the single GPU.
- **STT speed**: `WHISPER_BEAM_SIZE` (default 1 = greedy/fastest; raise to 5 for accuracy) + `condition_on_previous_text=False`.
- **Auto-send voice** (`ChatInput.tsx` `autoSendVoice`, default on): a spoken message transcribes and sends immediately — type *or* speak, AI replies in the cloned voice.

### STT (`stt.py`)
faster-whisper, lazy-loaded + cached. `vad_filter=True` (skips silence). `WHISPER_LANGUAGE` unset = auto-detect (set `zh` for Chinese). Blocking — called via `run_in_threadpool`.

### TTS (`tts.py`)
XTTS v2 via `coqui-tts`. Voice cloning from `voices/<name>.<ext>`. Accepts mp3/wav/m4a/ogg/flac/aac — non-wav is auto-converted to wav once via **pydub/ffmpeg** and cached. Lazy-loaded + cached. Chinese supported (`zh-cn`).

### Ollama client (`ollama_client.py`)
Raw `httpx` async (not the `ollama` package). `/api/chat` for chat, `/api/generate` for summarization, `/api/tags` for model list. Sends `keep_alive` + `options` (num_ctx/num_predict/temperature) on every call.

---

## Frontend design

### Streaming UX
User bubble appears instantly → empty AI bubble with blinking cursor → tokens append live → cursor clears at end. Input disabled during the stream.

### Voice mode
- **Mic (STT):** `ChatInput.tsx` uses `useRecorder` (MediaRecorder). Tap to record, tap to stop → uploads to `/transcribe` → transcribed text drops into the textarea (user reviews + sends).
- **Speech (TTS):** header toggle (`VoiceControls.tsx`). When on, AI replies are spoken in the selected cloned voice. Uses `useSpeechQueue` for **ordered, overlapping** sentence playback. Voice picker lists `/voices`.
- Sentence splitting handles Latin **and** CJK punctuation (`. ! ? 。 ！ ？` + newline); short fragments (<12 chars) are held back to avoid splitting on "3.14"/"Mr." and flushed at stream end.

### Session management
`SESSION_ID` is one `uuidv4` per page load, sent with every request. "New chat" calls `DELETE /session/{id}` and resets local state + stops playback.

### API calls (`api.ts`)
`sendMessage`, `streamMessage` (async generator), `clearSession`, `transcribe(Blob)`, `listVoices`, `synthesizeSpeech(text, voice?, language?)`.

---

## What is NOT built yet

### 1. Image / vision support (deferred by user)
The current LLM is **text-only** (verified — no `vision` capability) and **cannot** read images or generate them (Ollama LLMs don't do image gen at all — that's diffusion models). Plan if resumed: add a separate vision model (`qwen2.5vl:7b` discussed) — upload image → vision model describes it → inject description as context for the text model. Frontend: upload button in `ChatInput.tsx`. Backend: a `/vision` endpoint. **User explicitly said to skip image work for now.**

### 2. CPU TTS engine (Piper) for GPU-less machines
See "CPU-only fallback" above. Not implemented; would be a config-selectable engine.

### 3. WebSocket upgrade
Still HTTP + SSE. Only needed if moving to full-duplex / barge-in voice. Not required yet.

### 4. Intra-sentence streaming TTS (next perf win, optional)
Sentence-level streaming + latent caching are done. The next level is XTTS `inference_stream()` to stream audio chunks *within* a sentence, plus incremental playback on the frontend (MediaSource/Web Audio). High complexity, can't test without GPU — only worth it if first-audio latency still feels high after the current optimizations.

**Note:** speaker-latent caching (previously listed here as a TODO) is now **implemented** — see Performance work above.

---

## Known constraints / gotchas

- **`.env` is the source of truth** for the model name, not the README.
- Run backend commands from **cmd** (PowerShell PATH issue), or activate the venv.
- PyTorch CUDA wheels require **Python 3.11** here — 3.13 is unsupported for torch CUDA.
- TTS needs a `voices/default.*` clip **and** ffmpeg on PATH before it works.
- Ollama "address in use" on `ollama serve` = already running, ignore.
- Keep LLM context tight (last 8 messages) — long context slows generation and can degrade smaller models.
- VRAM budget on the 4070 running all three at once (~8B LLM + Whisper + XTTS) is tight (~9GB); if OOM, move Whisper to CPU (`WHISPER_DEVICE=cpu`).
- Devices default to `auto` — no need to set `cuda`/`cpu` per machine. Override only to force one.
- The XTTS fast path (`model.inference()` with cached latents) falls back to `tts_to_file` if Coqui's internal API differs; a `[tts] fast path unavailable …` log line means the fallback is active (still correct, just slower).

---

## Environment variables

**backend/.env** (current)
```
OLLAMA_HOST=http://localhost:11434
MODEL_NAME=qwen3:8b
SUMMARIZE_AFTER=12
KEEP_RECENT=6

# LLM generation / performance
KEEP_ALIVE=30m
NUM_CTX=4096
NUM_PREDICT=400
TEMPERATURE=0.8
WARM_UP_ON_START=true
WARM_UP_STT=true
WARM_UP_TTS=true            # auto-skips if torch isn't installed

# Speech-to-text (faster-whisper) — 'auto' = GPU if present, else CPU
WHISPER_MODEL=base          # tiny/base/small/medium/large-v3
WHISPER_DEVICE=auto         # auto / cuda / cpu
WHISPER_COMPUTE_TYPE=auto   # auto → float16 (gpu) / int8 (cpu)
WHISPER_BEAM_SIZE=1         # 1 = fastest (greedy); raise to 5 for accuracy
# WHISPER_LANGUAGE=zh        # unset = auto-detect

# Text-to-speech (XTTS v2 voice cloning) — 'auto' = GPU if present, else CPU
TTS_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
TTS_DEVICE=auto
TTS_LANGUAGE=en             # e.g. zh-cn for Chinese
TTS_TEMPERATURE=0.7
VOICES_DIR=voices
DEFAULT_VOICE=default
```

**frontend/.env.local**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```
