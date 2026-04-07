from sqlalchemy import text

ORDERS_ECONOMICS_SQL = text("""
WITH
order_item_base AS (
  SELECT
    t1.id AS order_pk,
    t1.created_at,
    t1.shipment_date,
    t5.seller_name,
    t1.order_id AS original_order_id_numeric,
    t2.offer_id,
    t2.id AS order_item_identifier,
    t4.name AS product_name,
    COALESCE(t7.status, t1.status) AS effective_order_status,
    t6.status AS margin_report_status,
    t6.payment_status AS margin_report_payment_status,
    t2.count AS item_count,
    t2.supplier_name,
    t2.base_price,
    COALESCE(t9.value, 0) AS ff_fee_value_per_item,
    COALESCE(t10.value, 0) AS socket_adapter_fee_value_per_item,
    t2.margin_percent,
    t2.final_price,
    t2.buyer_price,
    COALESCE(t2.subsidy, 0) AS subsidy,
    COALESCE(t6.market_services, 0) AS market_services,
    t6.payment_status IN (
      'Переведён',
      'Не будет переведён из-за отмены заказа',
      'Удержан из платежей покупателей'
    ) AS is_payment_status_relevant,
    COALESCE(t7.our_discount, 0) AS our_discount,
    COALESCE(t7.market_discount, 0) AS market_discount,
    COALESCE(t7.other_market_discounts, 0) AS other_market_discounts,
    COALESCE(t7.market_discount_sber, 0) AS market_discount_sber,
    COALESCE(t7.market_discount_ya_plus, 0) AS market_discount_ya_plus,
    COALESCE(t7.customer_refund_amount, 0) AS customer_refund_amount,
    t2.total_sum_of_all_added_costs,
    t2.markup_ff_fees_amount,
    t2.markup_yandex_accepting_payments_fee_amount,
    t2.markup_yandex_order_processing_fee_amount,
    t2.markup_socket_adapter_fee_amount,
    t2.markup_custom_delivery_fee_value_amount,
    t2.markup_margin_amount,
    t2.commission_yandex_category_fee_amount,
    t2.commission_yandex_transfer_payments_fee_amount,
    t2.commission_yandex_delivery_fee_actual_amount
  FROM e_com.ya_orders AS t1
    JOIN e_com.ya_order_items AS t2 ON t1.id = t2.order_id
    JOIN e_com.platform_sellers AS t5 ON t1.seller_id = t5.id
    JOIN e_com.yandex_feed_items AS t3 ON t2.feed_item_id = t3.id
    JOIN e_com.unique_product_groups AS t4 ON t3.unique_product_group_id = t4.id
    LEFT JOIN e_com.ya_order_margin_report AS t6 ON t1.id = t6.ya_orders_id
    LEFT JOIN e_com.ya_order_transactions_report AS t7 ON t2.id = t7.ya_order_items_id
    LEFT JOIN e_com.market_modifier_yandex AS t8 ON t3.market_modifier_yandex_id = t8.id
    LEFT JOIN e_com.ff_fees AS t9 ON t8.ff_fees_id = t9.id
    LEFT JOIN e_com.socket_adapter_fee AS t10 ON t8.socket_adapter_fee_id = t10.id
),
payments_agg AS (
  SELECT
    ya_orders_id AS order_pk,
    SUM(CASE
      WHEN transaction_source IN (
        'Баллы за скидку Маркета',
        'Баллы за скидку Яндекс Плюс',
        'Возврат скидки за участие в совместных акциях'
      ) THEN transaction_amount ELSE 0 END) AS sum_bonus_points,
    SUM(CASE
      WHEN transaction_source IN (
        'Скидка за участие в совместных акциях',
        'Возврат баллов за скидку Маркета'
      ) THEN transaction_amount ELSE 0 END) AS sum_promo_discount,
    SUM(CASE
      WHEN item_name_or_service_name = 'Отмена заказа по вине продавца'
        AND transaction_source = 'Оплата услуг Яндекс.Маркета'
        AND payment_status = 'Удержан из платежей покупателей'
      THEN transaction_amount ELSE 0 END) AS sum_seller_cancel_fee,
    SUM(CASE
      WHEN item_name_or_service_name = 'Отгрузка или доставка не вовремя'
        AND transaction_source = 'Оплата услуг Яндекс.Маркета'
        AND payment_status = 'Удержан из платежей покупателей'
      THEN transaction_amount ELSE 0 END) AS sum_late_ship_fee
  FROM e_com.ya_payments_reports
  GROUP BY ya_orders_id
),
item_calc AS (
  SELECT
    oib.original_order_id_numeric,
    oib.offer_id,
    oib.order_item_identifier,
    CASE
      WHEN oib.margin_report_status IN (
        'Заказ отменен до обработки', 'Невыкуп принят на складе',
        'Отменен при обработке', 'Полный возврат принят на складе', 'Отменен при доставке'
      ) OR oib.margin_report_payment_status = 'Не будет переведён из-за отмены заказа'
      THEN 0 - oib.market_services
      ELSE (
        (oib.buyer_price + oib.subsidy) * oib.item_count
        - oib.market_services
        - oib.our_discount
        - oib.market_discount
        - oib.other_market_discounts
        - oib.market_discount_sber
        - oib.market_discount_ya_plus
        + oib.customer_refund_amount
      )
    END AS e72_val,
    CASE
      WHEN oib.margin_report_status IN (
        'Невыкуп принят на складе', 'Полный возврат принят на складе', 'Отменен при доставке'
      ) THEN oib.ff_fee_value_per_item * oib.item_count
      WHEN oib.margin_report_status IN (
        'Заказ отменен до обработки', 'Отменен при обработке'
      ) THEN 0
      ELSE oib.base_price * oib.item_count
    END AS e73_val,
    CASE
      WHEN oib.margin_report_status IN (
        'Заказ отменен до обработки', 'Невыкуп принят на складе',
        'Отменен при обработке', 'Полный возврат принят на складе', 'Отменен при доставке'
      ) OR oib.margin_report_payment_status = 'Не будет переведён из-за отмены заказа'
      THEN 0
      ELSE oib.final_price * oib.item_count
           - oib.base_price * oib.item_count * (CAST(oib.margin_percent AS DOUBLE PRECISION) / 100 + 1)
    END AS e66_val
  FROM order_item_base oib
),
item_agg AS (
  SELECT
    original_order_id_numeric,
    offer_id,
    AVG(e72_val) AS avg_e72,
    AVG(e73_val) AS avg_e73,
    AVG(e66_val) AS avg_e66
  FROM item_calc
  GROUP BY original_order_id_numeric, offer_id
),
payment_summary AS (
  SELECT
    order_id AS original_order_id_numeric,
    MAX(payment_date) AS max_payment_date,
    SUM(CASE WHEN payment_date IS NOT NULL THEN transaction_amount ELSE 0 END) AS total_payout
  FROM e_com.ya_payments_reports
  WHERE order_id IS NOT NULL
  GROUP BY order_id
)
SELECT
  oib.order_item_identifier,
  MAX(oib.created_at) AS created_at,
  MAX(oib.shipment_date) AS shipment_date,
  MAX(oib.seller_name) AS seller_name,
  MAX(TO_CHAR(oib.original_order_id_numeric, 'FM999999999999999999')) AS order_id_str,
  MAX(oib.offer_id) AS offer_id,
  MAX(oib.product_name) AS product_name,
  MAX(oib.effective_order_status) AS effective_order_status,
  MAX(oib.margin_report_status) AS margin_report_status,
  MAX(oib.margin_report_payment_status) AS margin_report_payment_status,
  MAX(oib.item_count) AS item_count,
  MAX(oib.supplier_name) AS supplier_name,
  MAX(oib.base_price * oib.item_count) AS base_price_total,
  MAX(oib.ff_fee_value_per_item * oib.item_count) AS ff_fee_total,
  MAX(oib.socket_adapter_fee_value_per_item * oib.item_count) AS socket_adapter_fee_total,
  MAX(oib.base_price * oib.item_count * (CAST(oib.margin_percent AS DOUBLE PRECISION) / 100 + 1)) AS price_with_margin,
  MAX(oib.margin_percent) AS margin_percent,
  MAX(oib.final_price * oib.item_count) AS final_price_total,
  MAX(CASE
    WHEN oib.margin_report_status IN (
      'Заказ отменен до обработки', 'Невыкуп принят на складе',
      'Отменен при обработке', 'Полный возврат принят на складе', 'Отменен при доставке'
    ) OR oib.margin_report_payment_status = 'Не будет переведён из-за отмены заказа'
    THEN 0
    ELSE oib.base_price * oib.item_count * (CAST(oib.margin_percent AS DOUBLE PRECISION) / 100)
  END) AS margin_value,
  MAX((oib.buyer_price + COALESCE(oib.subsidy, 0)) * oib.item_count) AS buyer_price_subsidy_total,
  MAX(COALESCE(pay.sum_bonus_points, 0)) AS sum_bonus_points,
  MAX(oib.market_services) AS market_services,
  MAX((oib.buyer_price + COALESCE(oib.subsidy, 0)) * oib.item_count - oib.final_price * oib.item_count) AS price_diff,
  MAX(COALESCE(pay.sum_promo_discount, 0)) AS sum_promo_discount,
  MAX(COALESCE(ia.avg_e72, 0) + COALESCE(pay.sum_bonus_points, 0) + COALESCE(pay.sum_promo_discount, 0)) AS e72_e20_e21,
  MAX((COALESCE(ia.avg_e72, 0) + COALESCE(pay.sum_bonus_points, 0) + COALESCE(pay.sum_promo_discount, 0)) - COALESCE(ia.avg_e73, 0)) AS e72_e20_e21_minus_e73,
  MAX(CASE
    WHEN COALESCE(ia.avg_e66, 0) = 0 THEN 0
    ELSE (
      ((COALESCE(ia.avg_e72, 0) + COALESCE(pay.sum_bonus_points, 0) + COALESCE(pay.sum_promo_discount, 0))
        - COALESCE(ia.avg_e73, 0) - COALESCE(ia.avg_e66, 0))
      / NULLIF(COALESCE(ia.avg_e66, 0), 0)
    ) * 100
  END) AS margin_percent_calc,
  MAX(COALESCE(ia.avg_e72, 0)) AS avg_e72,
  MAX(COALESCE(ia.avg_e72, 0) - COALESCE(ia.avg_e73, 0)) AS e72_minus_e73,
  MAX(COALESCE(pay.sum_seller_cancel_fee, 0)) AS seller_cancel_fee,
  MAX(COALESCE(pay.sum_late_ship_fee, 0)) AS late_ship_fee,
  MAX(CASE WHEN oib.is_payment_status_relevant THEN COALESCE(ia.avg_e72, 0) ELSE 0 END) AS conditional_e72,
  MAX(COALESCE(ps.total_payout, 0)) AS sum_vyplat,
  MAX(ps.max_payment_date) AS date_vyplat,
  MAX(COALESCE(oib.total_sum_of_all_added_costs, 0)) AS total_added_costs,
  MAX(COALESCE(oib.markup_ff_fees_amount, 0)) AS markup_ff_fees,
  MAX(COALESCE(oib.markup_yandex_accepting_payments_fee_amount, 0)) AS markup_accepting_payments,
  MAX(COALESCE(oib.markup_yandex_order_processing_fee_amount, 0)) AS markup_order_processing,
  MAX(COALESCE(oib.markup_socket_adapter_fee_amount, 0)) AS markup_socket_adapter,
  MAX(COALESCE(oib.markup_custom_delivery_fee_value_amount, 0)) AS markup_custom_delivery,
  MAX(COALESCE(oib.markup_margin_amount, 0)) AS markup_margin,
  MAX(COALESCE(oib.commission_yandex_category_fee_amount, 0)) AS commission_category,
  MAX(COALESCE(oib.commission_yandex_transfer_payments_fee_amount, 0)) AS commission_transfer_payments,
  MAX(COALESCE(oib.commission_yandex_delivery_fee_actual_amount, 0)) AS commission_delivery
FROM order_item_base oib
  LEFT JOIN payments_agg pay ON oib.order_pk = pay.order_pk
  LEFT JOIN item_agg ia
    ON oib.original_order_id_numeric = ia.original_order_id_numeric
    AND oib.offer_id = ia.offer_id
  LEFT JOIN payment_summary ps ON oib.original_order_id_numeric = ps.original_order_id_numeric
GROUP BY oib.order_item_identifier
ORDER BY MAX(oib.created_at) DESC NULLS LAST
""")
