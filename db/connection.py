import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}"
        f"/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


def test_connection() -> tuple[bool, str]:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Подключение успешно"
    except Exception as e:
        return False, f"Ошибка подключения: {e}"
