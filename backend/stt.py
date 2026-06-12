"""Speech-to-text via faster-whisper.

The Whisper model is loaded lazily on first use and cached. Transcription is
CPU/GPU-bound and blocking, so callers should run `transcribe()` in a thread
(see main.py's use of `run_in_threadpool`).
"""

from config import settings

_model = None


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _resolve() -> tuple[str, str]:
    """Resolve 'auto' device/compute to concrete values for the host."""
    device = settings.whisper_device
    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    compute = settings.whisper_compute_type
    if compute == "auto":
        # float16 needs a GPU; int8 is the fast/safe choice on CPU
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        device, compute = _resolve()
        print(f"[stt] loading Whisper '{settings.whisper_model}' on {device} ({compute})")
        _model = WhisperModel(
            settings.whisper_model,
            device=device,
            compute_type=compute,
        )
    return _model


def transcribe(audio_path: str) -> dict:
    """Transcribe an audio file. Returns {text, language}."""
    model = _get_model()
    segments, info = model.transcribe(
        audio_path,
        language=settings.whisper_language,  # None = auto-detect
        beam_size=settings.whisper_beam_size,
        vad_filter=True,           # skip silence — faster, cleaner output
        condition_on_previous_text=False,  # each utterance is independent — faster
    )
    text = "".join(seg.text for seg in segments).strip()
    return {"text": text, "language": info.language}


def warm_up() -> None:
    """Load the model + init CUDA kernels so the first transcription is fast."""
    model = _get_model()
    try:
        import numpy as np

        # Transcribe 1s of silence to trigger lazy CUDA/kernel initialization
        list(model.transcribe(np.zeros(16000, dtype="float32"), beam_size=1)[0])
    except Exception:
        pass  # model is at least loaded
