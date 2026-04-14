"""
Расчёт показателей юнит-экономики МегаМаркет.
Чистые функции без side-эффектов.

Логика расчётов:
- sell_price        = из mm_payment_reports (положительные компоненты)
- market_services   = из mm_payment_reports (|отрицательные компоненты|)
- expected_payout   = sell_price − market_services − vat_on_incentive
- incentive_amount  = price − final_price (часть, оплаченная бонусами покупателя)
- vat_on_incentive  = incentive_amount × ставка НДС (по дате выплаты отчёта)
                      до 01.01.2026 → 20%, 01.01.2026–01.04.2026 → 22%, после → 0%
- our_costs         = effective_purchase_total + cdek_delivery_cost (для доставленных)
                      или return_delivery_cost (для возвратов)
- profit            = expected_payout + promo_discounts − our_costs
- profit_no_promo   = expected_payout − our_costs

Финансовые поля из mm_payment_reports — ORDER-LEVEL, повторяются на каждой позиции.
При агрегации по заказу суммировать sell_price/market_services НЕЛЬЗЯ.
"""

import numpy as np
import pandas as pd

from wolle_economy.enums import (
    MM_FULFILLMENT_STATUS_CANCELLED,
    MM_FULFILLMENT_STATUS_DELIVERED,
    MM_FULFILLMENT_STATUS_NOT_DELIVERED,
    MM_FULFILLMENT_STATUS_RETURNED,
)

# Русские строки fulfillment_status для группировки
_DELIVERED_LABELS = frozenset({MM_FULFILLMENT_STATUS_DELIVERED})
_CANCELLED_LABELS = frozenset({MM_FULFILLMENT_STATUS_CANCELLED})
_RETURNED_LABELS = frozenset({MM_FULFILLMENT_STATUS_NOT_DELIVERED, MM_FULFILLMENT_STATUS_RETURNED})


# ── НДС на incentive (бонусы → рубли) ────────────────────────────────────────
# Ставка определяется по дате создания заказа (created_at).
# до 01.01.2026 → 20%, 01.01.2026–31.03.2026 → 22%, с 01.04.2026 → 0%

_VAT_BOUNDARY_2026_01 = pd.Timestamp("2026-01-01", tz="UTC")
_VAT_BOUNDARY_2026_04 = pd.Timestamp("2026-04-01", tz="UTC")


def _compute_vat_rate(created_at: pd.Series) -> pd.Series:
    """Возвращает ставку НДС (0.20 / 0.22 / 0.0) по дате создания заказа."""
    dt = pd.to_datetime(created_at, errors="coerce", utc=True)
    rate = pd.Series(0.0, index=created_at.index)
    rate = rate.where(dt >= _VAT_BOUNDARY_2026_04, 0.22)  # до 01.04.2026 → 22%
    rate = rate.where(dt >= _VAT_BOUNDARY_2026_01, 0.20)   # до 01.01.2026 → 20%
    return rate


