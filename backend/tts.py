"""Text-to-speech via FunAudioLLM CosyVoice3.

CosyVoice3 is used in zero-shot voice cloning mode. Put a 3-30s reference clip
in `voices/` and provide the matching transcript either as `voices/<voice>.txt`
or via `COSYVOICE_PROMPT_TEXT` in `.env`.

The frontend still calls the same `/tts` endpoint; this module owns the
CosyVoice3 backend engine.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from hashlib import sha1
from pathlib import Path

from config import settings

_model = None
_model_lock = threading.Lock()
_synth_lock = threading.Lock()
_speaker_cache_lock = threading.Lock()
_speaker_cache: dict[tuple[str, str, int, int, str, bool], str] = {}

SUPPORTED_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac")
REQUIRED_MODEL_FILES = (
    "cosyvoice3.yaml",
    "llm.pt",
    "llm.rl.pt",
    "flow.pt",
    "hift.pt",
    "campplus.onnx",
    "speech_tokenizer_v3.onnx",
    "speech_tokenizer_v3.batch.onnx",
)


class TTSConfigError(RuntimeError):
    """Raised when TTS is not configured enough to run."""


def _backend_dir() -> Path:
    return Path(__file__).resolve().parent


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return _backend_dir() / candidate


def _truthy(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _cosyvoice_root() -> Path:
    return _resolve_path(settings.cosyvoice_repo_dir)


def _configure_import_path() -> None:
    root = _cosyvoice_root()
    matcha = root / "third_party" / "Matcha-TTS"
    for path in (root, matcha):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _import_automodel():
    root = _cosyvoice_root()
    if not root.exists():
        raise TTSConfigError(
            f"CosyVoice repo not found at {root}. Clone "
            "https://github.com/FunAudioLLM/CosyVoice with submodules, or update "
            "COSYVOICE_REPO_DIR."
        )
    _configure_import_path()
    from cosyvoice.cli.cosyvoice import AutoModel

    return AutoModel


def available() -> bool:
    """True if the CosyVoice source and imports are available."""
    try:
        _import_automodel()
        import torch  # noqa: F401
        import torchaudio  # noqa: F401

        return True
    except Exception:
        return False


def _model_dir() -> Path:
    configured = _resolve_path(settings.cosyvoice_model_dir)
    missing = [name for name in REQUIRED_MODEL_FILES if not (configured / name).exists()]
    if configured.exists() and not missing:
        return configured

    if not settings.cosyvoice_auto_download:
        raise TTSConfigError(
            f"CosyVoice3 model not found at {configured}. Download "
            f"{settings.cosyvoice_model_repo} there, or set COSYVOICE_AUTO_DOWNLOAD=true."
        )

    from huggingface_hub import snapshot_download

    configured.mkdir(parents=True, exist_ok=True)
    print(
        f"[tts] downloading CosyVoice3 model {settings.cosyvoice_model_repo} to {configured}; "
        f"missing={missing}",
        flush=True,
    )
    snapshot_download(repo_id=settings.cosyvoice_model_repo, local_dir=str(configured))
    if not (configured / "cosyvoice3.yaml").exists():
        raise TTSConfigError(f"Downloaded model is missing cosyvoice3.yaml: {configured}")
    return configured


def _get_model():
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model
        AutoModel = _import_automodel()
        model_dir = _model_dir()
        print(f"[tts] loading CosyVoice3 from {model_dir}", flush=True)
        _model = AutoModel(
            model_dir=str(model_dir),
            fp16=_truthy(settings.cosyvoice_fp16),
            load_vllm=False,
            load_trt=False,
        )
        return _model


def list_voices() -> list[str]:
    if not os.path.isdir(settings.voices_dir):
        return []
    names = {
        os.path.splitext(f)[0]
        for f in os.listdir(settings.voices_dir)
        if f.lower().endswith(SUPPORTED_EXTS)
    }
    return sorted(names)


def _find_voice_file(voice: str) -> Path:
    for ext in SUPPORTED_EXTS:
        path = _resolve_path(settings.voices_dir) / f"{voice}{ext}"
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"Voice '{voice}' not found in {settings.voices_dir}/. "
        f"Add a {' / '.join(SUPPORTED_EXTS)} file, or pick from {list_voices()}."
    )


def _ensure_wav(src_path: Path) -> Path:
    """Return a wav prompt path. CosyVoice uses torchaudio soundfile loading."""
    if src_path.suffix.lower() == ".wav":
        return src_path

    wav_path = src_path.with_suffix(".wav")
    if wav_path.is_file() and wav_path.stat().st_mtime >= src_path.stat().st_mtime:
        return wav_path

    from pydub import AudioSegment

    audio = AudioSegment.from_file(src_path)
    audio = audio.set_channels(1).set_frame_rate(24000)
    audio.export(wav_path, format="wav")
    return wav_path


def _voice_prompt_text(voice: str, voice_path: Path) -> str:
    transcript_path = voice_path.with_suffix(".txt")
    if transcript_path.is_file():
        prompt = transcript_path.read_text(encoding="utf-8").strip()
    else:
        prompt = settings.cosyvoice_prompt_text.strip()

    if not prompt:
        raise TTSConfigError(
            "CosyVoice3 zero-shot mode needs the transcript of the reference voice. "
            f"Create {transcript_path.name} next to the voice file, or set "
            "COSYVOICE_PROMPT_TEXT in backend/.env."
        )

    if "<|endofprompt|>" in prompt:
        return prompt
    system_prompt = settings.cosyvoice_system_prompt.strip()
    if not system_prompt:
        return prompt
    return f"{system_prompt}<|endofprompt|>{prompt}"


def _normalize_text(text: str, language: str | None) -> str:
    clean = text.strip()
    if not clean:
        return clean

    lang = (language or settings.tts_language).lower()
    if settings.cosyvoice_prefix_language_tokens:
        if lang.startswith("zh") and not clean.startswith("<|"):
            return f"<|zh|>{clean}"
        if lang.startswith("en") and not clean.startswith("<|"):
            return f"<|en|>{clean}"
    return clean


def _speaker_cache_key(
    voice_name: str,
    prompt_wav: Path,
    prompt_text: str,
    text_frontend: bool,
) -> tuple[str, str, int, int, str, bool]:
    stat = prompt_wav.stat()
    prompt_hash = sha1(prompt_text.encode("utf-8")).hexdigest()
    return (
        voice_name,
        str(prompt_wav.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
        prompt_hash,
        text_frontend,
    )


def _zero_shot_spk_id(model, voice_name: str, prompt_wav: Path, prompt_text: str, text_frontend: bool) -> str:
    """Cache CosyVoice3 prompt audio/text features for a reference voice."""
    key = _speaker_cache_key(voice_name, prompt_wav, prompt_text, text_frontend)
    cached = _speaker_cache.get(key)
    if cached:
        return cached

    with _speaker_cache_lock:
        cached = _speaker_cache.get(key)
        if cached:
            return cached

        cache_id = f"voice_{sha1('|'.join(map(str, key)).encode('utf-8')).hexdigest()[:20]}"
        started = time.perf_counter()
        model.add_zero_shot_spk(prompt_text, str(prompt_wav), cache_id)
        _speaker_cache[key] = cache_id
        print(
            "[tts] cached CosyVoice3 speaker "
            f"voice={voice_name} elapsed={time.perf_counter() - started:.2f}s",
            flush=True,
        )
        return cache_id


def synthesize(
    text: str,
    out_path: str,
    voice: str | None = None,
    language: str | None = None,
) -> str:
    """Synthesize `text` to `out_path` using CosyVoice3 zero-shot cloning."""
    model = _get_model()
    voice_name = voice or settings.default_voice
    voice_path = _find_voice_file(voice_name)
    prompt_wav = _ensure_wav(voice_path)
    prompt_text = _voice_prompt_text(voice_name, prompt_wav)
    tts_text = _normalize_text(text, language)
    started = time.perf_counter()

    with _synth_lock:
        import torch
        import torchaudio

        outputs = []
        mode = settings.cosyvoice_mode.lower()
        text_frontend = settings.cosyvoice_text_frontend
        if mode == "cross_lingual":
            zero_shot_spk_id = _zero_shot_spk_id(model, voice_name, prompt_wav, prompt_text, text_frontend)
            generator = model.inference_cross_lingual(
                tts_text,
                str(prompt_wav),
                zero_shot_spk_id=zero_shot_spk_id,
                stream=False,
                speed=settings.cosyvoice_speed,
                text_frontend=text_frontend,
            )
        elif mode == "instruct":
            generator = model.inference_instruct2(
                tts_text,
                prompt_text,
                str(prompt_wav),
                stream=False,
                speed=settings.cosyvoice_speed,
                text_frontend=text_frontend,
            )
        else:
            zero_shot_spk_id = _zero_shot_spk_id(model, voice_name, prompt_wav, prompt_text, text_frontend)
            generator = model.inference_zero_shot(
                tts_text,
                prompt_text,
                str(prompt_wav),
                zero_shot_spk_id=zero_shot_spk_id,
                stream=False,
                speed=settings.cosyvoice_speed,
                text_frontend=text_frontend,
            )

        for item in generator:
            outputs.append(item["tts_speech"].detach().cpu())

        if not outputs:
            raise RuntimeError("CosyVoice3 returned no audio")

        speech = outputs[0] if len(outputs) == 1 else torch.cat(outputs, dim=1)
        torchaudio.save(out_path, speech, model.sample_rate)

    print(
        "[tts] cosyvoice3 synth "
        f"elapsed={time.perf_counter() - started:.2f}s "
        f"chars={len(text)} voice={voice_name} mode={settings.cosyvoice_mode}",
        flush=True,
    )
    return out_path


def warm_up() -> None:
    """Load CosyVoice3 and run a tiny synthesis if the default voice is ready."""
    if not available():
        print("[tts] warm-up skipped: CosyVoice3 source/deps not available", flush=True)
        return
    _get_model()
    try:
        import tempfile
        import uuid

        out = os.path.join(tempfile.gettempdir(), f"warm_{uuid.uuid4().hex}.wav")
        synthesize("\u4f60\u597d\u3002", out, settings.default_voice, "zh-cn")
        os.remove(out)
    except Exception as e:
        print(f"[tts] warm-up skipped: {e}", flush=True)
