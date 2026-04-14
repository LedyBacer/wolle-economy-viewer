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
    s.location                    AS seller_location,

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
        -- tr.status='Частично возвращён' перебивает mr.status:
        -- margin_report может показывать 'Доставлен' даже при частичном возврате
        CASE WHEN tr.status = 'Частично возвращён' THEN 'Частично возвращён' END,
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
    -- Стоимость доставки из Китая (только для CN-магазинов — наш расход,
    -- не включён в market_services; для RU-магазинов = ЯМ-доставка, уже в market_services)
    COALESCE(i.markup_custom_delivery_fee_value_amount, 0) AS custom_delivery_fee,

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
    COALESCE(tr.returned_sell_price, 0)    AS returned_sell_price,
    -- NULL когда нет транзакций (нет tr-записи) → economics.py делает fallback на quantity
    tr.delivered_quantity                  AS tr_delivered_quantity,

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
-- Агрегируем транзакции по позиции: одна ya_order_items может иметь несколько строк,
-- например если из 3 заказанных штук 1 вернули — будет транзакция доставки и транзакция возврата.
-- SUM по финансовым полям, MAX по датам и статусу.
LEFT JOIN (
    SELECT
        ya_order_items_id,
        -- Итоговый статус:
        -- - есть и доставка и возврат → "Частично возвращён"
        -- - только возвраты → берём статус возврата
        -- - только доставка → берём статус доставки
        CASE
            WHEN COUNT(CASE WHEN status IN ('Возврат оформлен', 'Невыкуп передан вам') THEN 1 END) > 0
             AND COUNT(CASE WHEN status NOT IN ('Возврат оформлен', 'Невыкуп передан вам') THEN 1 END) > 0
            THEN 'Частично возвращён'
            ELSE COALESCE(
                MAX(CASE WHEN status IN ('Возврат оформлен', 'Невыкуп передан вам') THEN status END),
                MAX(status)
            )
        END                                        AS status,
        SUM(COALESCE(bonuses, 0))                  AS bonuses,
        SUM(COALESCE(our_discount, 0))             AS our_discount,
        SUM(COALESCE(market_discount, 0))          AS market_discount,
        SUM(COALESCE(other_market_discounts, 0))   AS other_market_discounts,
        SUM(COALESCE(market_discount_sber, 0))     AS market_discount_sber,
        SUM(COALESCE(market_discount_ya_plus, 0))  AS market_discount_ya_plus,
        SUM(COALESCE(customer_refund_amount, 0))   AS customer_refund_amount,
        -- Сумма sell_price возвращённых транзакций = buyer_price + subsidy за возвращённые штуки.
        -- Используется для корректировки sell_price: customer_refund_amount не включает субсидию,
        -- поэтому вычитать нужно именно sell_price возврата, а не customer_refund_amount.
        SUM(CASE
            WHEN status IN ('Возврат оформлен', 'Невыкуп передан вам')
            THEN COALESCE(sell_price, 0) ELSE 0
        END)                                       AS returned_sell_price,
        -- Количество доставленных единиц (total - возвращённые).
        -- Каждая транзакция = 1 штука заказа; используется для корректировки our_costs.
        COUNT(CASE
            WHEN status NOT IN ('Возврат оформлен', 'Невыкуп передан вам') THEN 1
        END)                                       AS delivered_quantity,
        MAX(customer_payment_date)                 AS customer_payment_date,
        MAX(refund_payment_date)                   AS refund_payment_date
    FROM e_com.ya_order_transactions_report
    GROUP BY ya_order_items_id
) tr ON i.id = tr.ya_order_items_id
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
    MAX(CASE
        -- Новый формат: реальная выплата по графику или удержана из платежей покупателей
        WHEN transaction_source IS NOT NULL
         AND payment_status IN ('Удержан из платежей покупателей', 'Переведён по графику выплат')
        THEN payment_date
        -- Старый формат: только Начисление = фактический перевод средств
        WHEN transaction_source IS NULL AND payment_status = 'Начисление'
        THEN payment_date
        ELSE NULL
    END) AS last_payment_date,

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
# Фактическая закупочная цена позиции заказа
# ---------------------------------------------------------------------------
# Логика: для каждого ya_order_item определяем «исходный» order_to_supplier,
# из которого реально приехал товар на склад, и берём его ru_custom_price/ru_price.
#
# - Если по позиции вообще нет движений по складу → берём текущий order_to_supplier.
# - Если последнее движение — 'lost' → берём текущий order_to_supplier.
# - Иначе → берём первую транзакцию, которая привезла товар на этот склад.
#
# COALESCE(..., 0) возвращает 0, когда исходного заказа поставщику нет —
# в этом случае Python-слой делает fallback на плановый base_price.
_SUPPLIER_PRICE_FACT_SELECT = """
WITH
latest_stock_movement AS (
    SELECT DISTINCT ON (smt.all_split_orders_id)
        smt.all_split_orders_id,
        smt.type,
        smt.warehouse_new_id
    FROM e_com.stock_movement_transactions smt
    ORDER BY smt.all_split_orders_id, smt.created_at DESC
),
first_stock_transaction AS (
    SELECT DISTINCT ON (smt.warehouse_new_id)
        smt.warehouse_new_id,
        smt.all_split_orders_id AS first_source_order_id
    FROM e_com.stock_movement_transactions smt
    ORDER BY smt.warehouse_new_id, smt.created_at ASC
),
source_order_mapping AS (
    SELECT
        yai.id AS ya_order_item_id,
        CASE
            WHEN lsm.all_split_orders_id IS NULL THEN aso.id
            WHEN lsm.type = 'lost'               THEN aso.id
            ELSE fst.first_source_order_id
        END AS source_all_split_orders_id
    FROM e_com.ya_order_items yai
    INNER JOIN e_com.all_split_orders aso ON yai.id = aso.ya_order_items_id
    LEFT JOIN latest_stock_movement lsm ON aso.id = lsm.all_split_orders_id
    LEFT JOIN first_stock_transaction fst ON lsm.warehouse_new_id = fst.warehouse_new_id
)
-- DISTINCT ON: у позиции может быть несколько all_split_orders (quantity>1),
-- что порождает несколько строк в source_order_mapping. Берём одну — цена одинакова.
SELECT DISTINCT ON (yai.id)
    yai.id AS item_id,
    COALESCE(ots.ru_custom_price, ots.ru_price, 0) AS supplier_price_fact
FROM e_com.ya_order_items yai
JOIN e_com.ya_orders o ON yai.order_id = o.id
LEFT JOIN source_order_mapping som ON yai.id = som.ya_order_item_id
LEFT JOIN e_com.all_split_orders aso_source ON som.source_all_split_orders_id = aso_source.id
LEFT JOIN e_com.order_to_supplier ots ON aso_source.order_to_supplier_id = ots.id
"""


