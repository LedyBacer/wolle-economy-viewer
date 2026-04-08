"""
SQL-запросы к базе данных.
Намеренно разбиты на отдельные запросы для читаемости и поддерживаемости.

Фильтрация на уровне БД (seller_ids, date_from, date_to) уменьшает объём
данных, передаваемых по сети, и снижает нагрузку на Python-слой.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import text

try:
    # SQLAlchemy 2.x
    from sqlalchemy.sql.elements import TextClause
except ImportError:  # pragma: no cover
    # Fallback for older SQLAlchemy
    from sqlalchemy.sql.expression import TextClause


# ---------------------------------------------------------------------------
# Базовый SELECT для позиций заказов (без WHERE и ORDER BY)
# ---------------------------------------------------------------------------
_ORDER_ITEMS_SELECT = """
SELECT
    -- Идентификаторы
    o.id                          AS ya_order_id,
    o.order_id                    AS order_id,
    i.id                          AS item_id,

    -- Время и продавец
    o.created_at                  AS created_at,
    o.shipment_date               AS shipment_date,
    s.seller_name                 AS seller_name,

    -- Товар
    i.offer_id                    AS offer_id,
    upg.name                      AS product_name,
    i.supplier_name               AS supplier_name,
    i.count                       AS quantity,

    -- Статусы
    -- Для заказов без margin_report (WolleBuy / ТехноПравда Гонконг и др.)
    -- подставляем русскую расшифровку o.status, чтобы колонки не были пустыми.
    COALESCE(tr.status, o.status) AS order_status,
    COALESCE(
        mr.status,
        CASE o.status
            WHEN 'DELIVERED'  THEN 'Доставлен'
            WHEN 'CANCELLED'  THEN 'Отменён'
            WHEN 'DELIVERY'   THEN 'В доставке'
            WHEN 'PROCESSING' THEN 'В обработке'
            WHEN 'PICKUP'     THEN 'Самовывоз'
            ELSE o.status
        END
    )                             AS fulfillment_status,
    mr.payment_status             AS payment_status,

    -- Цены (за единицу)
    i.base_price                  AS base_price,
    i.buyer_price                 AS buyer_price,
    COALESCE(i.subsidy, 0)        AS subsidy,
    i.final_price                 AS min_sell_price,
    i.margin_percent              AS margin_percent,
    COALESCE(ff.value, 0)         AS ff_fee,
    COALESCE(sa.value, 0)         AS socket_adapter_fee,

    -- Данные из отчёта о марже (на уровне заказа)
    mr.sell_price                 AS sell_price,
    mr.market_services            AS market_services,

    -- Скидки и баллы из отчёта о транзакциях (на уровне позиции)
    COALESCE(tr.bonuses, 0)                AS tr_bonuses,
    COALESCE(tr.our_discount, 0)           AS our_discount,
    COALESCE(tr.market_discount, 0)        AS market_discount,
    COALESCE(tr.other_market_discounts, 0) AS other_discounts,
    COALESCE(tr.market_discount_sber, 0)   AS sber_discount,
    COALESCE(tr.market_discount_ya_plus, 0) AS ya_plus_discount,
    COALESCE(tr.customer_refund_amount, 0) AS customer_refund,

    -- Даты платежей из транзакционного отчёта (надёжнее payments_reports.payment_date)
    tr.customer_payment_date      AS tr_customer_payment_date,
    tr.refund_payment_date        AS tr_refund_payment_date,

    -- Расчётные комиссии из нашей системы (только commission_* — это реальные
    -- расчётные комиссии ЯМ; markup_* здесь не включаем, это наша наценка).
    COALESCE(i.commission_yandex_category_fee_amount, 0)       AS calc_category_fee,
    COALESCE(i.commission_yandex_transfer_payments_fee_amount, 0) AS calc_transfer_fee,
    COALESCE(i.commission_yandex_delivery_fee_actual_amount, 0)   AS calc_delivery_fee

FROM e_com.ya_orders o
JOIN e_com.ya_order_items i
    ON o.id = i.order_id
JOIN e_com.platform_sellers s
    ON o.seller_id = s.id
JOIN e_com.yandex_feed_items fi
    ON i.feed_item_id = fi.id
JOIN e_com.unique_product_groups upg
    ON fi.unique_product_group_id = upg.id
LEFT JOIN e_com.ya_order_margin_report mr
    ON o.id = mr.ya_orders_id
LEFT JOIN e_com.ya_order_transactions_report tr
    ON i.id = tr.ya_order_items_id
LEFT JOIN e_com.market_modifier_yandex mm
    ON fi.market_modifier_yandex_id = mm.id
LEFT JOIN e_com.ff_fees ff
    ON mm.ff_fees_id = ff.id
LEFT JOIN e_com.socket_adapter_fee sa
    ON mm.socket_adapter_fee_id = sa.id
