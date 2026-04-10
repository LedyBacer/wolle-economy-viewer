"""
Конфигурация приложения.
Все параметры читаются из переменных окружения (файл .env в корне проекта).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Подключение к БД
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_name: str
    db_user: str
    db_password: str

    # TTL кэша Streamlit (секунды)
    cache_ttl: int = Field(default=3600)

    # Магазины без полного отчёта о марже ЯМ.
    # Данные для них носят справочный характер и исключаются из обзорных KPI.
    low_quality_sellers: frozenset[str] = frozenset({"WolleBuy"})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает единственный экземпляр Settings (singleton)."""
    return Settings()  # type: ignore[call-arg]