def build_supplier_price_fact_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """
    Возвращает (sql, params) для запроса фактических закупочных цен по позициям.

    Фильтры применяются по `ya_orders` тем же набором условий, что и в
    основном запросе позиций — это сужает результат до релевантных заказов.
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
        conditions.append("o.created_at < :date_to_exclusive")
        params["date_to_exclusive"] = date_to + datetime.timedelta(days=1)

    where = ("\nWHERE " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(_SUPPLIER_PRICE_FACT_SELECT + where)
    return sql, params


# ---------------------------------------------------------------------------
# Запрос 3: Список продавцов
# ---------------------------------------------------------------------------
SELLERS_SQL = text("""
SELECT id, seller_name
FROM e_com.platform_sellers
WHERE platform_for_sell_id = 1
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


# ═══════════════════════════════════════════════════════════════════════════
# МегаМаркет
# ═══════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# Подзапрос: агрегация mm_payment_reports по заказу
# ---------------------------------------------------------------------------
# Маппинг полей mm_payment_reports сильно зависит от версии отчёта ММ.
# Поля total / withheld_vat / incentive_reward / reward = итог строки (net payout).
# COALESCE берёт первый непустой итог-поле; иначе суммирует компоненты.
#
# Исключаем строки вида (pcc > 0, tc IS NULL, stw IS NULL) — это субсидийные
# строки из отдельных отчётов ММ (не входят в основную финансовую выплату).
_MM_PR_AGG = """
    SELECT
        mm_dbs_orders_id1,
        -- market_services: сумма |отрицательных| компонентов (комиссии, штрафы).
        -- Положительные компоненты НЕ агрегируем — маппинг полей нестабилен
        -- между версиями отчётов ММ, и итоговые суммы попадают в компонентные поля.
        -- sell_price и expected_payout вычисляются в Python из данных заказа.
        -- Только 6 «чистых» компонентных полей — они никогда не используются
        -- как итоговые суммы. cancellation_before_confirmation_commission и
        -- no_edo_commission исключены: в ряде версий отчётов ММ они хранят
        -- итог строки (net payout), а не реальную комиссию.
        SUM(
            ABS(LEAST(COALESCE(transaction_commission, 0), 0))
            + ABS(LEAST(COALESCE(product_category_commission, 0), 0))
            + ABS(LEAST(COALESCE(seller_goods, 0), 0))
            + ABS(LEAST(COALESCE(shipment_transfer_without_cancellation_commission, 0), 0))
            + ABS(LEAST(COALESCE(shipment_transfer_with_cancellation_commission, 0), 0))
            + ABS(LEAST(COALESCE(return_processing_commission, 0), 0))
        )                                                                     AS market_services,
        BOOL_OR(COALESCE(is_paid, FALSE))                                     AS is_paid
    FROM e_com.mm_payment_reports
    GROUP BY mm_dbs_orders_id1
"""

