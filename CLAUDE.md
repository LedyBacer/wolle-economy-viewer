# Wolle Economy Viewer

Streamlit-приложение для анализа юнит-экономики заказов с маркетплейса Яндекс Маркет.
Данные берутся исключительно из PostgreSQL.

## Структура проекта

```
app.py              # точка входа Streamlit (st.set_page_config только здесь)
economics.py        # расчёт всех финансовых метрик (чистые функции)
db/
  connection.py     # SQLAlchemy-подключение (env-переменные)
  queries.py        # SQL-запросы: ORDER_ITEMS_SQL, PAYMENT_AGGREGATES_SQL, SELLERS_SQL
pages/
  1_Заказы.py       # таблица заказов с фильтрами и метриками
```

## Команды

```bash
.venv/bin/streamlit run app.py      # запуск
.venv/bin/pip install -r requirements.txt
```

## Переменные окружения

`.env` (скопировать из `.env.example`):
```
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```
База данных: `e_commerce`, схема: `e_com`.

## Архитектура данных

### Ключевые таблицы БД

| Таблица | Что хранит |
|---|---|
| `ya_orders` | Заказы (статус, даты, продавец) |
| `ya_order_items` | Позиции заказов (цены, наценка, расчётные комиссии) |
| `ya_order_margin_report` | Итоговый отчёт ЯМ (sell_price, market_services, статус выплаты) |
| `ya_order_transactions_report` | Скидки и возвраты по позиции |
| `ya_payments_reports` | Транзакции платёжного отчёта (бонусы, штрафы, даты выплат) |
| `platform_sellers` | Продавцы |
| `yandex_feed_items` | Позиции фида (offer_id → product) |
| `unique_product_groups` | Товары (название) |
| `ff_fees` / `socket_adapter_fee` | Стоимость упаковки / переходника |
| `market_modifier_yandex` | Связь товара с тарифами |

### Поток данных

```
ORDER_ITEMS_SQL          →  orders DataFrame (26k строк, 1 строка = 1 позиция заказа)
PAYMENT_AGGREGATES_SQL   →  payments DataFrame (бонусы, штрафы, даты по order_id)
                              ↓ merge по ya_order_id
                         calc_economics()
                              ↓
                         готовый DataFrame со всеми метриками
```

### Логика расчёта ключевых метрик

- `sell_price` = из `ya_order_margin_report.sell_price` — итоговая цена заказа (buyer_payment + субсидия ЯМ)
- `expected_payout` = `sell_price − market_services` — фактический перевод от ЯМ
- `our_costs` = `base_price_total + ff_fee_total + socket_adapter_total` — наши затраты
- `expected_profit` = `expected_payout − our_costs` (без учёта промо)
- `promo_discounts` = наши расходы на промо из баланса баллов (отрицательная сумма, из `ya_payments_reports`)
- `profit` = `expected_payout + promo_discounts − our_costs` (с учётом промо)
- `bonus_points` = субсидия ЯМ (tr.bonuses). **СПРАВОЧНО** — уже включена в `sell_price`, НЕ прибавлять к прибыли!
- `calc_commissions` = сумма расчётных комиссий из `ya_order_items.commission_*` полей (~67% заказов)
- `fact_commissions` = реальные удержания ЯМ из `ya_payments_reports` ≈ `market_services`

### Формат ya_payments_reports — два типа записей

Таблица содержит разнородные данные, фильтрация зависит от формата:

| Признак | Новый формат | Старый формат |
|---|---|---|
| `transaction_source` | заполнен | NULL |
| Реальные комиссии ЯМ | `transaction_source = 'Оплата услуг Яндекс.Маркета'` | `payment_status = 'Удержание'` |
| Промо-расходы (наши) | `transaction_source = 'Скидка за участие в совместных акциях'` | `payment_status = 'Списание'` |
| Субсидия ЯМ (справочно) | `transaction_source = 'Баллы за скидку Маркета'` | `payment_status = 'Начисление'` (второй ряд) |

### Почему НЕ используем SUM(ya_payments_reports) как сумму выплаты

`ya_payments_reports` смешивает реальные комиссии и промо-расходы с одинаковыми именами (`item_name_or_service_name = 'Размещение товарных предложений'`). Надёжнее использовать `sell_price − market_services` из `ya_order_margin_report`.

### Заказы с несколькими позициями (multi-item)

142 заказа имеют >1 позиции в `ya_order_items`. `ya_order_margin_report` хранит **один** `sell_price`/`market_services` на весь заказ. При JOIN значения повторяются в каждой строке позиции — при агрегации по заказу суммировать `sell_price` и `market_services` НЕЛЬЗЯ.

## Правила разработки

### Общие
- Интерпретатор — `.venv/bin/python`, не системный
- Язык UI и комментариев — **русский**; имена переменных/функций — **английский**
- Не коммитить `.env`, `data/uploads/`

### Код
- SQL-запросы только в `db/queries.py`; сырой SQL через `sqlalchemy.text`, никаких ORM
- Расчёт метрик только в `economics.py` (чистые функции, без side-эффектов)
- Кэшировать тяжёлые операции через `@st.cache_data`
- Не хранить состояние в глобальных переменных — использовать `st.session_state`
- Новые страницы — в `pages/` по формату `N_Название.py`
- Все фильтры — в `st.sidebar`

### Безопасность
- Учётные данные БД только через `.env` / `st.secrets`, никогда не хардкодить
