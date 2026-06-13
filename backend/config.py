from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    model_name: str = "mythomax-l2:13b"
    summarize_after: int = 12
    keep_recent: int = 6

    # LLM generation / performance
    keep_alive: str = "30m"      # how long Ollama keeps the model in VRAM
    num_ctx: int = 4096          # context window; keep tight for speed
    num_predict: int = 400       # max tokens per reply (caps rambling)
    temperature: float = 0.8
    ollama_think: bool | str = False  # disable hidden thinking unless explicitly enabled
    warm_up_on_start: bool = True  # preload LLM into VRAM at startup
    warm_up_stt: bool = True       # preload Whisper at startup
    warm_up_tts: bool = True       # preload CosyVoice3 at startup

    # Image understanding (Ollama vision model)
    vision_model: str = ""
    vision_keep_alive: str = "10m"
    vision_num_ctx: int = 4096
    vision_num_predict: int = 700
    vision_max_image_mb: int = 8

    # Image generation (ComfyUI + Flux Schnell)
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_checkpoint: str = "flux1-schnell-fp8.safetensors"
    comfyui_workflow_path: str = ""
    image_gen_width: int = 768
    image_gen_height: int = 512
    image_gen_steps: int = 4
    image_gen_cfg: float = 1.0
    image_gen_sampler: str = "euler"
    image_gen_scheduler: str = "simple"
    image_gen_timeout: int = 300
    image_gen_reference_denoise: float = 0.82

    # Speech-to-text (faster-whisper)
    whisper_model: str = "base"            # tiny / base / small / medium / large-v3
    whisper_device: str = "auto"           # auto / cuda / cpu  (auto picks GPU if present)
    whisper_compute_type: str = "auto"     # auto / float16 (gpu) / int8 (cpu) / float32
    whisper_language: str | None = None    # None = auto-detect, or "zh", "en", etc.
    whisper_beam_size: int = 1             # 1 = fastest (greedy); raise to 5 for accuracy

    # Text-to-speech (CosyVoice3 voice cloning)
    tts_model: str = "cosyvoice3"
    tts_device: str = "auto"             # auto / cuda / cpu  (auto picks GPU if present)
    tts_language: str = "en"             # default speech language, e.g. "en", "zh-cn"
    voices_dir: str = "voices"           # folder holding reference .wav clips
    default_voice: str = "default"       # filename (no .wav) used when none specified
    cosyvoice_repo_dir: str = "vendor/CosyVoice"
    cosyvoice_model_dir: str = "pretrained_models/Fun-CosyVoice3-0.5B"
    cosyvoice_model_repo: str = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    cosyvoice_auto_download: bool = True
    cosyvoice_mode: str = "zero_shot"
    cosyvoice_prompt_text: str = ""
    cosyvoice_system_prompt: str = "You are a helpful assistant."
    cosyvoice_speed: float = 1.0
    cosyvoice_fp16: bool | str = True
    cosyvoice_prefix_language_tokens: bool = False
    cosyvoice_text_frontend: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
