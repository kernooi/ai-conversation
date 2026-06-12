# Voice reference clips

Drop reference audio files here to clone voices with XTTS v2.

## Requirements for a good clone
- **Format:** `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, or `.aac` — non-wav files
  are auto-converted to wav on first use and cached here (needs ffmpeg on PATH).
- **Length:** 6–30 seconds is the sweet spot
- **Content:** clean speech, one speaker, minimal background noise/music
- **Naming:** the filename (without extension) is the voice name

## Example
```
voices/
├── default.mp3     ← used when no voice is specified (DEFAULT_VOICE in .env)
├── alice.mp3       ← request with voice="alice"
└── friend.wav      ← request with voice="friend"
```

The frontend's voice picker lists every supported file here automatically (via `GET /voices`).

## ffmpeg
Conversion uses ffmpeg under the hood. If it's not installed:
- **Windows:** `winget install ffmpeg` (then reopen the terminal)
- Verify with `ffmpeg -version`

You do **not** need to convert files yourself — just drop in the `.mp3`.
