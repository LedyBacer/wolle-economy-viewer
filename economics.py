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
- our_costs           = base_price + ff_fee + socket_adapter (за весь заказ)
- expected_profit     = expected_payout - our_costs (без учёта промо)
- profit              = expected_payout + promo_discounts - our_costs (с учётом промо)
- fact_commissions    = реальные удержания ЯМ из платёжного отчёта ≈ market_services
"""
import pandas as pd
import numpy as np

# Статусы, означающие отмену до несения расходов (товар не отгружен)
CANCELLED_BEFORE_SHIP = frozenset({
    "Заказ отменен до обработки",
    "Отменен при обработке",
    "Отменён",
})

# Статусы возврата/невыкупа — расходы понесены, товар вернулся
RETURNED_STATUSES = frozenset({
    "Невыкуп принят на складе",
    "Полный возврат принят на складе",
    "Частичный невыкуп принят на складе",
    "Отменен при доставке",
})

# Все статусы, при которых заказ не приносит дохода от продажи
CANCELLED_STATUSES = CANCELLED_BEFORE_SHIP | RETURNED_STATUSES

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
    "bonus_points":             "Субсидия ЯМ (справочно, в sell_price)",
    "promo_discounts":          "Промо-расходы (наши баллы)",
    "diff_from_min_price":      "Разница от мин. цены",
    "calc_commissions":         "Расчётные комиссии",
    "market_services":          "Комиссии (margin_report)",
    "fact_commissions":         "Факт. комиссии (ЛК)",
    "income_after_fees":        "Доход за вычетом комиссий",
    "profit":                   "Прибыль",
    "profit_vs_expected":       "Разница Прибыли Факт/Ожид",
    "income_after_fees_promo":  "Доход за вычетом комиссий и промо",
    "profit_no_promo":          "Прибыль без учёта промо-расходов",
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
    "fact_commissions",
    "income_after_fees",
    "profit",
    "profit_vs_expected",
    "income_after_fees_promo",
    "profit_no_promo",
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
    df["sell_price"] = df["sell_price"].where(
        df["sell_price"].notna(),
        (df["buyer_price"] + df["subsidy"]) * q,
    )

    # Ожидаемая выплата = цена продажи минус комиссии ЯМ
    df["expected_payout"] = (
        df["sell_price"].fillna(0) - df["market_services"].fillna(0)
    ).clip(lower=0)

    # --- Ожидаемая прибыль: НЕ зависит от статуса заказа ---
    # (иначе при изменении статуса задним числом цифра "скачет")
    df["expected_profit"] = df["expected_payout"] - our_costs

    # --- Расчётные комиссии: только commission_* поля (markup_* — наша наценка) ---
    df["calc_commissions"] = (
        df["calc_category_fee"]
        + df["calc_transfer_fee"]
        + df["calc_delivery_fee"]
    )

    # --- Баллы берём из ya_order_transactions_report.bonuses (надёжнее payments_reports) ---
    df["bonus_points"] = df["tr_bonuses"].fillna(0)

    # Сохраняем совместимость: промо-скидки могут отсутствовать
    if "promo_discounts" not in df.columns:
        df["promo_discounts"] = 0.0
    df["promo_discounts"] = df["promo_discounts"].fillna(0)

    if "fact_commissions" not in df.columns:
        df["fact_commissions"] = 0.0
    df["fact_commissions"] = df["fact_commissions"].fillna(0)

    # --- Доход за вычетом комиссий ---
    # bonus_points (tr.bonuses) = субсидия ЯМ, уже включена в sell_price → НЕ прибавлять!
    # promo_discounts — наши расходы на промо (отрицательная сумма), вычитаем.
    pd_ = df["promo_discounts"].fillna(0)  # отрицательная сумма промо-списаний

    df["income_after_fees"]      = df["expected_payout"]
    df["income_after_fees_promo"] = df["expected_payout"] + pd_  # промо-расходы вычитаются (pd_ < 0)

    # --- Прибыль ---
    df["profit"]          = df["income_after_fees_promo"] - our_costs
    df["profit_no_promo"] = df["income_after_fees"] - our_costs

    # --- Разница от минимальной цены ---
    df["diff_from_min_price"] = df["sell_price"].fillna(0) - df["min_sell_price_total"]

    # --- Нам перевели за заказ: сумма выплаты только для переведённых заказов ---
    is_transferred = df["payment_status"].isin({"Переведён", "Удержан из платежей покупателей"})
    df["payout_if_paid"] = np.where(is_transferred, df["expected_payout"], 0.0)

    # --- Дата выплаты: сначала из транзакционного отчёта (надёжнее),
    # потом — MAX из платёжного отчёта ---
    tr_date = pd.to_datetime(df.get("tr_customer_payment_date"), errors="coerce", utc=True)
    pay_date = pd.to_datetime(df.get("last_payment_date"), errors="coerce", utc=True)
    df["last_payment_date"] = tr_date.fillna(pay_date)

    # --- Фактическая прибыль ---
    has_payment = (
        df["last_payment_date"].notna()
        | is_transferred  # margin_report говорит "Переведён" — деньги у нас
    )
    is_cancelled_before = df["fulfillment_status"].isin(CANCELLED_BEFORE_SHIP)
    is_returned = df["fulfillment_status"].isin(RETURNED_STATUSES)

    # Базовая формула: выплата минус наши расходы
    actual_full = df["expected_payout"] - our_costs

    df["actual_profit"] = np.where(
        ~has_payment,
        0.0,
        np.where(
            is_cancelled_before,
            # Отменён до отгрузки: расходы не понесены, остаются только штрафы/компенсации
            df["expected_payout"] - df.get("seller_cancel_penalty", 0).fillna(0)
              - df.get("late_ship_penalty", 0).fillna(0),
            np.where(
                is_returned,
                # Возврат: расходы понесены, товар вернулся — результат, как правило, в минус
                actual_full,
                actual_full,  # доставлен
            ),
        ),
    )

    # --- Разница: фактическая vs ожидаемая прибыль ---
    df["profit_vs_expected"] = df["actual_profit"] - df["expected_profit"]

    # --- Строковый номер заказа ---
    df["order_id_str"] = df["order_id"].astype(str)

    # ----------------------------------------------------------------------
    # Дополнительные производные поля для расширенной аналитики
    # ----------------------------------------------------------------------
    # Наши затраты (на позицию) — отдельной колонкой для агрегаций
    df["our_costs"] = our_costs

    # Take rate ЯМ = доля комиссий в цене продажи (на уровне заказа,
    # дублируется в позициях — корректно после dedup по ya_order_id)
    sp = df["sell_price"].replace(0, np.nan)
    df["take_rate_pct"] = (df["market_services"] / sp * 100).round(2)

    # Маржа по позиции (после комиссий и промо)
    df["margin_pct"] = (df["profit"] / sp * 100).round(2)

    # Флаги статусов на уровне позиции
    df["is_cancelled_before"] = df["fulfillment_status"].isin(CANCELLED_BEFORE_SHIP)
    df["is_returned"]         = df["fulfillment_status"].isin(RETURNED_STATUSES)
    df["is_cancelled_any"]    = df["fulfillment_status"].isin(CANCELLED_STATUSES)
    df["is_delivered"]        = ~df["is_cancelled_any"]
    df["is_loss"]             = df["profit"] < 0

    # Лаги (в днях)
    created = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    shipped = pd.to_datetime(df["shipment_date"], errors="coerce", utc=True)
    paid    = pd.to_datetime(df["last_payment_date"], errors="coerce", utc=True)
    df["ship_lag_days"] = (shipped - created).dt.total_seconds() / 86400
    df["pay_lag_days"]  = (paid - created).dt.total_seconds() / 86400

    return df
