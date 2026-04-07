"""
Расчёт показателей юнит-экономики.
Чистые функции без side-эффектов.

Логика расчётов:
- sell_price          = (buyer_price + subsidy) * quantity  — фактическая цена продажи по отчёту ЯМ
- market_services     = все комиссии и сборы ЯМ (упаковка, доставка, за категорию и т.д.)
- expected_payout     = sell_price - market_services        — сколько ЯМ должен/уже перевёл нам
- our_costs           = base_price + ff_fee + socket_adapter (за весь заказ)
- expected_profit     = expected_payout - our_costs
- actual_profit       = считается только если есть дата выплаты, иначе 0
"""
import pandas as pd
import numpy as np

# Статусы, означающие отмену/возврат заказа
CANCELLED_STATUSES = frozenset({
    "Заказ отменен до обработки",
    "Отменен при обработке",
    "Невыкуп принят на складе",
    "Полный возврат принят на складе",
    "Отменен при доставке",
})

# Подписи колонок для отображения в UI
COLUMN_LABELS: dict[str, str] = {
    "created_at":               "Заказ создан",
    "shipment_date":            "Дата отгрузки",
    "seller_name":              "Магазин",
    "order_id_str":             "Номер заказа",
    "offer_id":                 "Offer ID",
    "product_name":             "Наименование",
    "order_status":             "Статус заказа",
    "fulfillment_status":       "Статус заказа 2",
    "payment_status":           "Статус платежа",
    "quantity":                 "Количество",
    "supplier_name":            "Отправлено от/из",
    "base_price_total":         "Цена закупки",
    "ff_fee_total":             "Цена упаковки",
    "socket_adapter_total":     "Цена переходника",
    "price_with_margin":        "Цена + маржа",
    "our_margin":               "Наша маржа на заказ",
    "min_sell_price_total":     "Минимальная цена",
    "expected_profit":          "Ожидаемая прибыль",
    "sell_price":               "Цена продажи",
    "bonus_points":             "Начислено баллов",
    "promo_discounts":          "Списано баллов",
    "diff_from_min_price":      "Разница от мин. цены",
    "calc_commissions":         "Расчётные комиссии",
    "market_services":          "Комиссии",
    "income_after_fees":        "Доход за вычетом комиссий",
    "profit":                   "Прибыль",
    "profit_vs_expected":       "Разница Прибыли Факт/Ожид",
    "income_after_fees_bonus":  "Доход за вычетом комиссий (с баллами)",
    "profit_no_bonus":          "Прибыль без учёта баллов",
    "seller_cancel_penalty":    "Штраф за отмену заказа",
    "late_ship_penalty":        "Штраф за позднюю отгрузку",
    "payout_if_paid":           "Нам перевели за заказ",
    "expected_payout":          "Сумма выплаты (если нет даты, то ожидаемая)",
    "last_payment_date":        "Дата выплаты",
    "actual_profit":            "Фактическая прибыль",
}

# Порядок колонок в таблице
DISPLAY_COLUMNS: list[str] = [
    "created_at",
    "shipment_date",
    "seller_name",
    "order_id_str",
    "offer_id",
    "product_name",
    "order_status",
    "fulfillment_status",
    "payment_status",
    "quantity",
    "supplier_name",
    "base_price_total",
    "ff_fee_total",
    "socket_adapter_total",
    "price_with_margin",
    "our_margin",
    "min_sell_price_total",
    "expected_profit",
    "sell_price",
    "bonus_points",
    "promo_discounts",
    "diff_from_min_price",
    "calc_commissions",
    "market_services",
    "income_after_fees",
    "profit",
    "profit_vs_expected",
    "income_after_fees_bonus",
    "profit_no_bonus",
    "seller_cancel_penalty",
    "late_ship_penalty",
    "payout_if_paid",
    "expected_payout",
    "last_payment_date",
    "actual_profit",
]


def merge_with_payments(orders_df: pd.DataFrame, payments_df: pd.DataFrame) -> pd.DataFrame:
    """Объединяет данные о заказах с агрегированными данными о платежах."""
    return orders_df.merge(
        payments_df.rename(columns={"ya_orders_id": "ya_order_id"}),
        on="ya_order_id",
        how="left",
    )


