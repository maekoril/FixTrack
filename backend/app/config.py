from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)
    setup_token: str | None = Field(default=None, min_length=32)
    cors_origins: list[str] = ["http://localhost:5173"]
    access_token_minutes: int = Field(default=30, ge=1, le=1440)

    @field_validator("jwt_secret")
    @classmethod
    def reject_placeholder(cls, value: str) -> str:
        if value.startswith("replace-with-"):
            raise ValueError("Generate a unique JWT_SECRET before starting the API")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