"""


def build_order_items_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """
    Возвращает (sql, params) для запроса позиций заказов.

    Параметры фильтрации передаются как bind-параметры SQLAlchemy,
    что исключает SQL-инъекции и позволяет БД переиспользовать plan.

    Args:
        seller_ids: кортеж ID продавцов для фильтрации; None — все продавцы.
        date_from:  нижняя граница created_at (включительно); None — без ограничения.
        date_to:    верхняя граница created_at (включительно по дню); None — без ограничения.
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if seller_ids:
        conditions.append("o.seller_id = ANY(:seller_ids)")
        params["seller_ids"] = list(seller_ids)

    if date_from is not None:
        conditions.append("o.created_at >= :date_from")
        params["date_from"] = date_from

    if date_to is not None:
        # date_to включительно: берём начало следующего дня
        conditions.append("o.created_at < :date_to_exclusive")
        params["date_to_exclusive"] = date_to + datetime.timedelta(days=1)

    where = ("\nWHERE " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(_ORDER_ITEMS_SELECT + where + "\nORDER BY o.created_at DESC")
    return sql, params


# ---------------------------------------------------------------------------
# Агрегаты платежей — фильтруется по тому же набору заказов через подзапрос
# ---------------------------------------------------------------------------
_PAYMENT_AGGREGATES_SELECT = """
SELECT
    ya_orders_id,
    MAX(payment_date) AS last_payment_date,

    -- Фактические комиссии ЯМ (реальные удержания за услуги).
    -- Новый формат (transaction_source заполнен): фильтруем по источнику 'Оплата услуг'.
    -- Старый формат (transaction_source NULL): фильтруем по payment_status='Удержание'.
    -- Так исключаем промо-списания (payment_status='Списание'), у которых item_name
    -- совпадает с реальными комиссиями, что раньше приводило к двойному счёту.
    SUM(CASE
        WHEN transaction_amount < 0
         AND (
            transaction_source = 'Оплата услуг Яндекс.Маркета'
            OR (transaction_source IS NULL AND payment_status = 'Удержание')
         )
        THEN -transaction_amount ELSE 0
    END) AS fact_commissions,

    -- Штраф: отмена по вине продавца
    SUM(CASE
        WHEN item_name_or_service_name = 'Отмена заказа по вине продавца'
         AND transaction_amount < 0
        THEN -transaction_amount ELSE 0
    END) AS seller_cancel_penalty,

    -- Штраф: поздняя отгрузка/доставка
    SUM(CASE
        WHEN item_name_or_service_name = 'Отгрузка или доставка не вовремя'
         AND transaction_amount < 0
        THEN -transaction_amount ELSE 0
    END) AS late_ship_penalty,

    -- Компенсации в нашу пользу (положительные)
    SUM(CASE
        WHEN transaction_source IN (
            'Компенсация за потерянный заказ',
            'Компенсация по претензии',
            'Возврат премии'
        ) THEN transaction_amount ELSE 0
    END) AS compensations,

    -- Промо-расходы (наши расходы из баланса баллов на участие в акциях).
    -- Новый формат: transaction_source = 'Скидка за участие в совместных акциях'.
    -- Старый формат: transaction_source IS NULL AND payment_status = 'Списание'.
    -- Результат ОТРИЦАТЕЛЬНЫЙ — это наши расходы (вычитаются из прибыли).
    SUM(CASE
        WHEN transaction_source = 'Скидка за участие в совместных акциях'
          OR (transaction_source IS NULL AND payment_status = 'Списание')
        THEN transaction_amount ELSE 0
    END) AS promo_discounts

FROM e_com.ya_payments_reports
WHERE ya_orders_id IS NOT NULL
"""


def build_payment_aggregates_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """
    Возвращает (sql, params) для запроса агрегированных данных о платежах.

    Когда переданы seller_ids или даты — добавляет подзапрос к ya_orders,
    чтобы не тянуть строки платежей для нерелевантных заказов.
    """
    params: dict[str, Any] = {}
    extra_conditions: list[str] = []

    if seller_ids or date_from is not None or date_to is not None:
        sub_conditions = ["o2.id = p.ya_orders_id"]

        if seller_ids:
            sub_conditions.append("o2.seller_id = ANY(:seller_ids)")
            params["seller_ids"] = list(seller_ids)

        if date_from is not None:
            sub_conditions.append("o2.created_at >= :date_from")
            params["date_from"] = date_from

        if date_to is not None:
            sub_conditions.append("o2.created_at < :date_to_exclusive")
            params["date_to_exclusive"] = date_to + datetime.timedelta(days=1)

        sub_where = " AND ".join(sub_conditions)
        extra_conditions.append(f"EXISTS (SELECT 1 FROM e_com.ya_orders o2 WHERE {sub_where})")

    # Алиас p нужен для подзапроса выше
    base = _PAYMENT_AGGREGATES_SELECT.replace(
        "FROM e_com.ya_payments_reports",
        "FROM e_com.ya_payments_reports p",
    ).replace(
        "WHERE ya_orders_id IS NOT NULL",
        "WHERE p.ya_orders_id IS NOT NULL",
    )

    if extra_conditions:
        base += "  AND " + "\n  AND ".join(extra_conditions) + "\n"

    base += "GROUP BY p.ya_orders_id"
    sql = text(base)
    return sql, params


# ---------------------------------------------------------------------------
# Запрос 3: Список продавцов
# ---------------------------------------------------------------------------
SELLERS_SQL = text("""
SELECT id, seller_name
FROM e_com.platform_sellers
ORDER BY seller_name
""")


# ---------------------------------------------------------------------------
# Запрос 4: Диапазон дат заказов (для инициализации date picker)
# ---------------------------------------------------------------------------
DATE_RANGE_SQL = text("""
SELECT
    MIN(created_at)::date AS min_date,
    MAX(created_at)::date AS max_date
FROM e_com.ya_orders
""")
