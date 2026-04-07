# Wolle Economy Viewer

Streamlit-приложение для анализа юнит-экономики заказов с Яндекс Маркета.
Данные читаются из PostgreSQL (`e_commerce.e_com`).

## Требования

- Python 3.12+ (для разработки)
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
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
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
app.py            # точка входа Streamlit
economics.py      # расчёт метрик
db/               # подключение и SQL-запросы
pages/            # страницы Streamlit
Dockerfile        # образ для продакшена
docker-compose.yml
```

Подробнее об архитектуре данных и логике метрик — в [CLAUDE.md](CLAUDE.md).
