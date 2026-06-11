from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    model_name: str = "mythomax-l2:13b"
    summarize_after: int = 12
    keep_recent: int = 6

    model_config = {"env_file": ".env"}


settings = Settings()
