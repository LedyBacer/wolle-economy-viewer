# Wolle Economy Viewer

Streamlit-приложение для анализа юнит-экономики заказов с Яндекс Маркета.
Данные читаются из PostgreSQL (`e_commerce`, схема `e_com`).

## Требования

- Python 3.12+
- Docker и Docker Compose (для продакшена)
- Доступ к PostgreSQL с базой `e_commerce`

## Конфигурация

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

```
DB_HOST=...
DB_PORT=5432
DB_NAME=e_commerce
DB_USER=...
DB_PASSWORD=...
```

> Если PostgreSQL поднят на хост-машине рядом с Docker, используйте
> `DB_HOST=host.docker.internal` (macOS/Windows) или IP хоста (Linux).

## Разработка

```bash
python3.12 -m venv .venv

# Установка пакета в редактируемом режиме (включает dev-зависимости)
.venv/bin/pip install -e .[dev]

# Запуск
.venv/bin/streamlit run src/wolle_economy/ui/app.py

# Тесты
.venv/bin/pytest
```

Приложение будет доступно на http://localhost:8501.

## Продакшен (Docker Compose)

Сборка и запуск:

```bash
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f
```

Остановка:

```bash
docker compose down
```

Обновление после `git pull`:

```bash
docker compose up -d --build
```

Приложение слушает порт `8501`. Меняйте маппинг в [docker-compose.yml](docker-compose.yml) при необходимости. Для публикации наружу поставьте перед контейнером reverse proxy (nginx/Caddy/Traefik) с TLS.

## Структура

```
src/wolle_economy/
  ui/app.py       # точка входа Streamlit
  domain/         # расчёт метрик, загрузка данных
  db/             # подключение и SQL-запросы
  ui/pages/       # страницы Streamlit
tests/            # pytest-тесты (53 теста, без БД)
Dockerfile
docker-compose.yml
pyproject.toml    # зависимости, ruff, mypy, pytest
```

Подробнее об архитектуре данных и логике метрик — в [CLAUDE.md](CLAUDE.md).
