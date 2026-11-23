from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    service_token: str = ""
    frappe_url: str = ""
    frappe_api_key: str = ""
    frappe_api_secret: str = ""
    database_url: str = "sqlite:///./data/ai_engine.db"
    llm_provider: str = "mock"
    openai_model: str = "o4-mini"
    gemini_model: str = "gemini-3.5-flash"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    request_timeout_seconds: float = 20
    max_message_chars: int = 4000
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
