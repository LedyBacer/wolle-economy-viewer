# Wolle Economy Viewer

Streamlit-приложение для анализа юнит-экономики заказов с маркетплейсов
(Яндекс Маркет, МегаМаркет, Sportmaster, Wildberries, Ozon).
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
CACHE_TTL=3600
```

> Если PostgreSQL поднят на хост-машине рядом с Docker, используйте
> `DB_HOST=host.docker.internal` (macOS/Windows) или IP хоста (Linux).

## Разработка

```bash
python3.12 -m venv .venv

# Установка пакета в редактируемом режиме (включает dev-зависимости)
.venv/bin/pip install -e .[dev]

# Запуск Streamlit
.venv/bin/streamlit run src/wolle_economy/ui/app.py

# Запуск API
.venv/bin/uvicorn wolle_economy.api.app:app --host 0.0.0.0 --port 8506

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

В одном Docker Compose запускаются два процесса из общего образа:

- Streamlit-интерфейс — порт `8501`;
- API — порт `8506`.

Для публикации наружу поставьте перед контейнерами reverse proxy
(nginx/Caddy/Traefik) с TLS и направьте `/api/` на API-контейнер.

## API экономики

Ручка без авторизации возвращает одну строку из режима
«Показать все колонки». Маркетплейс определяется по связи магазина
с `platform_sellers`.

```http
GET /api/v1/order-economics?seller_id=1&order_id=12345&offer_id=ABC
```

Значения `order_id` и `offer_id` сравниваются точно. Даты возвращаются
в ISO 8601, отсутствующие значения — `null`, денежные значения — JSON-числа.

API поддерживает in-memory stale-while-revalidate кэш:

- полный снимок всех маркетплейсов обновляется в фоне раз в `CACHE_TTL`
  секунд (по умолчанию раз в час);
- найденная в снимке строка возвращается сразу с заголовком `X-Cache: HIT`,
  после чего точечно проверяется в БД;
- если ключа в снимке нет, API синхронно читает БД, возвращает
  `X-Cache: MISS` и сохраняет результат;
- новый полный снимок заменяет предыдущий атомарно; при ошибке обновления
  старые данные продолжают обслуживаться.

- `200` — найдена одна строка;
- `404` — магазин или строка не найдены;
- `409` — найдено несколько строк;
- `422` — параметры отсутствуют или невалидны;
- `503` — база данных недоступна.

Интерактивная документация после запуска доступна по адресу
`http://localhost:8506/docs`.

## Структура

```
src/wolle_economy/
  api/app.py      # точка входа FastAPI
  ui/app.py       # точка входа Streamlit
  domain/         # расчёт метрик, загрузка данных
  db/             # подключение и SQL-запросы
  ui/pages/       # страницы Streamlit
tests/            # pytest-тесты без обязательного подключения к БД
Dockerfile
docker-compose.yml
pyproject.toml    # зависимости, ruff, mypy, pytest
```

Подробнее об архитектуре данных и логике метрик — в [CLAUDE.md](CLAUDE.md).
