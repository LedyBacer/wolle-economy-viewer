"""
Настройка логирования для всего приложения.
Вызвать один раз при старте (в app.py).
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Настраивает корневой логгер с форматом, пригодным для Streamlit-окружения."""
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Подавляем слишком подробные логи сторонних библиотек
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