def calc_economics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Добавляет все производные финансовые колонки.
    Входной df должен содержать колонки из ORDER_ITEMS_SQL + PAYMENT_AGGREGATES_SQL.
    """
    df = df.copy()

    q = df["quantity"].fillna(1)

    # --- Базовые итого (цены × количество) ---
    df["base_price_total"]      = df["base_price"] * q
    df["ff_fee_total"]          = df["ff_fee"] * q
    df["socket_adapter_total"]  = df["socket_adapter_fee"] * q
    df["min_sell_price_total"]  = df["min_sell_price"] * q

    # Наша наценка в деньгах и цена с наценкой
    margin = df["margin_percent"].fillna(0).astype(float)
    df["our_margin"]       = df["base_price_total"] * margin / 100
    df["price_with_margin"] = df["base_price_total"] * (1 + margin / 100)

    # Наши затраты = закупка + упаковка + переходник
    our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]

    # --- Sell_price: используем данные из margin_report, иначе считаем сами ---
    # (buyer_price + subsidy) * quantity = то же самое, что sell_price в 99% случаев
    df["sell_price"] = df["sell_price"].where(
        df["sell_price"].notna(),
        (df["buyer_price"] + df["subsidy"]) * q,
    )

    # Ожидаемая выплата = цена продажи минус комиссии ЯМ
    # Для отменённых заказов без sell_price = 0
    df["expected_payout"] = (
        df["sell_price"].fillna(0) - df["market_services"].fillna(0)
    ).clip(lower=0)

    # --- Ожидаемая прибыль ---
    is_cancelled = df["fulfillment_status"].isin(CANCELLED_STATUSES)
    df["expected_profit"] = np.where(
        is_cancelled, 0.0, df["expected_payout"] - our_costs
    )

    # --- Расчётные комиссии из нашей системы ---
    df["calc_commissions"] = (
        df["calc_accepting_fee"]
        + df["calc_processing_fee"]
        + df["calc_transfer_fee"]
        + df["calc_category_fee"]
        + df["calc_delivery_fee"]
        + df["calc_custom_delivery_fee"]
    )

    # --- Доход за вычетом комиссий ---
    bp = df["bonus_points"].fillna(0)
    pd_ = df["promo_discounts"].fillna(0)

    df["income_after_fees"]       = df["expected_payout"]
    df["income_after_fees_bonus"] = df["expected_payout"] + bp + pd_

    # --- Прибыль ---
    df["profit"]         = df["income_after_fees_bonus"] - our_costs
    df["profit_no_bonus"] = df["income_after_fees"] - our_costs

    # --- Разница от минимальной цены ---
    df["diff_from_min_price"] = df["sell_price"].fillna(0) - df["min_sell_price_total"]

    # --- Нам перевели за заказ: сумма выплаты только для переведённых заказов ---
    is_transferred = df["payment_status"].isin({"Переведён", "Удержан из платежей покупателей"})
    df["payout_if_paid"] = np.where(is_transferred, df["expected_payout"], 0.0)

    # --- Фактическая прибыль ---
    # Считается только если есть дата выплаты (деньги реально получены или списаны)
    has_payment = df["last_payment_date"].notna()
    not_cancelled = ~is_cancelled
    will_be_transferred = df["payment_status"] == "Будет переведён"

    df["actual_profit"] = np.where(
        ~has_payment, 0.0,
        np.where(
            is_cancelled | (df["payment_status"] == "Не будет переведён из-за отмены заказа"),
            df["expected_payout"],                  # только штрафы/доп.начисления
            np.where(
                will_be_transferred,
                df["expected_payout"],              # ожидаемая сумма
                df["expected_payout"] - our_costs,  # фактическая прибыль
            )
        )
    )

    # --- Разница: фактическая vs ожидаемая прибыль ---
    df["profit_vs_expected"] = df["actual_profit"] - df["expected_profit"]

    # --- Строковый номер заказа ---
    df["order_id_str"] = df["order_id"].astype(str)

    return df
