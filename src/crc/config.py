"""Configuration centralisee, chargee depuis le fichier .env."""
from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    random_seed: int = 42
    time_granularity_minutes: int = 30
    history_start_date: date
    history_end_date: date

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def periods_per_day(self) -> int:
        return 24 * 60 // self.time_granularity_minutes


@lru_cache
def get_settings() -> Settings:
    return Settings()