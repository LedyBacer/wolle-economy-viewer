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


def _build_common_filters(
    *,
    seller_ids: tuple[int, ...] | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    seller_expr: str,
    created_at_expr: str,
) -> tuple[list[str], dict[str, Any]]:
    """Собирает SQL-условия фильтрации по продавцам и диапазону дат."""
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if seller_ids:
        conditions.append(f"{seller_expr} = ANY(:seller_ids)")
        params["seller_ids"] = list(seller_ids)

    if date_from is not None:
        conditions.append(f"{created_at_expr} >= :date_from")
        params["date_from"] = date_from

    if date_to is not None:
        conditions.append(f"{created_at_expr} < :date_to_exclusive")
        params["date_to_exclusive"] = date_to + datetime.timedelta(days=1)

    return conditions, params


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
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="o.seller_id",
        created_at_expr="o.created_at",
    )

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
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="o.seller_id",
        created_at_expr="o.created_at",
    )

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
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="o.seller_id",
        created_at_expr="o.created_at",
    )

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
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="o.seller_id",
        created_at_expr="o.created_at",
    )

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


# ═══════════════════════════════════════════════════════════════════════════
# Ozon
# ═══════════════════════════════════════════════════════════════════════════

_OZ_ORDER_ITEMS_SELECT = """
WITH
ozon_transactions_agg AS (
    SELECT
        ozon_orders_id,
        SUM(CASE WHEN service_name_ru ILIKE '%%вознаграждение за продажу%%' THEN -price ELSE 0 END) AS category_fee_fact,
        SUM(CASE WHEN operation_type_name ILIKE '%%Оплата эквайринга%%' THEN -price ELSE 0 END) AS acquiring_fee_fact,
        SUM(CASE
                WHEN service_name IN (
                    'MarketplaceServiceItemRedistributionLastMilePVZ',
                    'MarketplaceServiceItemRedistributionLastMileCourier',
                    'MarketplaceServiceItemDelivToCustomer'
                )
                THEN -price
                ELSE 0
            END) AS last_mile_fact,
        SUM(CASE WHEN service_name_ru ILIKE '%%Обработка отправления Drop-off%%' THEN -price ELSE 0 END) AS order_process_fact,
        SUM(CASE WHEN service_name_ru ILIKE '%%логистика%%' THEN -price ELSE 0 END) AS logistics_fact,
        CASE
            WHEN SUM(CASE WHEN service_name = 'Revenue' THEN 1 ELSE 0 END) > 0
            THEN SUM(price)
            ELSE 0
        END AS revenue_after_commission,
        SUM(CASE
                WHEN operation_type_name ILIKE '%%операционных ошибок продавца: отмена%%'
                THEN -price
                ELSE 0
            END) AS cancel_penalty,
        SUM(CASE
                WHEN operation_type_name ILIKE '%%операционных ошибок продавца: поздняя отгрузка%%'
                THEN -price
                ELSE 0
            END) AS late_shipment_penalty,
        SUM(CASE
                WHEN operation_type_name ILIKE '%%Обработка операционных ошибок продавца: отгрузка в нерекомендованный слот%%'
                THEN -price
                ELSE 0
            END) AS late_recommend_penalty,
        COUNT(*) AS report_rows
    FROM e_com.ozon_order_transactions
    GROUP BY ozon_orders_id
),
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
        oz.id AS oz_order_id,
        CASE
            WHEN lsm.all_split_orders_id IS NULL THEN aso.id
            WHEN lsm.type = 'lost'               THEN aso.id
            ELSE fst.first_source_order_id
        END AS source_all_split_orders_id
    FROM e_com.ozon_orders oz
    INNER JOIN e_com.all_split_orders aso ON oz.id = aso.ozon_orders_id
    LEFT JOIN latest_stock_movement lsm ON aso.id = lsm.all_split_orders_id
    LEFT JOIN first_stock_transaction fst ON lsm.warehouse_new_id = fst.warehouse_new_id
),
supplier_prices AS (
    SELECT DISTINCT ON (oz.id)
        oz.id AS oz_order_id,
        COALESCE(ots.ru_custom_price, ots.ru_price, 0) AS supplier_price_fact,
        ots.supplier_name AS supplier_name
    FROM e_com.ozon_orders oz
    LEFT JOIN source_order_mapping som ON oz.id = som.oz_order_id
    LEFT JOIN e_com.all_split_orders aso_source ON som.source_all_split_orders_id = aso_source.id
    LEFT JOIN e_com.order_to_supplier ots
        ON ots.id = aso_source.unique_product_id
    ORDER BY oz.id, aso_source.id
)
SELECT
    o.id AS oz_order_id,
    o.id AS item_id,
    o.order_id AS order_id,
    o.created_at + INTERVAL '3 HOUR' AS created_at,
    CASE
        WHEN (
            EXTRACT(DOW FROM o.created_at + INTERVAL '3 HOUR') = 6
            AND (o.created_at + INTERVAL '3 HOUR')::time >= '09:00:00'
        ) THEN date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '2 days' + INTERVAL '6 hours'
        WHEN EXTRACT(DOW FROM o.created_at + INTERVAL '3 HOUR') = 0
        THEN date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '1 day' + INTERVAL '6 hours'
        WHEN (o.created_at + INTERVAL '3 HOUR')::time >= '09:00:00'
        THEN date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '1 day' + INTERVAL '6 hours'
        ELSE date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '6 hours'
    END AS shipment_date,
    fi.platform_seller_id AS seller_id,
    ps.seller_name AS seller_name,
    ps.location AS seller_location,
    o.offer_id AS offer_id,
    fi.title AS product_name,
    COALESCE(o.supplier_name, sp.supplier_name) AS supplier_name,
    COALESCE(o.quantity, 1)::bigint AS quantity,
    o.status AS oz_status,
    CASE
        WHEN o.status = 'delivered' THEN
            CASE
                WHEN COALESCE(r.quantity, 0) > 0 THEN
                    CASE
                        WHEN COALESCE(r.quantity, 0) < COALESCE(o.quantity, 1) THEN 'Частичный возврат'
                        ELSE 'Возврат'
                    END
                ELSE 'Доставлен'
            END
        WHEN o.status = 'awaiting_packaging' THEN 'Ожидает сборки'
        WHEN o.status IN ('delivering', 'awaiting_deliver') THEN 'Доставляется'
        WHEN o.status = 'cancelled' THEN 'Отменен'
        ELSE o.status
    END AS order_status,
    CASE
        WHEN o.status = 'delivered' THEN
            CASE
                WHEN COALESCE(r.quantity, 0) > 0 THEN
                    CASE
                        WHEN COALESCE(r.quantity, 0) < COALESCE(o.quantity, 1) THEN 'Частичный возврат'
                        ELSE 'Возврат'
                    END
                ELSE 'Доставлен'
            END
        WHEN o.status = 'awaiting_packaging' THEN 'Ожидает сборки'
        WHEN o.status IN ('delivering', 'awaiting_deliver') THEN 'Доставляется'
        WHEN o.status = 'cancelled' THEN 'Отменен'
        ELSE o.status
    END AS fulfillment_status,
    COALESCE(o.supplier_price, 0)::double precision AS base_price,
    COALESCE(sp.supplier_price_fact, 0)::double precision AS supplier_price_fact,
    COALESCE(o.ff_fee, 50)::double precision AS ff_fee,
    COALESCE(o.socket_adapter_fee, 0)::double precision AS socket_adapter_fee,
    COALESCE(o.margin_price, o.price, 0)::double precision AS min_sell_price,
    (COALESCE(o.price, 0) * COALESCE(o.quantity, 1))::double precision AS sell_price_plan,
    (COALESCE(o.category_fee, 0) * COALESCE(o.quantity, 1))::double precision AS category_fee,
    (COALESCE(o.acquiring_fee, 0) * COALESCE(o.quantity, 1))::double precision AS acquiring_fee_plan,
    (
        (COALESCE(o.delivery_fee, 0) + COALESCE(o.order_process_fee, 0) + COALESCE(o.last_mile, 0))
        * COALESCE(o.quantity, 1)
    )::double precision AS delivery_fee_plan,
    (
        COALESCE(o.price, 0) * GREATEST(COALESCE(o.quantity, 1) - COALESCE(r.quantity, 0), 0)
    )::double precision AS report_sell_price,
    (
        COALESCE(ta.category_fee_fact, 0)
        + COALESCE(ta.acquiring_fee_fact, 0)
        + COALESCE(ta.last_mile_fact, 0)
        + COALESCE(ta.order_process_fact, 0)
        + COALESCE(ta.logistics_fact, 0)
    )::double precision AS report_market_services,
    COALESCE(ta.revenue_after_commission, 0)::double precision AS revenue_after_commission,
    COALESCE(ta.order_process_fact, 0)::double precision AS order_process_fact,
    COALESCE(ta.logistics_fact, 0)::double precision AS logistics_fact,
    0::double precision AS report_compensation,
    CASE
        WHEN COALESCE(r.quantity, 0) > 0 THEN 1
        ELSE 0
    END::double precision AS return_docs,
    COALESCE(r.quantity, 0)::double precision AS refund_quantity,
    COALESCE(o.cancelled_after_ship, FALSE) AS cancelled_after_ship,
    COALESCE(ta.report_rows, 0)::double precision AS report_rows,
    COALESCE(ta.cancel_penalty, 0)::double precision AS cancel_penalty,
    COALESCE(ta.late_shipment_penalty, 0)::double precision AS late_shipment_penalty,
    COALESCE(ta.late_recommend_penalty, 0)::double precision AS late_recommend_penalty
FROM e_com.ozon_orders o
JOIN e_com.ozon_feed_items fi ON fi.id = o.feed_item_id
JOIN e_com.platform_sellers ps ON ps.id = fi.platform_seller_id
LEFT JOIN e_com.ozon_refunds r ON r.id = o.ozon_refunds_id
LEFT JOIN ozon_transactions_agg ta ON ta.ozon_orders_id = o.id
LEFT JOIN supplier_prices sp ON sp.oz_order_id = o.id
WHERE ps.platform_for_sell_id = 2
"""


