"""Text-to-speech via Coqui XTTS v2, with voice cloning. GPU-optimized.

Voice cloning works from a short reference clip: drop a 6-30s clean audio file
of the target voice into the `voices/` folder (e.g. voices/alice.mp3), then
request voice="alice". XTTS synthesizes new speech in that voice.

Accepted reference formats: .wav .mp3 .m4a .ogg .flac .aac
Non-wav files are auto-converted to wav once and cached next to the original
(requires ffmpeg on PATH).

Performance:
- The model is loaded once and cached (lazy).
- Speaker conditioning latents are computed once per voice and cached, so
  repeated (per-sentence) synthesis skips the expensive speaker-embedding step
  and goes straight to generation. This is the main GPU speed win.
- Synthesis is serialized with a lock (one GPU job at a time) and is blocking,
  so callers run `synthesize()` in a thread (see main.py).
"""

import os
import threading

from config import settings

_tts = None
# XTTS runs on a single GPU; serialize synthesis so concurrent per-sentence
# requests don't collide on the model / device.
_synth_lock = threading.Lock()
# voice-clip path+mtime -> (gpt_cond_latent, speaker_embedding)
_latent_cache: dict[str, tuple] = {}

SUPPORTED_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac")


def available() -> bool:
    """True if the TTS stack (torch + Coqui) is importable in this env."""
    try:
        import torch  # noqa: F401
        from TTS.api import TTS  # noqa: F401

        return True
    except Exception:
        return False


def _resolve_device() -> str:
    """Resolve the TTS device. 'auto' picks cuda if available, else cpu."""
    import torch

    if settings.tts_device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if settings.tts_device == "cuda" and not torch.cuda.is_available():
        return "cpu"  # asked for GPU but none present — fall back
    return settings.tts_device


def _get_tts():
    global _tts
    if _tts is None:
        from TTS.api import TTS

        device = _resolve_device()
        note = "" if device == "cuda" else " (slow on CPU)"
        print(f"[tts] loading XTTS on {device}{note}")
        _tts = TTS(settings.tts_model).to(device)
    return _tts


def list_voices() -> list[str]:
    """Available reference voices (filenames without extension) in the voices dir.

    A name appears once even if both e.g. alice.mp3 and a cached alice.wav exist.
    """
    if not os.path.isdir(settings.voices_dir):
        return []
    names = {
        os.path.splitext(f)[0]
        for f in os.listdir(settings.voices_dir)
        if f.lower().endswith(SUPPORTED_EXTS)
    }
    return sorted(names)


def _find_voice_file(voice: str) -> str:
    """Locate the reference clip for `voice`, trying each supported extension."""
    for ext in SUPPORTED_EXTS:
        path = os.path.join(settings.voices_dir, f"{voice}{ext}")
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        f"Voice '{voice}' not found in {settings.voices_dir}/. "
        f"Add a {' / '.join(SUPPORTED_EXTS)} file, or pick from {list_voices()}."
    )


def _ensure_wav(src_path: str) -> str:
    """Return a wav path for `src_path`, converting + caching if it isn't wav."""
    if src_path.lower().endswith(".wav"):
        return src_path

    base = os.path.splitext(src_path)[0]
    wav_path = f"{base}.wav"
    # Reuse a previous conversion if it's newer than the source
    if os.path.isfile(wav_path) and os.path.getmtime(wav_path) >= os.path.getmtime(src_path):
        return wav_path

    from pydub import AudioSegment

    audio = AudioSegment.from_file(src_path)
    # Mono 22.05kHz is plenty for XTTS speaker conditioning
    audio = audio.set_channels(1).set_frame_rate(22050)
    audio.export(wav_path, format="wav")
    return wav_path


def _get_latents(speaker_wav: str):
    """Compute (and cache) XTTS speaker conditioning latents for a voice clip.

    Keyed by path + mtime so replacing the clip transparently recomputes.
    """
    key = f"{speaker_wav}:{os.path.getmtime(speaker_wav)}"
    cached = _latent_cache.get(key)
    if cached is not None:
        return cached

    model = _get_tts().synthesizer.tts_model
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
        audio_path=[speaker_wav]
    )
    _latent_cache[key] = (gpt_cond_latent, speaker_embedding)
    return _latent_cache[key]


def synthesize(text: str, out_path: str, voice: str | None = None,
               language: str | None = None) -> str:
    """Synthesize `text` to a wav file at `out_path` in the cloned voice.

    Fast path: cached speaker latents + low-level XTTS inference.
    Falls back to the simple `tts_to_file` path if the low-level API differs.
    """
    tts = _get_tts()
    speaker_wav = _ensure_wav(_find_voice_file(voice or settings.default_voice))
    lang = language or settings.tts_language

    with _synth_lock:  # one synthesis at a time on the GPU
        try:
            model = tts.synthesizer.tts_model
            gpt_cond_latent, speaker_embedding = _get_latents(speaker_wav)
            out = model.inference(
                text,
                lang,
                gpt_cond_latent,
                speaker_embedding,
                temperature=settings.tts_temperature,
                enable_text_splitting=False,  # sentences are already split upstream
            )
            tts.synthesizer.save_wav(out["wav"], out_path)
        except Exception as e:
            # Internal API changed or unavailable — use the robust public path
            print(f"[tts] fast path unavailable ({e}); using tts_to_file")
            tts.tts_to_file(
                text=text,
                speaker_wav=speaker_wav,
                language=lang,
                file_path=out_path,
            )
    return out_path


def warm_up() -> None:
    """Preload XTTS into VRAM + cache default-voice latents + warm kernels."""
    if not available():
        print("[tts] warm-up skipped: torch/coqui-tts not installed")
        return
    _get_tts()
    try:
        import tempfile
        import uuid

        out = os.path.join(tempfile.gettempdir(), f"warm_{uuid.uuid4().hex}.wav")
        # Goes through the fast path → also primes the latent cache
        synthesize("Hello.", out, settings.default_voice)
        os.remove(out)
    except FileNotFoundError:
        pass  # no default voice yet — model is at least loaded into VRAM
    except Exception:
        pass
