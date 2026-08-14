"""
Расчёт показателей юнит-экономики.
Чистые функции без side-эффектов.

Логика расчётов:
- sell_price          = из ya_order_margin_report — цена, которую ЯМ фиксирует как продажу
                        = buyer_payment + субсидия_ЯМ (баллы Маркета/Плюса) за весь заказ
- market_services     = из ya_order_margin_report — комиссии ЯМ за заказ
- expected_payout     = sell_price - market_services — фактический перевод от ЯМ
- bonus_points        = субсидия ЯМ (tr.bonuses = subsidy) — СПРАВОЧНО, уже в sell_price!
                        НЕ прибавлять к прибыли — иначе двойной счёт.
- promo_discounts     = наши расходы на промо из баланса баллов (отрицательная сумма)
                        Вычитаются из дохода отдельно (settlement через баланс баллов)
- our_costs           = base_price + ff_fee + socket_adapter + custom_delivery
                        (за доставленное количество)
- expected_profit     = expected_payout - our_costs (без учёта промо)
- profit              = expected_payout + promo_discounts - our_costs (с учётом промо)
- fact_commissions    = реальные удержания ЯМ из платёжного отчёта ≈ market_services
"""

import numpy as np
import pandas as pd

from wolle_economy.enums import (
    CANCELLED_BEFORE_SHIP,
    CANCELLED_STATUSES,
    PAID_STATUSES,
    RETURNED_STATUSES,
    FulfillmentStatus,
)


def merge_with_payments(orders_df: pd.DataFrame, payments_df: pd.DataFrame) -> pd.DataFrame:
    """Объединяет данные о заказах с агрегированными данными о платежах."""
    return orders_df.merge(
        payments_df.rename(columns={"ya_orders_id": "ya_order_id"}),
        on="ya_order_id",
        how="left",
    )