def build_oz_order_items_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """Возвращает (sql, params) для заказов Ozon."""
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="fi.platform_seller_id",
        created_at_expr="o.created_at",
    )

    extra = ("\n  AND " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(_OZ_ORDER_ITEMS_SELECT + extra + "\nORDER BY o.created_at DESC")
    return sql, params


OZ_SELLERS_SQL = text("""
SELECT id, seller_name
FROM e_com.platform_sellers
WHERE platform_for_sell_id = 2
ORDER BY seller_name
""")


OZ_DATE_RANGE_SQL = text("""
SELECT
    MIN(o.created_at)::date AS min_date,
    MAX(o.created_at)::date AS max_date
FROM e_com.ozon_orders o
JOIN e_com.ozon_feed_items fi ON fi.id = o.feed_item_id
JOIN e_com.platform_sellers ps ON ps.id = fi.platform_seller_id
WHERE ps.platform_for_sell_id = 2
""")


# ═══════════════════════════════════════════════════════════════════════════
# Wildberries
# ═══════════════════════════════════════════════════════════════════════════

_WB_ORDER_ITEMS_SELECT = """
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
        wb.id AS wb_order_id,
        CASE
            WHEN lsm.all_split_orders_id IS NULL THEN aso.id
            WHEN lsm.type = 'lost'               THEN aso.id
            ELSE fst.first_source_order_id
        END AS source_all_split_orders_id
    FROM e_com.wb_orders wb
    INNER JOIN e_com.all_split_orders aso ON wb.id = aso.wb_orders_id
    LEFT JOIN latest_stock_movement lsm ON aso.id = lsm.all_split_orders_id
    LEFT JOIN first_stock_transaction fst ON lsm.warehouse_new_id = fst.warehouse_new_id
),
supplier_prices AS (
    SELECT
        wb.id AS wb_order_id,
        COALESCE(ots.ru_custom_price, ots.ru_price, 0) AS supplier_price_fact,
        ots.supplier_name AS supplier_name
    FROM e_com.wb_orders wb
    LEFT JOIN source_order_mapping som ON wb.id = som.wb_order_id
    LEFT JOIN e_com.all_split_orders aso_source ON som.source_all_split_orders_id = aso_source.id
    LEFT JOIN e_com.order_to_supplier ots
        ON ots.id = aso_source.unique_product_id
)
SELECT
    o.id AS wb_order_id,
    o.id AS item_id,
    o.order_id AS order_id,
    o.created_at + INTERVAL '3 HOUR' AS created_at,
    CASE
        WHEN (
            EXTRACT(DOW FROM o.created_at + INTERVAL '3 HOUR') = 6
            AND (o.created_at + INTERVAL '3 HOUR')::time >= '09:00:00'
        ) THEN date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '2 days' + INTERVAL '6 hours'
        WHEN EXTRACT(DOW FROM o.created_at + INTERVAL '3 HOUR') = 0
        THEN date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '1 day' + INTERVAL '6 hours'
        WHEN (o.created_at + INTERVAL '3 HOUR')::time >= '09:00:00'
        THEN date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '1 day' + INTERVAL '6 hours'
        ELSE date_trunc('day', o.created_at + INTERVAL '3 HOUR') + INTERVAL '6 hours'
    END AS shipment_date,
    o.seller_id AS seller_id,
    ps.seller_name AS seller_name,
    ps.location AS seller_location,
    o.offer_id AS offer_id,
    fi.title AS product_name,
    COALESCE(o.supplier_name, sp.supplier_name) AS supplier_name,
    1::bigint AS quantity,
    o.wb_status AS wb_status,
    CASE o.wb_status
        WHEN 'waiting' THEN 'в работе'
        WHEN 'sorted' THEN 'отсортирован'
        WHEN 'sold' THEN 'получен'
        WHEN 'canceled' THEN 'отмена'
        WHEN 'canceled_by_client' THEN 'отмена при получении'
        WHEN 'declined_by_client' THEN 'отмена до сборки'
        WHEN 'defect' THEN 'отмена по браку'
        WHEN 'ready_for_pickup' THEN 'прибыл в ПВЗ'
        WHEN 'postponed_delivery' THEN 'курьерская доставка отложена'
        ELSE o.wb_status
    END AS order_status,
    CASE o.wb_status
        WHEN 'waiting' THEN 'в работе'
        WHEN 'sorted' THEN 'отсортирован'
        WHEN 'sold' THEN 'получен'
        WHEN 'canceled' THEN 'отмена'
        WHEN 'canceled_by_client' THEN 'отмена при получении'
        WHEN 'declined_by_client' THEN 'отмена до сборки'
        WHEN 'defect' THEN 'отмена по браку'
        WHEN 'ready_for_pickup' THEN 'прибыл в ПВЗ'
        WHEN 'postponed_delivery' THEN 'курьерская доставка отложена'
        ELSE o.wb_status
    END AS fulfillment_status,
    o.base_price AS base_price,
    COALESCE(sp.supplier_price_fact, 0) AS supplier_price_fact,
    COALESCE(o.ff_fee, 50) AS ff_fee,
    COALESCE(o.socket_adapter_fee, 0) AS socket_adapter_fee,
    COALESCE(o.final_price, 0) AS min_sell_price,
    COALESCE(o.sale_price_ru, o.final_price) AS sell_price_plan,
    COALESCE(o.margin_percent, 0) AS margin_percent,
    COALESCE(o.category_fee, 0) AS category_fee,
    COALESCE(o.acquiring_fee, 0) AS acquiring_fee_plan,
    COALESCE(o.delivery_fee, 0) AS delivery_fee_plan,
    ra.report_sell_price AS report_sell_price,
    ra.report_retail_sum AS report_retail_sum,
    ra.report_commission AS report_commission,
    ra.report_acquiring_fee AS report_acquiring_fee,
    ra.report_delivery_fee AS report_delivery_fee,
    ra.report_penalty AS report_penalty,
    ra.report_acceptance AS report_acceptance,
    ra.report_storage_fee AS report_storage_fee,
    ra.report_market_services AS report_market_services,
    ra.report_compensation AS report_compensation,
    COALESCE(ra.return_docs, 0) AS return_docs,
    COALESCE(ra.report_rows, 0) AS report_rows
FROM e_com.wb_orders o
JOIN e_com.wb_feed_items fi ON fi.id = o.feed_item_id
JOIN e_com.platform_sellers ps ON ps.id = o.seller_id
LEFT JOIN supplier_prices sp ON sp.wb_order_id = o.id
LEFT JOIN LATERAL (
    SELECT
        SUM(
            CASE r.doc_type_name
                WHEN 'Продажа' THEN r.retail_price
                WHEN 'Возврат' THEN -r.retail_price
                WHEN '销售' THEN r.retail_price * CASE
                    WHEN fi.platform_seller_id = 11
                    THEN o.sale_price_ru / (CAST(o.converted_price AS DOUBLE PRECISION) / 100)
                    ELSE 1
                END
                ELSE 0
            END
        ) AS report_sell_price,
        SUM(r.retail_price) AS report_retail_sum,
        SUM(
            CASE r.doc_type_name
                WHEN 'Продажа' THEN (r.retail_price * r.commission_percent) / 100
                WHEN 'Возврат' THEN ((-r.retail_price) * r.commission_percent) / 100
                WHEN '销售' THEN (r.retail_price * CASE
                    WHEN fi.platform_seller_id = 11
                    THEN o.sale_price_ru / (CAST(o.converted_price AS DOUBLE PRECISION) / 100)
                    ELSE 1
                END * r.commission_percent) / 100
                ELSE 0
            END
        ) AS report_commission,
        SUM(r.acquiring_fee) AS report_acquiring_fee,
        SUM(
            CASE
                WHEN r.currency_name = 'cny'
                THEN r.delivery_rub * CASE
                    WHEN fi.platform_seller_id = 11
                    THEN o.sale_price_ru / (CAST(o.converted_price AS DOUBLE PRECISION) / 100)
                    ELSE 1
                END
                ELSE r.delivery_rub
            END
        ) AS report_delivery_fee,
        SUM(r.penalty) AS report_penalty,
        SUM(r.acceptance) AS report_acceptance,
        SUM(r.storage_fee) AS report_storage_fee,
        SUM(
            CASE
                WHEN r.supplier_oper_name LIKE 'Возмещение издержек по перевозке/по складским операциям с товаром'
                THEN r.ppvz_vw + r.ppvz_vw_nds + r.rebill_logistic_cost
                ELSE 0
            END
        ) AS report_compensation,
        COUNT(*) FILTER (WHERE r.doc_type_name = 'Возврат') AS return_docs,
        COUNT(r.id) AS report_rows,
        SUM(
            CASE r.doc_type_name
                WHEN 'Продажа' THEN (r.retail_price * r.commission_percent) / 100
                WHEN 'Возврат' THEN ((-r.retail_price) * r.commission_percent) / 100
                WHEN '销售' THEN (r.retail_price * CASE
                    WHEN fi.platform_seller_id = 11
                    THEN o.sale_price_ru / (CAST(o.converted_price AS DOUBLE PRECISION) / 100)
                    ELSE 1
                END * r.commission_percent) / 100
                ELSE 0
            END
        )
        + SUM(r.acquiring_fee)
        + SUM(
            CASE
                WHEN r.currency_name = 'cny'
                THEN r.delivery_rub * CASE
                    WHEN fi.platform_seller_id = 11
                    THEN o.sale_price_ru / (CAST(o.converted_price AS DOUBLE PRECISION) / 100)
                    ELSE 1
                END
                ELSE r.delivery_rub
            END
        )
        + SUM(r.penalty)
        + SUM(r.acceptance)
        + SUM(r.storage_fee) AS report_market_services
    FROM e_com.wb_reports r
    WHERE r.wb_orders_id = o.id
) ra ON TRUE
WHERE ps.platform_for_sell_id = 3
"""


def build_wb_order_items_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """Возвращает (sql, params) для заказов Wildberries."""
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="o.seller_id",
        created_at_expr="o.created_at",
    )

    extra = ("\n  AND " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(_WB_ORDER_ITEMS_SELECT + extra + "\nORDER BY o.created_at DESC")
    return sql, params


WB_SELLERS_SQL = text("""
SELECT id, seller_name
FROM e_com.platform_sellers
WHERE platform_for_sell_id = 3
ORDER BY seller_name
""")


WB_DATE_RANGE_SQL = text("""
SELECT
    MIN(o.created_at)::date AS min_date,
    MAX(o.created_at)::date AS max_date
FROM e_com.wb_orders o
JOIN e_com.platform_sellers ps ON ps.id = o.seller_id
WHERE ps.platform_for_sell_id = 3
""")


# ═══════════════════════════════════════════════════════════════════════════
# Sportmaster
# ═══════════════════════════════════════════════════════════════════════════

_SM_ORDER_ITEMS_SELECT = """
SELECT
    t1.id AS sm_order_id,
    t1.id AS item_id,
    t1.order_id AS order_id,
    t1.created_at AS created_at,
    t2.date_realization AS date_realization,
    t1.status_name AS order_status,
    t1.status_name AS fulfillment_status,
    t1.offer_id AS offer_id,
    t3.title AS product_name,
    t1.quantity AS quantity,
    1 AS seller_id,
    'Sportmaster' AS seller_name,
    'RU' AS seller_location,
    t1.supplier_name AS supplier_name,
    t4.shipment_date AS shipment_date,

    -- Плановая/фактическая закупка (за единицу)
    t1.supplier_price AS base_price,
    COALESCE(t5.supplier_price, 0) AS supplier_price_fact,

    -- Комиссии / расходы за единицу
    CAST(FLOOR(t1.ff_fee) AS BIGINT) AS ff_fee,
    CAST(FLOOR(t1.adapter_fee) AS BIGINT) AS socket_adapter_fee,
    t1.category_fee_percent AS category_fee_percent,
    CAST(FLOOR(t2.agent_rate_percent) AS BIGINT) AS agent_rate_percent,
    t1.category_fee AS category_fee,
    t2.agent_rate AS agent_rate,
    t1.delivery_fee AS delivery_fee,
    CAST(FLOOR(t2.logistic) AS BIGINT) AS logistic,

    -- Цены продажи
    t1.modifier_price AS modifier_price,
    t1.min_price_multiplier AS min_price_multiplier,
    t1.margin_price AS margin_price,
    t1.margin_price * t1.quantity AS margin_price_total,
    CAST(FLOOR(t2.seller_price) AS BIGINT) AS seller_price_unit,
    CAST(FLOOR(t2.seller_price) AS BIGINT) * t1.quantity AS sell_price,
    CAST(FLOOR(t2.seller_price) AS BIGINT) - t1.margin_price AS diff_from_min_price,

    -- Расчётная/фактическая прибыль и выплаты из исходного отчёта
    (((((t1.margin_price - t1.delivery_fee) - t1.category_fee) - t1.ff_fee) - t1.adapter_fee) - t1.supplier_price)
        * t1.quantity AS expected_profit,
    CASE
        WHEN (
            t2.seller_price IS NOT NULL
            AND t2.logistic IS NOT NULL
            AND t2.agent_rate IS NOT NULL
        ) THEN CASE
            WHEN t2.refund_total_to_seller = 0 THEN
                ((((t2.seller_price - t2.logistic / t1.quantity) - t2.agent_rate) - t1.ff_fee) - t1.adapter_fee)
                - CASE WHEN t5.supplier_price = 0 THEN t1.supplier_price ELSE t5.supplier_price END
            ELSE (-t2.logistic) / t1.quantity - t1.ff_fee
        END
        ELSE CASE
            WHEN t2.logistic IS NOT NULL THEN (-t2.logistic) / t1.quantity - t1.ff_fee
            ELSE 0
        END
    END AS profit_unit,
    (
        CASE
            WHEN (
                t2.seller_price IS NOT NULL
                AND t2.logistic IS NOT NULL
                AND t2.agent_rate IS NOT NULL
            ) THEN CASE
                WHEN t2.refund_total_to_seller = 0 THEN
                    ((((t2.seller_price - t2.logistic / t1.quantity) - t2.agent_rate) - t1.ff_fee) - t1.adapter_fee)
                    - CASE WHEN t5.supplier_price = 0 THEN t1.supplier_price ELSE t5.supplier_price END
                ELSE (-t2.logistic) / t1.quantity - t1.ff_fee
            END
            ELSE CASE
                WHEN t2.logistic IS NOT NULL THEN (-t2.logistic) / t1.quantity - t1.ff_fee
                ELSE 0
            END
        END
    ) * t1.quantity AS profit,
    CASE
        WHEN (
            t1.status_name IN ('Отменен', 'REJECTED', 'Отказ при получении')
            OR t2.refund_quantity > 0
        ) THEN CASE
            WHEN t1.status_name LIKE 'REJECTED' THEN 0
            ELSE CASE
                WHEN t2.refund_quantity > 0 THEN -t1.delivery_fee - t1.ff_fee
                ELSE -t1.delivery_fee
            END
        END
        ELSE (t1.margin_price - t1.category_fee) * t1.quantity - t1.delivery_fee
    END AS expected_payout,
    CASE
        WHEN (t2.total IS NOT NULL AND t2.logistic IS NOT NULL) THEN t2.total - t2.logistic
        WHEN (t2.total IS NULL AND t2.logistic IS NOT NULL) THEN -t2.logistic
        WHEN (t2.total IS NOT NULL AND t2.logistic IS NULL) THEN t2.total
        ELSE 0
    END AS payout_if_paid,

    -- Поля для дополнительной логики в Python-слое
    t2.refund_quantity AS refund_quantity,
    t2.refund_total_to_seller AS refund_total_to_seller,
    t2.total AS total

FROM (
    SELECT *
    FROM e_com.sm_orders
) AS t1
JOIN (
    SELECT
        id,
        CASE
            WHEN (EXTRACT(DOW FROM created_at) = 6 AND created_at::time >= '09:00:00') THEN
                date_trunc('day', created_at) + INTERVAL '2 days' + INTERVAL '6 hours'
            WHEN EXTRACT(DOW FROM created_at) = 0 THEN
                date_trunc('day', created_at) + INTERVAL '1 day' + INTERVAL '6 hours'
            WHEN created_at::time >= '09:00:00' THEN
                date_trunc('day', created_at) + INTERVAL '1 day' + INTERVAL '6 hours'
            ELSE
                date_trunc('day', created_at) + INTERVAL '6 hours'
        END AS shipment_date
    FROM e_com.sm_orders
) AS t4
    ON t1.id = t4.id
FULL OUTER JOIN (
    SELECT *
    FROM e_com.sm_price_reports
) AS t2
    ON t1.id = t2.sm_orders_id
JOIN (
    WITH latest_stock_movement AS (
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
            sm.id AS sm_order_id,
            CASE
                WHEN lsm.all_split_orders_id IS NULL THEN aso.id
                WHEN lsm.type = 'lost' THEN aso.id
                ELSE fst.first_source_order_id
            END AS source_all_split_orders_id
        FROM e_com.sm_orders sm
        INNER JOIN e_com.all_split_orders aso ON sm.id = aso.sm_orders_id
        LEFT JOIN latest_stock_movement lsm ON aso.id = lsm.all_split_orders_id
        LEFT JOIN first_stock_transaction fst ON lsm.warehouse_new_id = fst.warehouse_new_id
    )
    SELECT
        sm.id AS sm_order_id,
        COALESCE(ots.ru_custom_price, ots.ru_price, 0) AS supplier_price
    FROM e_com.sm_orders sm
    LEFT JOIN source_order_mapping som ON sm.id = som.sm_order_id
    LEFT JOIN e_com.all_split_orders aso_source ON som.source_all_split_orders_id = aso_source.id
    LEFT JOIN e_com.order_to_supplier ots ON aso_source.order_to_supplier_id = ots.id
) AS t5
    ON t1.id = t5.sm_order_id
JOIN (
    SELECT *
    FROM e_com.sm_feed_items
) AS t3
    ON t1.feed_item_id = t3.id
"""


def build_sm_order_items_query(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> tuple[TextClause, dict[str, Any]]:
    """Возвращает (sql, params) для заказов Sportmaster."""
    conditions, params = _build_common_filters(
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
        seller_expr="sm.seller_id",
        created_at_expr="sm.created_at",
    )

    where = ("\nWHERE " + "\n  AND ".join(conditions)) if conditions else ""
    sql = text(
        "SELECT DISTINCT * FROM (\n"
        + _SM_ORDER_ITEMS_SELECT
        + "\n) sm"
        + where
        + "\nORDER BY sm.created_at DESC"
    )
    return sql, params


SM_SELLERS_SQL = text("""
SELECT 1 AS id, 'Sportmaster' AS seller_name
""")


SM_DATE_RANGE_SQL = text("""
SELECT
    MIN(created_at)::date AS min_date,
    MAX(created_at)::date AS max_date
FROM e_com.sm_orders
""")