# ---------------------------------------------------------------------------
# Подзапрос: фактическая выплата из финансовых отчётов ММ (mm_financial_report)
# ---------------------------------------------------------------------------
# company_debt — что ММ должен нам, seller_debt — удержания (комиссии).
# net = company_debt − seller_debt = фактически перечисленная сумма по заказу.
# НДС на incentive вычитается на уровне мерчанта, не попадает в per-order строки.
_MM_FR_AGG = """
    SELECT
        shipment_id,
        SUM(COALESCE(company_debt, 0)) - SUM(COALESCE(seller_debt, 0)) AS fr_net_payout
    FROM e_com.mm_financial_report
    WHERE shipment_id IS NOT NULL
    GROUP BY shipment_id
"""

# ---------------------------------------------------------------------------
# Подзапрос: фактическая закупочная цена через all_split_orders
# ---------------------------------------------------------------------------
# DISTINCT ON: при quantity > 1 может быть несколько all_split_orders на позицию.
_MM_SPF = """
    SELECT DISTINCT ON (aso.mm_dbs_order_item_id)
        aso.mm_dbs_order_item_id,
        COALESCE(ots.ru_custom_price, ots.ru_price, 0) AS supplier_price_fact,
        ots.supplier_name                               AS supplier_name
    FROM e_com.all_split_orders aso
    LEFT JOIN e_com.order_to_supplier ots ON ots.id = aso.order_to_supplier_id
    WHERE aso.mm_dbs_order_item_id IS NOT NULL
    ORDER BY aso.mm_dbs_order_item_id
"""

