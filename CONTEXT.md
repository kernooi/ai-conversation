# AI Conversation — Project Context

> Handoff document for any AI assistant continuing this project.
> Read this fully before touching any file.

---

## What this project is

A local, private AI voice + chat assistant. The end goal is to clone a person's voice and have a real-time conversation with them — text and spoken. Everything runs locally (no cloud APIs).

**Current phase:** Text chat is working end-to-end. Voice pipeline (STT + TTS) has not been started yet.

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| LLM | MythoMax-L2 13B Q4_K_S via Ollama | Better roleplay/character consistency than instruct models |
| Backend | FastAPI (Python) | Async, easy streaming, simple to extend |
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind) | Modern React with good streaming support |
| STT | Faster Whisper / Whisper.cpp | Planned — not built yet |
| TTS | XTTS v2 | Planned — not built yet (voice cloning) |

**Hardware:** RTX 4070. MythoMax 13B uses ~7–10GB VRAM.

---

## Repository structure

```
ai-conversation/
├── backend/
│   ├── main.py            # FastAPI app — all endpoints
│   ├── memory.py          # Session memory management
│   ├── ollama_client.py   # Ollama REST API wrapper (httpx, async)
│   ├── config.py          # Pydantic settings (reads .env)
│   ├── requirements.txt
│   ├── .env               # Real config (gitignored)
│   └── .env.example       # Template
└── frontend/
    └── app/
        ├── page.tsx                    # Main chat page, session state
        ├── lib/
        │   ├── api.ts                  # sendMessage(), streamMessage(), clearSession()
        │   └── types.ts                # Message, Session, ChatRequest, ChatResponse
        └── components/
            ├── ChatWindow.tsx          # Scrollable message list
            ├── MessageBubble.tsx       # User/AI bubbles with streaming cursor
            └── ChatInput.tsx          # Auto-resize textarea, mic placeholder
```

---

## How to run

**Prerequisites:** Ollama installed, Python 3.10+, Node 18+

**Terminal 1 — Ollama (usually auto-starts on Windows)**
```cmd
ollama list   # verify model is present
```

**Terminal 2 — Backend**
```cmd
cd backend
python -m pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Verify: `http://localhost:8000/health` must return `"model_available": true`

**Terminal 3 — Frontend**
```cmd
cd frontend
npm install
npm run dev
```
Open: `http://localhost:3000`

---

## Backend design

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Check Ollama connection + model availability |
| POST | `/chat/stream` | **Primary endpoint** — SSE streaming response |
| POST | `/chat` | Fallback non-streaming endpoint |
| DELETE | `/session/{id}` | Clear session memory |

### Memory system

Each session stores:
```python
SessionData:
    summary: str       # Long-term: periodic summary of old messages
    messages: list     # Short-term: recent message history
```

Context sent to the model = system prompt + last 8 messages only.
This keeps token usage well within the safe range for a 13B model (2K–4K tokens).

**Summarization trigger:** When a session exceeds `SUMMARIZE_AFTER` (default 12) messages,
the oldest `N - KEEP_RECENT` messages are summarized via a second Ollama call and stored
as `summary`. The summary is injected into the system prompt on every subsequent turn.

### Streaming (SSE)

`POST /chat/stream` uses Server-Sent Events:
- Each chunk: `data: "token"\n\n` (JSON-encoded string)
- Errors: `data: {"error": "..."}\n\n`
- End: `data: [DONE]\n\n`

Memory persistence happens in a `BackgroundTask` after the stream completes —
this avoids blocking the response and survives client disconnection.

### Ollama client

Uses raw `httpx` async HTTP calls (not the `ollama` Python package) for reliability.
Calls `POST /api/chat` for chat, `POST /api/generate` for summarization.

---

## Frontend design

### Streaming UX

1. User sends message → user bubble appears immediately
2. Empty AI bubble added with blinking cursor (no typing dots)
3. Tokens stream in and append to the AI bubble in real time
4. Inline cursor disappears when stream ends
5. Input is disabled for the entire stream duration

### Session management

Session ID is a `uuidv4` generated once per page load. It's sent with every request
so the backend can maintain memory across turns. "New chat" button calls
`DELETE /session/{id}` to wipe backend memory, then resets frontend state.

### API calls (`api.ts`)

- `streamMessage()` — async generator, yields string chunks from SSE
- `sendMessage()` — regular fetch, returns full response (fallback)
- `clearSession()` — DELETE call for new chat

---

## What is NOT built yet

### 1. Image / vision support

The current model (MythoMax-L2) is **text-only**. Vision was discussed but not implemented.

**Agreed plan:** Use `qwen2.5vl:7b` as a vision handler alongside MythoMax.
- User uploads image → backend sends to `qwen2.5vl:7b` for description
- Description text is injected as context into the MythoMax conversation

**To implement:**
- Frontend: image upload button in `ChatInput.tsx`, preview in bubble
- Backend: new `POST /vision` endpoint that calls Ollama with base64 image
- Backend: inject vision result as a user-facing context message in session memory
- Ollama: `ollama pull qwen2.5vl:7b`

### 2. Voice pipeline (STT)

Not started. Planned stack:
- **Faster Whisper** or **Whisper.cpp** for speech-to-text
- Push-to-talk button already exists in `ChatInput.tsx` (currently disabled, labeled "coming soon")
- When implemented: button held → record audio → send to STT endpoint → text injected into chat input

### 3. Voice pipeline (TTS)

Not started. Planned stack:
- **XTTS v2** for voice cloning and text-to-speech
- AI responses should be spoken back using a cloned voice
- Integration point: after each AI message completes streaming, send text to TTS endpoint, play audio

### 4. WebSocket upgrade

Currently using HTTP + SSE. For full duplex voice conversation, upgrading to WebSockets
was mentioned. Not needed until voice pipeline is built.

---

## Known constraints

- MythoMax 13B is sensitive to long context — never dump full history. Always trim to last 8 messages.
- MythoMax benefits from structured roleplay-style system prompts.
- Summarization adds latency on the trigger turn (every ~12 messages). This is acceptable.
- Ollama on Windows auto-starts as a system tray app — `ollama serve` will fail if it's already running (that error is normal and expected).
- Frontend runs on Windows with PowerShell but Python/pip must be run from cmd (PATH issue on this machine).

---

## Environment variables

**backend/.env**
```
OLLAMA_HOST=http://localhost:11434
MODEL_NAME=nollama/mythomax-l2-13b:Q4_K_S
SUMMARIZE_AFTER=12
KEEP_RECENT=6
```

**frontend/.env.local**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```