def calc_mm_economics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Добавляет все производные финансовые колонки для заказов МегаМаркет.
    Входной df — результат pd.concat DBS + Poizon из loader.
    """
    if df.empty:
        return df

    df = df.copy()
    q = df["quantity"].fillna(1)

    # ── Базовые итоги ──────────────────────────────────────────────────────
    df["base_price_total"] = df["base_price"] * q
    df["min_sell_price_total"] = df["min_sell_price"].fillna(0) * q

    # Фактическая закупочная цена: supplier_price_fact > 0 → используем,
    # иначе fallback на base_price (аналогично ЯМ).
    spf = pd.to_numeric(df["supplier_price_fact"], errors="coerce").fillna(0)
    df["supplier_price_fact"] = spf
    df["effective_purchase_total"] = np.where(spf > 0, spf * q, df["base_price_total"])
    df["uses_fact_purchase_price"] = spf > 0

    # margin_pct_raw — плановый % наценки Wolle (из min_allowed_price в БД).
    # price_with_margin = закупка + наценка Wolle (без комиссий ММ и доставки).
    # our_margin = плановая прибыль Wolle = base_price × margin_pct_raw / 100.
    # modifier_price хранится для справки, но включает комиссии ММ — не подходит
    # для расчёта плановой маржи.
    margin_pct = pd.to_numeric(df["margin_pct_raw"], errors="coerce").fillna(0)
    df["price_with_margin"] = (df["base_price_total"] * (1 + margin_pct / 100)).round(2)
    df["our_margin"] = (df["base_price_total"] * margin_pct / 100).round(2)

    # ── Флаги статусов (по русским строкам fulfillment_status из SQL) ─────
    df["is_delivered"] = df["fulfillment_status"].isin(_DELIVERED_LABELS)
    df["is_cancelled_before"] = df["fulfillment_status"].isin(_CANCELLED_LABELS)
    df["is_returned"] = df["fulfillment_status"].isin(_RETURNED_LABELS)
    df["is_cancelled_any"] = ~df["is_delivered"]

    # ── НДС на incentive ──────────────────────────────────────────────────
    incentive = pd.to_numeric(df["incentive_amount"], errors="coerce").fillna(0)
    df["incentive_amount"] = incentive
    vat_rate = _compute_vat_rate(df["created_at"])
    df["vat_on_incentive"] = (incentive * vat_rate).round(2)

    # ── Финансы ────────────────────────────────────────────────────────────
    # sell_price вычисляется из данных заказа (price × qty + delivery_cost),
    # а не из mm_payment_reports — маппинг положительных полей в отчётах
    # нестабилен между версиями (итоговые суммы попадают в компонентные поля).
    # market_services (отрицательные компоненты) надёжны и берутся из SQL.
    delivery = pd.to_numeric(
        df.get("delivery_cost", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    df["sell_price"] = np.where(
        df["is_delivered"],
        pd.to_numeric(df["price"], errors="coerce").fillna(0) * q + delivery,
        0.0,
    )
    df["market_services"] = np.where(df["is_delivered"], df["market_services"], 0.0)

    # expected_payout = sell_price − комиссии − НДС на incentive
    df["expected_payout"] = np.where(
        df["is_delivered"],
        df["sell_price"] - df["market_services"] - df["vat_on_incentive"],
        0.0,
    )

    if "promo_discounts" not in df.columns:
        df["promo_discounts"] = 0.0
    df["promo_discounts"] = df["promo_discounts"].fillna(0)

    if "bonus_from_mm" not in df.columns:
        df["bonus_from_mm"] = 0.0
    df["bonus_from_mm"] = df["bonus_from_mm"].fillna(0)

    # ── Наши затраты ───────────────────────────────────────────────────────
    return_cost = pd.to_numeric(
        df.get("return_delivery_cost", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)

    cdek_cost = pd.to_numeric(
        df.get("cdek_delivery_cost", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)

    # Доставленные: закупка + фактическая доставка СДЭК.
    # Возвраты/невыкупы: товар вернулся → закупка не потеряна, но есть расходы на возврат.
    # Отменённые до отгрузки: затрат нет.
    df["our_costs"] = np.where(
        df["is_cancelled_before"],
        0.0,
        np.where(
            df["is_returned"],
            return_cost,
            df["effective_purchase_total"] + cdek_cost,
        ),
    )

    # ── Прибыль ────────────────────────────────────────────────────────────
    promo = df["promo_discounts"].fillna(0)  # отрицательная сумма
    df["expected_profit"] = df["expected_payout"] - df["our_costs"]
    df["income_after_fees"] = df["expected_payout"]
    df["income_after_fees_promo"] = df["expected_payout"] + promo
    df["profit_no_promo"] = df["expected_payout"] - df["our_costs"]
    df["profit"] = df["expected_payout"] + promo - df["our_costs"]
    # diff_from_min_price: сравниваем цену товара (без доставки) с минимальной.
    # sell_price включает доставку → берём price × qty для корректного сравнения.
    price_total = pd.to_numeric(df["price"], errors="coerce").fillna(0) * q
    df["diff_from_min_price"] = np.where(
        df["is_delivered"],
        price_total - df["min_sell_price_total"],
        0.0,
    )

    # ── Фактическая прибыль (с учётом статуса оплаты) ──────────────────────
    is_paid = df["payment_status"] == "Переведён"
    is_deducted = df["payment_status"] == "Списание"

    # payout_if_paid: фактически перечисленная сумма из финансовых отчётов ММ.
    # fr_net_payout = company_debt − seller_debt из mm_financial_report.
    # Если фин. отчёт есть → показываем реальную выплату; иначе 0.
    fr_payout = pd.to_numeric(
        df.get("fr_net_payout", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0)
    df["payout_if_paid"] = fr_payout

    delivered_at = pd.to_datetime(df.get("delivered_at"), errors="coerce", utc=True)
    # Дата выплаты — только для полностью оплаченных заказов
    df["last_payment_date"] = np.where(is_paid, delivered_at, pd.NaT)
    # Дата списания — для заказов с только списаниями (без основной выплаты)
    df["deduction_date"] = np.where(is_deducted & ~is_paid, delivered_at, pd.NaT)

    has_payment = is_paid
    df["actual_profit"] = np.where(
        ~has_payment,
        # Для «Списание» учитываем фактические списания (отрицательные)
        np.where(is_deducted, df["expected_payout"], 0.0),
        np.where(df["is_cancelled_before"], 0.0, df["profit"]),
    )
    df["profit_vs_expected"] = df["actual_profit"] - df["expected_profit"]

    # ── Метрики и аналитические поля ───────────────────────────────────────
    # Poizon: supplier_name не в all_split_orders → подставляем "Poizon"
    if "supplier_name" not in df.columns:
        df["supplier_name"] = None
    df["supplier_name"] = df["supplier_name"].where(
        df["supplier_name"].notna(),
        other=df["channel"].map(lambda c: "Poizon" if c == "poizon" else None),
    )

    # Алиас для совместимости с аналитическими табами (kpi, abc, trends и др.),
    # которые ожидают колонку ya_order_id.
    df["ya_order_id"] = df["mm_order_id"]
    df["order_id_str"] = df["order_id"].astype(str)

    sp = df["sell_price"].replace(0, np.nan)
    df["take_rate_pct"] = (df["market_services"] / sp * 100).round(2)
    df["margin_pct"] = (df["profit"] / sp * 100).round(2)
    df["margin_plan_pct"] = (df["our_margin"] / sp * 100).round(2)
    df["margin_fact_pct"] = df["margin_pct"]
    df["margin_fact_rub"] = df["profit"]

    bp = df["base_price_total"].replace(0, np.nan)
    df["margin_plan_on_cost_pct"] = (df["our_margin"] / bp * 100).round(2)
    df["margin_fact_on_cost_pct"] = (df["profit"] / bp * 100).round(2)

    df["is_loss"] = df["profit"] < 0

    # Временны́е лаги
    created = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    paid = pd.to_datetime(df["last_payment_date"], errors="coerce", utc=True)
    df["ship_lag_days"] = np.nan  # ММ DBS не имеет отдельной даты отгрузки
    df["pay_lag_days"] = (paid - created).dt.total_seconds() / 86400

    return df
