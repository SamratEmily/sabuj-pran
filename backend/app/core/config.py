from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads backend/.env or the repo-root .env when running outside Docker.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "development"
    database_url: str = "mysql+pymysql://bms:bms@localhost:3306/bms?charset=utf8mb4"
    test_database_url: str = "mysql+pymysql://bms:bms@localhost:3306/bms_test?charset=utf8mb4"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bcrypt_rounds: int = 12
    cors_origins: str = "http://localhost:5173"
    timezone: str = "Asia/Dhaka"

    @model_validator(mode="after")
    def _check_secret(self) -> Self:
        if self.is_production and len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
