"""
Расчёт показателей юнит-экономики.
Чистые функции без side-эффектов.

Логика расчётов:
- sell_price          = из ya_order_margin_report — цена, которую ЯМ фиксирует как продажу
                        = buyer_payment + субсидия_ЯМ (баллы Маркета/Плюса) за весь заказ
- market_services     = из ya_order_margin_report — комиссии ЯМ за заказ
- expected_payout     = sell_price - market_services — доход до списаний баллов
- bonus_points        = субсидия ЯМ (tr.bonuses = subsidy) — СПРАВОЧНО, уже в sell_price!
                        НЕ прибавлять к прибыли — иначе двойной счёт.
- promo_discounts     = наши расходы на промо из баланса баллов (отрицательная сумма)
                        Вычитаются из дохода отдельно (settlement через баланс баллов)
- our_costs           = base_price + ff_fee + socket_adapter + custom_delivery
                        (за доставленное количество)
- expected_profit     = прибыль сохранённого плана публикации, иначе целевая наценка
- profit              = expected_payout + promo_discounts + boost_wallet_spend - our_costs
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


def merge_with_payments(
    orders_df: pd.DataFrame, payments_df: pd.DataFrame
) -> pd.DataFrame:
    """Объединяет данные о заказах с агрегированными данными о платежах."""
    return orders_df.merge(
        payments_df.rename(columns={"ya_orders_id": "ya_order_id"}),
        on="ya_order_id",
        how="left",
    )


def _allocate_order_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Общие суммы заказа распределяем по выручке, не дублируем в каждой позиции.

    Распределение услуг — оценка для позиции. Сумма по заказу сохраняется точно.
    Списания из wallet_sku уже привязаны к позиции SQL-запросом и не распределяются.
    """
    df["order_costs_allocated"] = False
    df["order_cost_share"] = 1.0
    if "ya_order_id" not in df:
        return df
    for _, indices in df.groupby("ya_order_id", sort=False).groups.items():
        if len(indices) < 2:
            continue
        group = df.loc[indices]
        weights = (
            (
                (group["buyer_price"].fillna(0) + group["subsidy"].fillna(0))
                * group["quantity"].fillna(1)
            )
            .astype(float)
            .clip(lower=0)
        )
        shares = (
            weights / weights.sum()
            if weights.sum() > 0
            else pd.Series(1 / len(group), index=indices)
        )
        shared_columns = [
            "sell_price",
            "market_services",
            "promo_discounts",
            "boost_wallet_spend",
            "fact_commissions",
        ]
        shared_columns += [
            name for name in df if name.startswith("fact_") and name.endswith("_fee")
        ]
        shared_columns += ["fact_other_fees", "fact_unclassified_fees"]
        for column in dict.fromkeys(shared_columns):
            if column not in df:
                continue
            values = (
                pd.to_numeric(group[column], errors="coerce").astype(float).dropna()
            )
            if values.empty:
                continue
            # Общий отчёт/платёжный агрегат одинаков в JOIN каждой позиции.
            df[column] = pd.to_numeric(df[column], errors="coerce").astype(float)
            df.loc[indices, column] = shares * values.iloc[0]
        if "report_service_details" in df:
            details = next(
                (
                    value
                    for value in group["report_service_details"]
                    if isinstance(value, dict)
                ),
                None,
            )
            if details is not None:
                for index in indices:
                    df.at[index, "report_service_details"] = {
                        key: float(value or 0) * shares.loc[index]
                        for key, value in details.items()
                    }
        df.loc[indices, "order_costs_allocated"] = True
        df.loc[indices, "order_cost_share"] = shares
    return df


