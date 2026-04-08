"""
Подключение к PostgreSQL через SQLAlchemy.
Engine создаётся один раз (singleton через lru_cache) и переиспользуется
между запросами — пул соединений работает корректно.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Возвращает единственный экземпляр SQLAlchemy Engine."""
    s = get_settings()
    url = (
        f"postgresql+psycopg2://{quote_plus(s.db_user)}:{quote_plus(s.db_password)}"
        f"@{s.db_host}:{s.db_port}/{s.db_name}"
    )
    return create_engine(url, pool_pre_ping=True)


def test_connection() -> tuple[bool, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Подключение успешно"
    except OSError as e:
        return False, f"Ошибка подключения (сеть): {e}"
    except SQLAlchemyError as e:
        return False, f"Ошибка подключения (SQLAlchemy): {e}"
