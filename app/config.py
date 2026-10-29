"""
Centralize configuration
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM Configuration
    ollama_api_key: str

    #Local model
    primary_model: str = "qwen3:8b"
    fallback_model: str = "qwen3:8b"

    # primary_model: str = "gemma4:31b"
    # fallback_model: str = "gemma4:31b"

    # Langsmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "RAG"

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    rate_limit: str = "20/minute"
    cache_ttl_seconds: int = 300
    max_retries: int = 3

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    # Cached settings instance - loaded once and reused everywhere
    return Settings()