# ---------------------------------------------------------------------------
# МегаМаркет DBS: позиции заказов (1 строка = 1 позиция)
# ---------------------------------------------------------------------------
_MM_DBS_ORDER_ITEMS_SELECT = f"""
SELECT
    -- Идентификаторы
    o.id                          AS mm_order_id,
    o.shipment_id                 AS order_id,
    i.id                          AS item_id,

    -- Время и продавец
    o.created_at                  AS created_at,
    c.delivered_at                AS delivered_at,
    ps.id                         AS seller_id,
    ps.seller_name                AS seller_name,

    -- Товар
    i.offer_id                    AS offer_id,
    i.item_name                   AS product_name,
    i.quantity                    AS quantity,

    -- Цены (за единицу)
    i.base_price                  AS base_price,
    i.price                       AS price,
    i.final_price                 AS final_price,
    i.min_allowed_price           AS margin_pct_raw,    -- ошибочное название в БД: на самом деле % маржи
    i.margin_percent              AS min_sell_price,     -- ошибочное название в БД: на самом деле мин. допустимая цена
    i.modifier_price              AS modifier_price,     -- цена с учётом маржи + комиссий + доставки

    -- Доставка
    o.delivery_cost               AS delivery_cost,      -- стоимость доставки, снятая с покупателя
    o.cdek_delivery_cost          AS cdek_delivery_cost,  -- фактическая стоимость доставки для нас

    -- Бонусы покупателя (incentive): часть, оплаченная бонусами (спасибо и т.д.)
    (i.price - i.final_price)     AS incentive_amount,

    -- Статусы
    c.status                      AS cdek_status,
    i.status                      AS item_status,
    CASE
        WHEN c.status = 'DELIVERED'                            THEN 'Доставлен'
        WHEN c.status = 'NOT_DELIVERED'                        THEN 'Не доставлен'
        WHEN c.status IN ('REMOVED', 'DELETED', 'CANCELLED')  THEN 'Отменён'
        WHEN c.status = 'RETURNED_TO_RECIPIENT_CITY_WAREHOUSE' THEN 'Возврат'
        WHEN c.status IS NOT NULL                              THEN 'В доставке'
        WHEN i.status IN ('canceled', 'canceled_by_mm', 'canceled_declined') THEN 'Отменён'
        WHEN i.status = 'delivered'                            THEN 'Доставлен'
        WHEN i.status = 'returned'                             THEN 'Возврат'
        ELSE 'Неизвестно'
    END                           AS fulfillment_status,
    CASE
        WHEN COALESCE(pr.is_paid, FALSE) THEN 'Переведён'
        WHEN pr.market_services > 0      THEN 'Списание'
        ELSE NULL
    END                                         AS payment_status,

    -- Комиссии из mm_payment_reports (только отрицательные компоненты — надёжные).
    -- sell_price и expected_payout вычисляются в Python из данных заказа,
    -- т.к. маппинг положительных полей нестабилен между версиями отчётов ММ.
    COALESCE(pr.market_services, 0)         AS market_services,

    -- Стоимость возврата СДЭК
    COALESCE(r.delivery_cost, 0)  AS return_delivery_cost,

    -- Фактическая закупочная цена и поставщик
    COALESCE(spf.supplier_price_fact, 0) AS supplier_price_fact,
    spf.supplier_name                    AS supplier_name,

    -- Фактическая выплата из финансовых отчётов ММ
    COALESCE(fr.fr_net_payout, 0) AS fr_net_payout,

    -- Канал
    'dbs'                         AS channel

FROM e_com.mm_dbs_orders o
JOIN e_com.mm_dbs_order_item i
    ON i.order_id = o.id
JOIN e_com.platform_sellers ps
    ON ps.id = o.seller_id
LEFT JOIN e_com.mm_cdek_orders c
    ON c.mm_order_id = o.id
LEFT JOIN e_com.mm_dbs_cdek_returns r
    ON r.mm_cdek_orders_id = c.id
LEFT JOIN ({_MM_PR_AGG}) pr
    ON pr.mm_dbs_orders_id1 = o.id
LEFT JOIN ({_MM_SPF}) spf
    ON spf.mm_dbs_order_item_id = i.id
LEFT JOIN ({_MM_FR_AGG}) fr
    ON fr.shipment_id = o.shipment_id
WHERE ps.platform_for_sell_id = 5
  AND ps.feed_type != 'POIZON'
"""


