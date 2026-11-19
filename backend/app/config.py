from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)
    setup_token: str | None = Field(default=None, min_length=32)
    cors_origins: list[str] = ["http://localhost:5173"]
    access_token_minutes: int = Field(default=30, ge=1, le=1440)
    groq_api_key: SecretStr | None = None
    groq_model: str = Field(default="openai/gpt-oss-20b", min_length=1, max_length=100)
    ai_timeout_seconds: int = Field(default=30, ge=5, le=60)
    groq_vision_model: str = Field(default="qwen/qwen3.8-27b", min_length=1, max_length=100)
    triage_requests_per_minute: int = Field(default=5, ge=1, le=60)

    @field_validator("jwt_secret")
    @classmethod
    def reject_placeholder(cls, value: str) -> str:
        if value.startswith("replace-with-"):
            raise ValueError("Generate a unique JWT_SECRET before starting the API")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