def _apply_payment_refund_fallback(df: pd.DataFrame, q: pd.Series) -> pd.DataFrame:
    """Распознаёт полный возврат по платёжному отчёту.

    Это fallback для однопозиционных заказов, когда отчёт по товарам
    ещё содержит старый статус, но платёжный отчёт уже содержит полный
    возврат оплаты покупателя и субсидии Маркета.
    """
    refund_total = pd.to_numeric(
        df.get("payment_refund_total", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    gross_sell = pd.to_numeric(df.get("sell_price"), errors="coerce")
    fallback_sell = (df["buyer_price"].fillna(0) + df["subsidy"].fillna(0)) * q
    gross_sell = gross_sell.fillna(fallback_sell)
    item_count = pd.to_numeric(
        df.get("order_items_count", pd.Series(1, index=df.index)), errors="coerce"
    ).fillna(1)
    transaction_refund = pd.to_numeric(
        df.get("returned_sell_price", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)

    full_refund = (
        item_count.eq(1)
        & gross_sell.gt(0)
        & refund_total.ge(gross_sell.sub(0.01))
        & transaction_refund.eq(0)
    )
    df["payment_refund_fallback"] = full_refund
    df.loc[full_refund, "returned_sell_price"] = gross_sell[full_refund]
    df.loc[full_refund, "tr_delivered_quantity"] = 0
    df.loc[full_refund, "fulfillment_status"] = FulfillmentStatus.RETURN_CREATED
    return df


def _compute_base_totals(df: pd.DataFrame, q: pd.Series) -> pd.DataFrame:
    """Базовые итого: цены × количество и наценка."""
    df["base_price_total"] = df["base_price"] * q
    df["ff_fee_total"] = df["ff_fee"] * q
    df["socket_adapter_total"] = df["socket_adapter_fee"] * q
    df["min_sell_price_total"] = df["min_sell_price"] * q

    # Фактическая закупочная цена из order_to_supplier (см. queries.py).
    # Если значения нет или оно равно 0 — используем плановый base_price.
    # base_price_total остаётся плановым (на нём держится our_margin /
    # price_with_margin), а в our_costs идёт effective_purchase_total.
    if "supplier_price_fact" in df.columns:
        spf = pd.to_numeric(df["supplier_price_fact"], errors="coerce").fillna(0)
    else:
        spf = pd.Series(0.0, index=df.index)
    df["supplier_price_fact"] = spf
    df["effective_purchase_total"] = np.where(
        spf > 0,
        spf * q,
        df["base_price_total"],
    )
    df["uses_fact_purchase_price"] = spf > 0

    # Фиксированная доставка — наш расход для любого магазина.
    cdn = pd.to_numeric(
        df.get("custom_delivery_fee", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    df["custom_delivery_fee_total"] = cdn * q

    margin = df["margin_percent"].fillna(0).astype(float)
    df["our_margin"] = df["base_price_total"] * margin / 100
    df["price_with_margin"] = df["base_price_total"] * (1 + margin / 100)
    return df


def _compute_payouts(df: pd.DataFrame, q: pd.Series) -> pd.DataFrame:
    """sell_price, expected_payout, calc_commissions, bonus_points, promo_discounts."""
    # sell_price: берём из margin_report, иначе считаем сами
    df["sell_price"] = df["sell_price"].where(
        df["sell_price"].notna(),
        (df["buyer_price"] + df["subsidy"]) * q,
    )

    # При частичном возврате margin_report хранит sell_price за все штуки.
    # Корректируем: вычитаем sell_price возвращённых транзакций (= buyer_price + subsidy за возврат).
    # Нельзя использовать customer_refund_amount — он содержит только buyer_price без субсидии,
    # а субсидия возврата списывается отдельно через "Возврат баллов за скидку Маркета".
    # Для обычных заказов returned_sell_price = 0, поэтому изменений нет.
    returned_sell = (
        df["returned_sell_price"].fillna(0) if "returned_sell_price" in df.columns else 0.0
    )
    df["sell_price"] = df["sell_price"] - returned_sell

    # Ожидаемая выплата = цена продажи минус комиссии ЯМ
    df["expected_payout"] = (df["sell_price"].fillna(0) - df["market_services"].fillna(0)).clip(
        lower=0
    )

    # Полный план комиссий из снимка позиции заказа. Все исходные суммы
    # рассчитаны за единицу товара, поэтому для строки показываем итог × quantity.
    def planned_total(column: str) -> pd.Series:
        values = pd.to_numeric(
            df.get(column, pd.Series(0.0, index=df.index)),
            errors="coerce",
        ).fillna(0)
        return values * q

    df["calc_category_fee_total"] = planned_total("calc_category_fee")
    df["calc_transfer_fee_total"] = planned_total("calc_transfer_fee")
    df["calc_delivery_fee_total"] = planned_total("calc_delivery_fee")
    df["calc_accepting_payment_fee_total"] = planned_total("calc_accepting_payment_fee")
    df["calc_order_processing_fee_total"] = planned_total("calc_order_processing_fee")
    planned_columns = [
        "calc_category_fee_total",
        "calc_transfer_fee_total",
        "calc_delivery_fee_total",
        "calc_accepting_payment_fee_total",
        "calc_order_processing_fee_total",
    ]
    df["calc_commissions"] = df[planned_columns].sum(axis=1)

    # Субсидия ЯМ — СПРАВОЧНО, уже включена в sell_price, не прибавлять к прибыли
    df["bonus_points"] = df["tr_bonuses"].fillna(0)

    # Промо-скидки (отрицательная сумма)
    if "promo_discounts" not in df.columns:
        df["promo_discounts"] = 0.0
    df["promo_discounts"] = df["promo_discounts"].fillna(0)

    if "fact_commissions" not in df.columns:
        fact_commissions_raw = pd.Series(np.nan, index=df.index)
    else:
        fact_commissions_raw = pd.to_numeric(df["fact_commissions"], errors="coerce")

    # Итоговая разбивка united-orders учитывает поздние корректировки и
    # компенсации Яндекса. Она приоритетнее реконструкции по платёжному реестру,
    # где одинаковая услуга может встречаться начислением и сторно отдельно.
    report_details = df.get(
        "report_service_details",
        pd.Series(None, index=df.index, dtype=object),
    )
    report_total = pd.to_numeric(
        df.get("market_services", pd.Series(np.nan, index=df.index)),
        errors="coerce",
    )
    report_available = report_details.map(lambda value: isinstance(value, dict)) & report_total.notna()

    def report_component(key: str) -> pd.Series:
        return pd.to_numeric(
            report_details.map(
                lambda value: value.get(key) if isinstance(value, dict) else np.nan
            ),
            errors="coerce",
        ).fillna(0)

    report_components = {
        key: report_component(key)
        for key in (
            "placement",
            "warehouse_processing",
            "loyalty",
            "boost",
            "installment",
            "delivery",
            "middle_mile_delivery",
            "express_delivery",
            "cross_border_delivery",
            "accepting_payment",
            "transfer",
            "pickup",
            "order_processing",
            "sorting_center_processing",
            "warehouse_order_processing",
            "storage",
            "return_delivery",
            "sales_reward",
        )
    }
    report_components_total = sum(report_components.values(), pd.Series(0.0, index=df.index))
    report_complete = report_available & report_components_total.sub(report_total).abs().le(0.011)
    fact_commissions_raw = fact_commissions_raw.where(~report_available, report_total)

    if "fact_commissions_available" in df.columns:
        fact_available = df["fact_commissions_available"].fillna(False).astype(bool)
    else:
        fact_available = fact_commissions_raw.notna()
    fact_available |= report_available
    df["fact_commissions_available"] = fact_available
    df["fact_commissions"] = fact_commissions_raw.fillna(0)

    details_complete = (
        df.get(
            "fact_commission_details_complete",
            pd.Series(False, index=df.index),
        )
        .fillna(False)
        .astype(bool)
    )
    details_complete = details_complete.where(~report_available, report_complete)

    report_fact_components = {
        "fact_category_fee": report_components["placement"],
        "fact_transfer_fee": report_components["transfer"],
        "fact_delivery_fee": (
            report_components["delivery"]
            + report_components["middle_mile_delivery"]
            + report_components["express_delivery"]
            + report_components["cross_border_delivery"]
        ),
        "fact_accepting_payment_fee": report_components["accepting_payment"],
        "fact_order_processing_fee": (
            report_components["order_processing"]
            + report_components["sorting_center_processing"]
            + report_components["warehouse_order_processing"]
        ),
        "fact_other_fees": sum(
            (
                report_components[key]
                for key in (
                    "warehouse_processing",
                    "loyalty",
                    "boost",
                    "installment",
                    "pickup",
                    "storage",
                    "return_delivery",
                    "sales_reward",
                )
            ),
            pd.Series(0.0, index=df.index),
        ),
        "fact_unclassified_fees": pd.Series(0.0, index=df.index),
    }
    for column, report_values in report_fact_components.items():
        existing = pd.to_numeric(
            df.get(column, pd.Series(np.nan, index=df.index)),
            errors="coerce",
        )
        df[column] = existing.where(~report_available, report_values)

    order_items_count = pd.to_numeric(
        df.get("order_items_count", pd.Series(1, index=df.index)),
        errors="coerce",
    ).fillna(1)
    # Факт агрегирован на заказ. Для multi-item заказа его нельзя сравнивать
    # с планом одной позиции без произвольного распределения между товарами.
    details_complete &= order_items_count.eq(1)
    df["fact_commission_details_complete"] = details_complete

    fact_plan_pairs = {
        "category_fee_diff": ("fact_category_fee", "calc_category_fee_total"),
        "transfer_fee_diff": ("fact_transfer_fee", "calc_transfer_fee_total"),
        "yandex_delivery_fee_diff": ("fact_delivery_fee", "calc_delivery_fee_total"),
        "accepting_payment_fee_diff": (
            "fact_accepting_payment_fee",
            "calc_accepting_payment_fee_total",
        ),
        "order_processing_fee_diff": (
            "fact_order_processing_fee",
            "calc_order_processing_fee_total",
        ),
    }
    for diff_column, (fact_column, plan_column) in fact_plan_pairs.items():
        fact_values = pd.to_numeric(
            df.get(fact_column, pd.Series(np.nan, index=df.index)),
            errors="coerce",
        )
        df[fact_column] = fact_values
        df[diff_column] = (fact_values - df[plan_column]).where(details_complete)

    for column in ("fact_other_fees", "fact_unclassified_fees"):
        df[column] = pd.to_numeric(
            df.get(column, pd.Series(np.nan, index=df.index)),
            errors="coerce",
        )

    total_comparison_available = fact_available & order_items_count.eq(1)
    df["commissions_diff"] = (df["fact_commissions"] - df["calc_commissions"]).where(
        total_comparison_available
    )

    return df


def _compute_profits(df: pd.DataFrame, our_costs: pd.Series) -> pd.DataFrame:
    """expected_profit, income_after_fees, profit, profit_no_promo, diff_from_min_price."""
    df["expected_profit"] = df["expected_payout"] - our_costs

    promo = df["promo_discounts"].fillna(0)  # отрицательная сумма
    df["income_after_fees"] = df["expected_payout"]
    df["income_after_fees_promo"] = df["expected_payout"] + promo

    df["profit"] = df["income_after_fees_promo"] - our_costs
    df["profit_no_promo"] = df["income_after_fees"] - our_costs

    df["diff_from_min_price"] = df["sell_price"].fillna(0) - df["min_sell_price_total"]
    return df


def _compute_actual_profit(df: pd.DataFrame, our_costs: pd.Series) -> pd.DataFrame:
    """payout_if_paid, last_payment_date, actual_profit, profit_vs_expected."""
    is_transferred = df["payment_status"].isin(PAID_STATUSES)
    df["payout_if_paid"] = np.where(is_transferred, df["expected_payout"], 0.0)

    # Дата выплаты: сначала из транзакционного отчёта (надёжнее), потом из платёжного
    tr_raw = (
        df["tr_customer_payment_date"]
        if "tr_customer_payment_date" in df.columns
        else pd.Series(pd.NA, index=df.index)
    )
    pay_raw = (
        df["last_payment_date"]
        if "last_payment_date" in df.columns
        else pd.Series(pd.NA, index=df.index)
    )
    refund_raw = (
        df["payment_refund_date"]
        if "payment_refund_date" in df.columns
        else pd.Series(pd.NA, index=df.index)
    )
    tr_date = pd.to_datetime(tr_raw, errors="coerce", utc=True)
    pay_date = pd.to_datetime(pay_raw, errors="coerce", utc=True)
    refund_date = pd.to_datetime(refund_raw, errors="coerce", utc=True)
    df["last_payment_date"] = tr_date.fillna(pay_date).fillna(refund_date)

    has_payment = df["last_payment_date"].notna() | is_transferred
    is_cancelled_before = df["fulfillment_status"].isin(CANCELLED_BEFORE_SHIP)

    # Для факта приоритетны реальные удержания из платёжного отчёта.
    # market_services остаётся fallback для заказов без такого отчёта.
    fact_available = df.get(
        "fact_commissions_available", pd.Series(False, index=df.index)
    ).fillna(False).astype(bool)
    fact_commissions = pd.to_numeric(
        df.get("fact_commissions", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    market_services = pd.to_numeric(
        df.get("market_services", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    actual_market_services = pd.Series(
        np.where(fact_available, fact_commissions, market_services),
        index=df.index,
    )
    promo = pd.to_numeric(
        df.get("promo_discounts", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    compensations = pd.to_numeric(
        df.get("compensations", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    actual_full = df["sell_price"].fillna(0) - actual_market_services + promo + compensations - our_costs

    # Отменён до отгрузки: расходы не понесены, учитываем только штрафы/компенсации
    cancelled_result = (
        df["expected_payout"]
        - df.get("seller_cancel_penalty", pd.Series(0.0, index=df.index)).fillna(0)
        - df.get("late_ship_penalty", pd.Series(0.0, index=df.index)).fillna(0)
    )

    df["actual_profit"] = np.where(
        ~has_payment,
        0.0,
        np.where(is_cancelled_before, cancelled_result, actual_full),
    )
    df["profit_vs_expected"] = df["actual_profit"] - df["expected_profit"]
    return df


def _compute_flags_and_lags(df: pd.DataFrame) -> pd.DataFrame:
    """Флаги статусов, производные поля аналитики, временны́е лаги."""
    df["order_id_str"] = df["order_id"].astype(str)

    sp = df["sell_price"].replace(0, np.nan)
    df["take_rate_pct"] = (df["market_services"] / sp * 100).round(2)
    df["margin_pct"] = (df["profit"] / sp * 100).round(2)
    df["margin_plan_pct"] = (df["our_margin"] / sp * 100).round(2)
    df["margin_fact_pct"] = df["margin_pct"]
    df["margin_fact_rub"] = df["profit"]

    # Маржа относительно закупочной цены (для сравнения с margin_percent из БД).
    # План: our_margin / base_price_total → совпадает с margin_percent.
    # Факт: profit / base_price_total → «сколько реально заработали сверх закупки».
    bp = df["base_price_total"].replace(0, np.nan)
    df["margin_plan_on_cost_pct"] = (df["our_margin"] / bp * 100).round(2)
    df["margin_fact_on_cost_pct"] = (df["profit"] / bp * 100).round(2)

    df["is_cancelled_before"] = df["fulfillment_status"].isin(CANCELLED_BEFORE_SHIP)
    df["is_returned"] = df["fulfillment_status"].isin(RETURNED_STATUSES)
    df["is_cancelled_any"] = df["fulfillment_status"].isin(CANCELLED_STATUSES)
    df["is_delivered"] = ~df["is_cancelled_any"]
    df["is_loss"] = df["profit"] < 0

    created = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    shipped = pd.to_datetime(df["shipment_date"], errors="coerce", utc=True)
    paid = pd.to_datetime(df["last_payment_date"], errors="coerce", utc=True)
    df["ship_lag_days"] = (shipped - created).dt.total_seconds() / 86400
    df["pay_lag_days"] = (paid - created).dt.total_seconds() / 86400

    return df


def calc_economics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Добавляет все производные финансовые колонки.
    Входной df должен содержать колонки из ORDER_ITEMS_SQL + PAYMENT_AGGREGATES_SQL.
    """
    df = df.copy()
    q = df["quantity"].fillna(1)
    df = _apply_payment_refund_fallback(df, q)

    # При частичном возврате затраты считаем только на доставленные единицы:
    # покупная цена возвращённых штук не потеряна — товар вернулся на склад.
    # Если транзакций нет (tr_delivered_quantity IS NULL) — fallback на полный quantity.
    if "tr_delivered_quantity" in df.columns:
        delivered_q = pd.to_numeric(df["tr_delivered_quantity"], errors="coerce").fillna(q)
    else:
        delivered_q = q

    df = _compute_base_totals(df, q)
    df = _compute_payouts(df, q)

    spf = df["supplier_price_fact"]
    effective_purchase_delivered = pd.Series(
        np.where(
            spf > 0,
            spf * delivered_q,
            df["base_price"] * delivered_q,
        ),
        index=df.index,
    )
    cdn = pd.to_numeric(
        df.get("custom_delivery_fee", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    our_costs = (
        effective_purchase_delivered
        + df["ff_fee"] * delivered_q
        + df["socket_adapter_fee"] * delivered_q
        + cdn * delivered_q
    )
    df["our_costs"] = our_costs

    df = _compute_profits(df, our_costs)
    df = _compute_actual_profit(df, our_costs)
    df = _compute_flags_and_lags(df)

    return df