def build_mm_dbs_order_items_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """Возвращает (sql, params) для DBS-заказов МегаМаркет."""
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if seller_ids:
        conditions.append("o.seller_id = ANY(:seller_ids)")
        params["seller_ids"] = list(seller_ids)
    if date_from is not None:
        conditions.append("o.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        conditions.append("o.created_at < :date_to_exclusive")
        params["date_to_exclusive"] = date_to + datetime.timedelta(days=1)

    extra = ("\n  AND " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(_MM_DBS_ORDER_ITEMS_SELECT + extra + "\nORDER BY o.created_at DESC")
    return sql, params


# ---------------------------------------------------------------------------
# МегаМаркет Poizon: позиции заказов (1 строка = 1 позиция)
# ---------------------------------------------------------------------------
_MM_POIZON_ORDER_ITEMS_SELECT = f"""
SELECT
    -- Идентификаторы
    o.id                          AS mm_order_id,
    o.shipment_id                 AS order_id,
    i.id                          AS item_id,

    -- Время и продавец
    o.created_at                  AS created_at,
    NULL::timestamptz             AS delivered_at,
    ps.id                         AS seller_id,
    ps.seller_name                AS seller_name,

    -- Товар
    i.offer_id                    AS offer_id,
    i.item_name                   AS product_name,
    i.quantity                    AS quantity,

    -- Цены (за единицу)
    i.base_price                  AS base_price,
    i.price                       AS price,
    i.final_price                 AS final_price,
    i.min_allowed_price           AS margin_pct_raw,    -- ошибочное название в БД: на самом деле % маржи
    i.margin_percent              AS min_sell_price,     -- ошибочное название в БД: на самом деле мин. допустимая цена
    i.modifier_price              AS modifier_price,     -- цена с учётом маржи + комиссий + доставки

    -- Доставка
    o.delivery_cost               AS delivery_cost,      -- стоимость доставки, снятая с покупателя
    COALESCE(o.cdek_delivery_cost, 0) AS cdek_delivery_cost,  -- фактическая стоимость доставки

    -- Бонусы покупателя (incentive): часть, оплаченная бонусами
    (i.price - i.final_price)     AS incentive_amount,

    -- Статусы (po.status вместо СДЭК)
    po.status                     AS cdek_status,
    i.status                      AS item_status,
    CASE po.status
        WHEN 'COMPLETED' THEN 'Доставлен'
        WHEN 'CANCELED'  THEN 'Отменён'
        ELSE 'В доставке'
    END                           AS fulfillment_status,
    CASE
        WHEN COALESCE(pr.is_paid, FALSE) THEN 'Переведён'
        WHEN pr.market_services > 0      THEN 'Списание'
        ELSE NULL
    END                                         AS payment_status,

    -- Комиссии из mm_payment_reports (только отрицательные компоненты).
    COALESCE(pr.market_services, 0)         AS market_services,

    -- Нет СДЭК-возврата для Poizon
    0                             AS return_delivery_cost,

    -- Фактическая закупочная цена и поставщик (через all_split_orders)
    COALESCE(spf.supplier_price_fact, 0) AS supplier_price_fact,
    spf.supplier_name                    AS supplier_name,

    -- Цена товара на Poizon (альтернативная закупочная для аналитики)
    pi.price                      AS poizon_price,

    -- Фактическая выплата из финансовых отчётов ММ
    COALESCE(fr.fr_net_payout, 0) AS fr_net_payout,

    -- Канал
    'poizon'                      AS channel

FROM e_com.mm_dbs_orders o
JOIN e_com.mm_dbs_order_item i
    ON i.order_id = o.id
JOIN e_com.mm_dbs_poizon_orders po
    ON po.mm_dbs_orders_id = o.id
LEFT JOIN e_com.mm_dbs_poizon_order_items pi
    ON pi.mm_dbs_order_item_id = i.id
JOIN e_com.platform_sellers ps
    ON ps.id = o.seller_id
LEFT JOIN ({_MM_PR_AGG}) pr
    ON pr.mm_dbs_orders_id1 = o.id
LEFT JOIN ({_MM_SPF}) spf
    ON spf.mm_dbs_order_item_id = i.id
LEFT JOIN ({_MM_FR_AGG}) fr
    ON fr.shipment_id = o.shipment_id
WHERE ps.platform_for_sell_id = 5
  AND ps.feed_type = 'POIZON'
"""


def build_mm_poizon_order_items_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """Возвращает (sql, params) для Poizon-заказов МегаМаркет."""
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if seller_ids:
        conditions.append("o.seller_id = ANY(:seller_ids)")
        params["seller_ids"] = list(seller_ids)
    if date_from is not None:
        conditions.append("o.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        conditions.append("o.created_at < :date_to_exclusive")
        params["date_to_exclusive"] = date_to + datetime.timedelta(days=1)

    extra = ("\n  AND " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(_MM_POIZON_ORDER_ITEMS_SELECT + extra + "\nORDER BY o.created_at DESC")
    return sql, params


# ---------------------------------------------------------------------------
# МегаМаркет: список продавцов
# ---------------------------------------------------------------------------
MM_SELLERS_SQL = text("""
SELECT id, seller_name
FROM e_com.platform_sellers
WHERE platform_for_sell_id = 5
ORDER BY seller_name
""")


# ---------------------------------------------------------------------------
# МегаМаркет: диапазон дат заказов
# ---------------------------------------------------------------------------
MM_DATE_RANGE_SQL = text("""
SELECT
    MIN(o.created_at)::date AS min_date,
    MAX(o.created_at)::date AS max_date
FROM e_com.mm_dbs_orders o
JOIN e_com.platform_sellers ps ON ps.id = o.seller_id
WHERE ps.platform_for_sell_id = 5
""")