def aggregate_yandex_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Итоги заказа: суммы позиций, затем пересчёт процентов от общей базы."""
    if df.empty:
        return df.copy()
    result = (
        df.drop_duplicates("ya_order_id").copy().set_index("ya_order_id", drop=False)
    )
    totals = {
        "quantity",
        "sell_price",
        "market_services",
        "promo_discounts",
        "boost_wallet_spend",
        "bonus_points",
        "our_margin",
        "price_with_margin",
        "our_costs",
        "expected_profit",
        "legacy_floor_profit",
        "expected_payout",
        "profit",
        "profit_no_promo",
        "actual_profit",
        "payout_if_paid",
        "profit_vs_expected",
        "income_after_fees",
        "income_after_fees_promo",
        "diff_from_min_price",
        "fact_commissions",
        "calc_commissions",
        "commissions_diff",
        "full_market_services",
        "cash_payout",
        "wallet_balance_change",
    }
    totals.update(column for column in df if column.endswith(("_total", "_diff")))
    totals.update(
        column
        for column in df
        if column.startswith("fact_") and column.endswith(("_fee", "_fees", "_spend"))
    )
    for column in totals.intersection(df.columns):
        result[column] = df.groupby("ya_order_id", sort=False)[column].sum(min_count=1)
    for flag in (
        "order_costs_allocated",
        "economics_is_estimated",
        "is_returned",
        "is_cancelled_any",
    ):
        if flag in df:
            result[flag] = df.groupby("ya_order_id", sort=False)[flag].any()
    result["margin_pct"] = (
        result["profit"] / result["sell_price"].replace(0, np.nan) * 100
    ).round(2)
    result["margin_fact_pct"] = result["margin_pct"]
    result["margin_fact_rub"] = result["profit"]
    result["margin_plan_pct"] = (
        result["our_margin"] / result["sell_price"].replace(0, np.nan) * 100
    ).round(2)
    result["margin_plan_on_cost_pct"] = (
        result["our_margin"] / result["base_price_total"].replace(0, np.nan) * 100
    ).round(2)
    result["margin_fact_on_cost_pct"] = (
        result["profit"] / result["effective_purchase_total"].replace(0, np.nan) * 100
    ).round(2)
    result["take_rate_pct"] = (
        result["market_services"] / result["sell_price"].replace(0, np.nan) * 100
    ).round(2)
    result["is_loss"] = result["profit"] < 0
    return result.reset_index(drop=True)


def _apply_pricing_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Полный план публикации имеет приоритет над повторным расчётом уведомления."""
    snapshots = df.get(
        "pricing_snapshot", pd.Series(None, index=df.index, dtype=object)
    )

    def is_complete(value):
        if (
            not isinstance(value, dict)
            or value.get("calculation_version") != "yandex-v2-full-fees"
            or value.get("snapshot_source") == "order_recalculation"
        ):
            return False
        try:
            for number in (
                value["source"]["purchase_price_rub"],
                value["margin"]["markup_percent"],
                value["prices"]["target_price"],
                value["prices"]["minimum_allowed_price"],
            ):
                if not np.isfinite(float(number)):
                    return False
            return isinstance(value["components"], list) and all(
                isinstance(component, dict)
                and isinstance(component["code"], str)
                and np.isfinite(float(component["amount"]))
                for component in value["components"]
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return False

    complete = snapshots.map(is_complete)
    df["plan_snapshot_complete"] = complete
    df["snapshot_expected_profit_unit"] = np.nan
    df["snapshot_shipping_fixed"] = 0.0
    if complete.any():
        for field in (
            "base_price",
            "margin_percent",
            "min_sell_price",
            "ff_fee",
            "socket_adapter_fee",
            "custom_delivery_fee",
            "calc_category_fee",
            "calc_transfer_fee",
            "calc_accepting_payment_fee",
            "calc_order_processing_fee",
            "planned_boost_amount",
            "calc_delivery_fee",
        ):
            df[field] = pd.to_numeric(
                df.get(field, pd.Series(np.nan, index=df.index)), errors="coerce"
            ).astype(float)
    for index in df.index[complete]:
        snapshot = snapshots.loc[index]
        components = {c["code"]: float(c["amount"]) for c in snapshot["components"]}
        purchase = float(snapshot["source"]["purchase_price_rub"])
        price = float(snapshot["prices"]["target_price"])
        df.loc[index, "base_price"] = purchase
        df.loc[index, "margin_percent"] = float(snapshot["margin"]["markup_percent"])
        df.loc[index, "min_sell_price"] = float(
            snapshot["prices"]["minimum_allowed_price"]
        )
        fields = {
            "ff_fee": "ff",
            "socket_adapter_fee": "socket_adapter",
            "custom_delivery_fee": "custom_delivery",
            "calc_category_fee": "category_commission",
            "calc_transfer_fee": "transfer_commission",
            "calc_accepting_payment_fee": "accepting_payment",
            "calc_order_processing_fee": "order_processing",
            "planned_boost_amount": "boost",
        }
        for field, code in fields.items():
            df.loc[index, field] = components.get(code, 0)
        df.loc[index, "calc_delivery_fee"] = sum(
            components.get(code, 0)
            for code in ("delivery", "middle_mile", "cross_border")
        )
        df.loc[index, "snapshot_expected_profit_unit"] = (
            price
            - purchase
            - sum(amount for code, amount in components.items() if code != "margin")
        )
        df.loc[index, "snapshot_shipping_fixed"] = float(
            snapshot.get("decision", {})
            .get("metadata", {})
            .get("cross_border_fixed_per_order", 0)
        )
    return df


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
        df["returned_sell_price"].fillna(0)
        if "returned_sell_price" in df.columns
        else 0.0
    )
    df["sell_price"] = df["sell_price"] - returned_sell

    # Ожидаемая выплата = цена продажи минус комиссии ЯМ
    df["expected_payout"] = (
        df["sell_price"].fillna(0) - df["market_services"].fillna(0)
    ).clip(lower=0)

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
    df["snapshot_fixed_fee_savings"] = 0.0
    complete = df.get(
        "plan_snapshot_complete", pd.Series(False, index=df.index)
    ).fillna(False)
    if complete.any():
        sku_count = (
            df.groupby(["ya_order_id", "offer_id"])["offer_id"].transform("size")
            if "ya_order_id" in df and "offer_id" in df
            else pd.Series(1, index=df.index)
        )
        accepting = (
            pd.to_numeric(df["calc_accepting_payment_fee"], errors="coerce").fillna(0)
            / sku_count
        )
        accepting_savings = df["calc_accepting_payment_fee_total"] - accepting
        df["calc_accepting_payment_fee_total"] = df[
            "calc_accepting_payment_fee_total"
        ].where(~complete, accepting)
        fixed = df.get("snapshot_shipping_fixed", pd.Series(0, index=df.index))
        shipping_savings = fixed * (
            q - df.get("order_cost_share", pd.Series(1, index=df.index))
        )
        df["calc_delivery_fee_total"] -= shipping_savings.where(complete, 0)
        df["snapshot_fixed_fee_savings"] = (accepting_savings + shipping_savings).where(
            complete, 0
        )
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
    # Отдельный отчёт по баллам надёжнее старых строк платёжного отчёта.
    # Замена, а не сложение, предотвращает двойной учёт уже распознанных списаний.
    wallet_available = (
        df.get("wallet_promo_available", pd.Series(False, index=df.index))
        .fillna(False)
        .astype(bool)
    )
    wallet_promo = pd.to_numeric(
        df.get("wallet_promo_discounts", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    df["promo_discounts"] = df["promo_discounts"].where(~wallet_available, wallet_promo)

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
    report_available = (
        report_details.map(lambda value: isinstance(value, dict)) & report_total.notna()
    )

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
    report_components_total = sum(
        report_components.values(), pd.Series(0.0, index=df.index)
    )
    report_complete = report_available & report_components_total.sub(
        report_total
    ).abs().le(0.011)
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
        "fact_boost_service_fee": report_components["boost"],
        "fact_other_fees": sum(
            (
                report_components[key]
                for key in (
                    "warehouse_processing",
                    "loyalty",
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

    planned_boost_unit = pd.to_numeric(
        df.get("planned_boost_amount", pd.Series(np.nan, index=df.index)),
        errors="coerce",
    )
    # Сохранённая сумма буста — увеличение цены на единицу товара,
    # компенсирующее ставку. Для старой истории без снимка оставляем NaN.
    df["calc_boost_fee_total"] = planned_boost_unit * q
    wallet_spend_signed = pd.to_numeric(
        df.get("boost_wallet_spend", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    # В реестре списание отрицательное. Для таблицы выводим расход плюсом,
    # а исходный знак сохраняем для формулы прибыли.
    df["boost_wallet_spend"] = wallet_spend_signed
    df["fact_boost_wallet_spend"] = -wallet_spend_signed
    df["fact_boost_fee_total"] = (
        pd.to_numeric(
            df.get("fact_boost_service_fee", pd.Series(0.0, index=df.index)),
            errors="coerce",
        ).fillna(0)
        + df["fact_boost_wallet_spend"]
    )

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
    planned_boost = pd.to_numeric(
        df.get("calc_boost_fee_total", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    boost_wallet_spend = pd.to_numeric(
        df.get("boost_wallet_spend", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(
        0
    )  # debit is negative
    # Целевая прибыль задаётся на закупку при публикации цены. Фактические
    # удержания и списания баллов не должны менять исторический план.
    df["expected_profit"] = df["our_margin"]
    snapshot_profit = pd.to_numeric(
        df.get("snapshot_expected_profit_unit", pd.Series(np.nan, index=df.index)),
        errors="coerce",
    )
    df["expected_profit"] = df["expected_profit"].where(
        snapshot_profit.isna(),
        snapshot_profit * df["quantity"].fillna(1)
        + df.get("snapshot_fixed_fee_savings", 0),
    )
    df["legacy_floor_profit"] = (
        df["min_sell_price_total"]
        - df["calc_commissions"]
        - planned_boost
        - df["base_price_total"]
        - df["ff_fee_total"]
        - df["socket_adapter_total"]
        - df["custom_delivery_fee_total"]
    )
    complete = (
        df.get("plan_snapshot_complete", pd.Series(False, index=df.index))
        .fillna(False)
        .astype(bool)
    )
    df["legacy_floor_profit"] = df["legacy_floor_profit"].where(~complete)

    promo = df["promo_discounts"].fillna(0)  # отрицательная сумма
    df["income_after_fees"] = df["expected_payout"]
    df["income_after_fees_promo"] = df["expected_payout"] + promo + boost_wallet_spend

    df["profit"] = df["income_after_fees_promo"] - our_costs
    df["profit_no_promo"] = df["income_after_fees"] + boost_wallet_spend - our_costs
    df["full_market_services"] = (
        df["market_services"].fillna(0) - promo - boost_wallet_spend
    )
    # Денежная выплата и доход с учётом бонусного баланса — разные величины.
    # Это реконструкция из отчёта, а не подтверждённая банковская выписка.
    df["cash_payout"] = (
        df["sell_price"].fillna(0)
        - df["bonus_points"]
        - df["market_services"].fillna(0)
    )
    df["wallet_balance_change"] = df["bonus_points"] + promo + boost_wallet_spend
    df["economics_is_estimated"] = ~df["uses_fact_purchase_price"]

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
    fact_available = (
        df.get("fact_commissions_available", pd.Series(False, index=df.index))
        .fillna(False)
        .astype(bool)
    )
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
    boost_wallet_spend = pd.to_numeric(
        df.get("boost_wallet_spend", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(
        0
    )  # debit is negative
    compensations = pd.to_numeric(
        df.get("compensations", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0)
    actual_full = (
        df["sell_price"].fillna(0)
        - actual_market_services
        + promo
        + boost_wallet_spend
        + compensations
        - our_costs
    )

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
    planned_boost = pd.to_numeric(
        df.get("calc_boost_fee_total", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    planned_margin_net_boost = df["our_margin"]
    df["margin_plan_pct"] = (planned_margin_net_boost / sp * 100).round(2)
    df["margin_fact_pct"] = df["margin_pct"]
    df["margin_fact_rub"] = df["profit"]

    # Маржа относительно закупочной цены (для сравнения с margin_percent из БД).
    # План: наценка за вычетом ожидаемого расхода на буст, относительно закупки.
    # Факт: profit / base_price_total → «сколько реально заработали сверх закупки».
    bp = df["base_price_total"].replace(0, np.nan)
    df["margin_plan_on_cost_pct"] = (planned_margin_net_boost / bp * 100).round(2)
    df["margin_fact_on_cost_pct"] = (
        df["profit"] / df["effective_purchase_total"].replace(0, np.nan) * 100
    ).round(2)

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
    df = _allocate_order_amounts(df)
    df = _apply_pricing_snapshot(df)
    q = df["quantity"].fillna(1)
    df = _apply_payment_refund_fallback(df, q)

    # При частичном возврате затраты считаем только на доставленные единицы:
    # покупная цена возвращённых штук не потеряна — товар вернулся на склад.
    # Если транзакций нет (tr_delivered_quantity IS NULL) — fallback на полный quantity.
    if "tr_delivered_quantity" in df.columns:
        delivered_q = pd.to_numeric(
            df["tr_delivered_quantity"], errors="coerce"
        ).fillna(q)
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
    df["base_purchase_expensed"] = effective_purchase_delivered
    df["our_costs"] = our_costs

    df = _compute_profits(df, our_costs)
    df = _compute_actual_profit(df, our_costs)
    df = _compute_flags_and_lags(df)

    return df


def apply_refund_cases(frame, items, operations, matches):
    """Послеобслуживание: деньги и восстановление закупки, без изменения плана продажи."""
    from decimal import Decimal, ROUND_DOWN

    out = frame.copy()
    if out.empty:
        return out

    def dec(value):
        if value is None or pd.isna(value):
            return None
        return Decimal(str(value))

    def split_amount(total, allocation_rows):
        weights = {
            str(x["split_order_id"]): Decimal(str(x["allocated_amount"]))
            for x in allocation_rows
        }
        weight = sum(weights.values())
        if weight <= 0:
            return {k: Decimal(0) for k in weights}
        result = {
            k: (total * v / weight).quantize(Decimal(".01"), rounding=ROUND_DOWN)
            for k, v in weights.items()
        }
        for k in sorted(weights, key=int)[: int((total - sum(result.values())) * 100)]:
            result[k] += Decimal(".01")
        return result

    by_operation = {}
    for op in operations:
        by_operation.setdefault(str(op["id"]), []).append(op)
    expenses = {}
    reimbursements = {}
    planned_reimbursements = {}
    plans = {}
    unknown = set()
    case_ids = {}
    for op_id, allocations in by_operation.items():
        op = allocations[0]
        key = lambda x: (
            int(x["seller_id"]),
            str(x["order_number"]),
            str(x["offer_id"]),
        )
        if op["payer"] != "company":
            continue
        if op["currency"] != "RUB" and op.get("rub_amount") is None:
            unknown.update(key(a) for a in allocations)
            continue
        incoming = op.get("kind") in (
            "supplier_reimbursement",
            "carrier_reimbursement",
            "commission_refund",
        )
        sign = Decimal(-1) if incoming else Decimal(1)
        total = Decimal(str(op["rub_amount"] or op["amount"]))
        if op["state"] == "planned":
            for a in allocations:
                if incoming:
                    planned_reimbursements[key(a)] = planned_reimbursements.get(
                        key(a), Decimal(0)
                    ) + Decimal(str(a["allocated_amount"]))
                plans[key(a)] = plans.get(key(a), Decimal(0)) + sign * Decimal(
                    str(a["allocated_amount"])
                )
            continue
        covered = Decimal(0)
        valid_matched = Decimal(0)
        uncertain = False
        for match in matches:
            if str(match["operation_id"]) != op_id:
                continue
            snapshot = match["source_snapshot"]
            if (
                match.get("current_fingerprint") != snapshot.get("fingerprint")
                or match.get("current_amount") is None
                or Decimal(str(match["current_amount"])) < Decimal(str(match["amount"]))
            ):
                uncertain = True
                continue
            coverage = match.get("current_coverage")
            # A report link is evidence only when the native calculator actually consumes it.
            if coverage == "included":
                covered += Decimal(str(match["amount"]))
                valid_matched += Decimal(str(match["amount"]))
            elif coverage == "not_included":
                valid_matched += Decimal(str(match["amount"]))
            elif coverage == "returned":
                # Evaluated against the exact native row below.
                valid_matched += Decimal(str(match["amount"]))
            else:
                uncertain = True
        if (
            op["method"] == "marketplace"
            or op.get("kind") in ("carrier_reimbursement", "commission_refund")
        ) and valid_matched < total:
            uncertain = True
        if uncertain:
            unknown.update(key(a) for a in allocations)
        allocated = split_amount(max(total - covered, Decimal(0)), allocations)
        for a in allocations:
            k = key(a)
            expenses[k] = (
                expenses.get(k, Decimal(0)) + sign * allocated[str(a["split_order_id"])]
            )
            if incoming:
                reimbursements[k] = (
                    reimbursements.get(k, Decimal(0))
                    + allocated[str(a["split_order_id"])]
                )
            case_ids.setdefault(k, set()).add(str(a["case_id"]))

    for index, row in out.iterrows():
        if pd.isna(row.get("seller_id")):
            continue
        key = (
            int(row["seller_id"]),
            str(row.get("order_id_str", row.get("order_id"))),
            str(row.get("offer_id")),
        )
        relevant = [
            i
            for i in items
            if (int(i["seller_id"]), str(i["order_number"]), str(i["offer_id"])) == key
        ]
        if (
            not relevant
            and key not in expenses
            and key not in plans
            and key not in unknown
        ):
            continue
        monetary = expenses.get(key, Decimal(0))
        planned = plans.get(key, Decimal(0))
        correction = Decimal(0)
        incomplete = key in unknown or any(
            i.get("replacement_cost_unknown", False) for i in relevant
        )
        pending = False
        recovered = Decimal(0)
        loss = Decimal(0)
        # Many compensation cases may concern the same unit. Inventory is adjusted once;
        # a physical return result takes precedence over compensation-only observations.
        unit_costs = {}
        managed_units = {}
        for position, item in enumerate(relevant):
            if item["stage"] == "cancelled":
                continue
            unit_id = item.get("split_order_id", f"fixture:{position}")
            snapshot = dec(item.get("purchase_cost"))
            if snapshot is not None:
                unit_costs.setdefault(unit_id, set()).add(snapshot)
            if len(unit_costs.get(unit_id, ())) > 1:
                incomplete = True

            if unit_id not in managed_units or item["requires_return"]:
                managed_units[unit_id] = item
        q = dec(row.get("quantity"))
        basis = dec(row.get("effective_purchase_total"))
        recognized = dec(row.get("base_purchase_expensed"))
        estimated_cost = False
        if not relevant and (key in expenses or key in plans):
            if basis is None or basis <= 0:
                incomplete = True

        for item in managed_units.values():
            cost = dec(item.get("purchase_cost"))
            if cost is None:
                cost = dec(item.get("procurement_cost"))
            if cost is None and basis is not None and basis > 0 and q and q > 0:
                cost = basis / q
                estimated_cost = True
            if cost is None or recognized is None or not q or q <= 0:
                incomplete = True
                continue
            target = Decimal(0) if item["stage"] == "stocked" else cost
            if recognized == 0:
                unit_recognized = Decimal(0)
            elif basis is not None and abs(recognized - basis) < Decimal(".01"):
                unit_recognized = recognized / q
                if q > 1 and abs(unit_recognized - cost) >= Decimal(".01"):
                    incomplete = True
                    continue
            elif item.get("native_refund"):
                unit_recognized = Decimal(0)
            else:
                incomplete = True
                continue
            correction += unit_recognized - target
            if item["requires_return"]:
                if item["stage"] == "stocked":
                    recovered += cost
                elif item["stage"] in ("defective", "lost"):
                    loss += cost
                elif item["stage"] != "external_received":
                    pending = True
        # Logistics already recognized by the native returned-order formula are covered once.
        for op_id, allocs in by_operation.items():
            matching_allocs = [
                a
                for a in allocs
                if (int(a["seller_id"]), str(a["order_number"]), str(a["offer_id"]))
                == key
            ]
            if (
                not matching_allocs
                or allocs[0]["state"] != "posted"
                or allocs[0]["payer"] != "company"
            ):
                continue
            returned_coverage = sum(
                (
                    Decimal(str(m["amount"]))
                    for m in matches
                    if str(m["operation_id"]) == op_id
                    and m.get("current_coverage") == "returned"
                    and m.get("current_fingerprint")
                    == m["source_snapshot"].get("fingerprint")
                ),
                Decimal(0),
            )
            if returned_coverage and bool(row.get("is_returned", False)):
                share = split_amount(returned_coverage, allocs)
                monetary -= (
                    Decimal(-1)
                    if allocs[0].get("kind")
                    in (
                        "supplier_reimbursement",
                        "carrier_reimbursement",
                        "commission_refund",
                    )
                    else Decimal(1)
                ) * sum(
                    (share[str(a["split_order_id"])] for a in matching_allocs),
                    Decimal(0),
                )
        original = dec(row.get("profit"))
        original_actual = dec(row.get("actual_profit"))
        out.at[index, "profit_before_after_sales"] = (
            float(original) if original is not None else np.nan
        )
        out.at[index, "after_sales_cost_estimated"] = estimated_cost
        out.at[index, "after_sales_expense"] = float(monetary)
        out.at[index, "after_sales_gross_expense"] = float(
            monetary + reimbursements.get(key, Decimal(0))
        )
        out.at[index, "after_sales_reimbursement"] = float(
            reimbursements.get(key, Decimal(0))
        )
        out.at[index, "after_sales_planned_gross_expense"] = float(
            planned + planned_reimbursements.get(key, Decimal(0))
        )
        out.at[index, "after_sales_planned_reimbursement"] = float(
            planned_reimbursements.get(key, Decimal(0))
        )
        out.at[index, "after_sales_planned"] = float(planned)
        out.at[index, "inventory_recovery_amount"] = float(recovered)
        out.at[index, "inventory_loss_amount"] = float(loss)
        out.at[index, "inventory_profit_adjustment"] = float(correction)
        out.at[index, "after_sales_state"] = (
            "needs_reconciliation"
            if incomplete
            else ("provisional" if pending else "complete")
        )
        final = (
            original - monetary + correction
            if original is not None and not incomplete
            else None
        )
        out.at[index, "profit"] = float(final) if final is not None else np.nan
        native_cost = dec(row.get("our_costs"))
        if native_cost is not None:
            out.at[index, "our_costs"] = (
                float(native_cost + monetary - correction) if not incomplete else np.nan
            )
        sale = dec(row.get("sell_price"))
        for name, denominator in [
            ("margin_pct", sale),
            ("margin_fact_pct", sale),
            ("margin_fact_on_cost_pct", basis),
        ]:
            out.at[index, name] = (
                float(final / denominator * 100)
                if final is not None and denominator
                else np.nan
            )
        out.at[index, "projected_profit"] = (
            float(final - planned) if final is not None else np.nan
        )
        out.at[index, "actual_profit"] = (
            float(original_actual - monetary + correction)
            if original_actual is not None and not incomplete
            else np.nan
        )
        out.at[index, "profit_no_promo"] = (
            float(dec(row["profit_no_promo"]) - monetary + correction)
            if dec(row.get("profit_no_promo")) is not None and not incomplete
            else np.nan
        )
        out.at[index, "margin_fact_rub"] = float(final) if final is not None else np.nan
        out.at[index, "is_loss"] = final < 0 if final is not None else False
    return out
