"""
SQL-запросы к базе данных.
Намеренно разбиты на отдельные запросы для читаемости и поддерживаемости.
"""
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Запрос 1: Базовые данные по позициям заказов
# Один ряд = одна позиция заказа (offer_id внутри заказа)
# ---------------------------------------------------------------------------
ORDER_ITEMS_SQL = text("""
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
    COALESCE(tr.status, o.status) AS order_status,
    mr.status                     AS fulfillment_status,
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

    -- Скидки из отчёта о транзакциях
    COALESCE(tr.our_discount, 0)           AS our_discount,
    COALESCE(tr.market_discount, 0)        AS market_discount,
    COALESCE(tr.other_market_discounts, 0) AS other_discounts,
    COALESCE(tr.market_discount_sber, 0)   AS sber_discount,
    COALESCE(tr.market_discount_ya_plus, 0) AS ya_plus_discount,
    COALESCE(tr.customer_refund_amount, 0) AS customer_refund,

    -- Расчётные комиссии из нашей системы (заполнены не для всех)
    COALESCE(i.markup_yandex_accepting_payments_fee_amount, 0) AS calc_accepting_fee,
    COALESCE(i.markup_yandex_order_processing_fee_amount, 0)   AS calc_processing_fee,
    COALESCE(i.markup_custom_delivery_fee_value_amount, 0)     AS calc_custom_delivery_fee,
    COALESCE(i.markup_margin_amount, 0)                        AS calc_margin_amount,
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
ORDER BY o.created_at DESC
""")


# ---------------------------------------------------------------------------
# Запрос 2: Агрегированные данные о платежах по заказам
# Из ya_payments_reports — бонусы, скидки, штрафы, дата выплаты
# ---------------------------------------------------------------------------
PAYMENT_AGGREGATES_SQL = text("""
SELECT
    ya_orders_id,
    MAX(payment_date) AS last_payment_date,

    -- Баллы начислены нам за скидки Маркета / Яндекс Плюс
    SUM(CASE
        WHEN transaction_source IN (
            'Баллы за скидку Маркета',
            'Баллы за скидку Яндекс Плюс',
            'Возврат скидки за участие в совместных акциях'
        ) THEN transaction_amount ELSE 0
    END) AS bonus_points,

    -- Скидки, которые мы финансировали из своего кармана
    SUM(CASE
        WHEN transaction_source IN (
            'Скидка за участие в совместных акциях',
            'Возврат баллов за скидку Маркета'
        ) THEN transaction_amount ELSE 0
    END) AS promo_discounts,

    -- Штраф: отмена по вине продавца
    SUM(CASE
        WHEN item_name_or_service_name = 'Отмена заказа по вине продавца'
         AND transaction_source = 'Оплата услуг Яндекс.Маркета'
         AND payment_status = 'Удержан из платежей покупателей'
        THEN transaction_amount ELSE 0
    END) AS seller_cancel_penalty,

    -- Штраф: поздняя отгрузка/доставка
    SUM(CASE
        WHEN item_name_or_service_name = 'Отгрузка или доставка не вовремя'
         AND transaction_source = 'Оплата услуг Яндекс.Маркета'
         AND payment_status = 'Удержан из платежей покупателей'
        THEN transaction_amount ELSE 0
    END) AS late_ship_penalty

FROM e_com.ya_payments_reports
WHERE ya_orders_id IS NOT NULL
GROUP BY ya_orders_id
""")


# ---------------------------------------------------------------------------
# Запрос 3: Список продавцов
# ---------------------------------------------------------------------------
SELLERS_SQL = text("""
SELECT id, seller_name
FROM e_com.platform_sellers
ORDER BY seller_name
""")
