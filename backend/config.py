from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    model_name: str = "mythomax-l2:13b"
    summarize_after: int = 12
    keep_recent: int = 6

    # ── LLM generation / performance ──
    keep_alive: str = "30m"      # how long Ollama keeps the model in VRAM
    num_ctx: int = 4096          # context window — keep tight for speed
    num_predict: int = 400       # max tokens per reply (caps rambling)
    temperature: float = 0.8
    warm_up_on_start: bool = True  # preload LLM into VRAM at startup
    warm_up_stt: bool = True       # preload Whisper at startup
    warm_up_tts: bool = True       # preload XTTS at startup

    # ── Speech-to-text (faster-whisper) ──
    whisper_model: str = "base"            # tiny / base / small / medium / large-v3
    whisper_device: str = "auto"           # auto / cuda / cpu  (auto picks GPU if present)
    whisper_compute_type: str = "auto"     # auto / float16 (gpu) / int8 (cpu) / float32
    whisper_language: str | None = None    # None = auto-detect, or "zh", "en", etc.
    whisper_beam_size: int = 1             # 1 = fastest (greedy); raise to 5 for accuracy

    # ── Text-to-speech (XTTS v2 voice cloning) ──
    tts_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    tts_device: str = "auto"             # auto / cuda / cpu  (auto picks GPU if present)
    tts_language: str = "en"             # default speech language, e.g. "en", "zh-cn"
    tts_temperature: float = 0.7         # XTTS sampling temperature
    voices_dir: str = "voices"           # folder holding reference .wav clips
    default_voice: str = "default"       # filename (no .wav) used when none specified

    model_config = {"env_file": ".env"}


settings = Settings()
