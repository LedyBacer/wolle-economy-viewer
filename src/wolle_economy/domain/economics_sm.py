"""Расчёт и нормализация юнит-экономики Sportmaster."""

from __future__ import annotations

import numpy as np
import pandas as pd

_SM_CANCELLED_BEFORE = frozenset({"Отменен", "REJECTED"})
_SM_RETURNED = frozenset({"Отказ при получении"})


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def calc_sm_economics(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит сырые данные Sportmaster к каноническому контракту приложения."""
    if df.empty:
        return df

    out = df.copy()
    q = _num(out.get("quantity", pd.Series(1.0, index=out.index)), default=1.0)

    out["ya_order_id"] = out["sm_order_id"]
    out["channel"] = "sportmaster"
    if "seller_name" not in out.columns:
        out["seller_name"] = "Sportmaster"
    else:
        out["seller_name"] = out["seller_name"].fillna("Sportmaster")
    out["seller_location"] = "RU"

    out["base_price"] = _num(out["base_price"])
    out["base_price_total"] = out["base_price"] * q

    out["supplier_price_fact"] = _num(out.get("supplier_price_fact", pd.Series(0.0, index=out.index)))
    out["supplier_price_fact_total"] = out["supplier_price_fact"] * q
    out["effective_purchase_total"] = np.where(
        out["supplier_price_fact"] > 0,
        out["supplier_price_fact"] * q,
        out["base_price_total"],
    )
    out["uses_fact_purchase_price"] = out["supplier_price_fact"] > 0

    out["ff_fee"] = _num(out.get("ff_fee", pd.Series(0.0, index=out.index)))
    out["socket_adapter_fee"] = _num(out.get("socket_adapter_fee", pd.Series(0.0, index=out.index)))
    out["ff_fee_total"] = out["ff_fee"] * q
    out["socket_adapter_total"] = out["socket_adapter_fee"] * q
    out["custom_delivery_fee_total"] = 0.0

    out["margin_price"] = _num(out.get("margin_price", pd.Series(0.0, index=out.index)))
    out["margin_price_total"] = _num(out.get("margin_price_total", out["margin_price"] * q))
    out["price_with_margin"] = out["margin_price_total"]
    out["our_margin"] = out["margin_price_total"] - out["base_price_total"]
    out["min_sell_price_total"] = out["margin_price_total"]

    raw_sell = _num(out.get("sell_price", pd.Series(np.nan, index=out.index)), default=np.nan)
    has_price_report = out.get(
        "has_price_report",
        raw_sell.notna(),
    )
    has_price_report = pd.Series(has_price_report, index=out.index).fillna(False).astype(bool)
    out["has_price_report"] = has_price_report

    # Фактическую цену нельзя подменять плановой margin_price: при отсутствующем
    # отчёте это создавало правдоподобное, но неверное значение.
    out["sell_price"] = raw_sell.where(has_price_report)

    out["expected_payout"] = _num(out.get("expected_payout", pd.Series(0.0, index=out.index)))
    out["payout_if_paid"] = _num(out.get("payout_if_paid", pd.Series(0.0, index=out.index)))
    out["market_services"] = (out["sell_price"] - out["payout_if_paid"]).where(has_price_report)

    out["expected_profit"] = _num(out.get("expected_profit", pd.Series(0.0, index=out.index)))
    report_profit = _num(
        out.get("profit", pd.Series(np.nan, index=out.index)),
        default=np.nan,
    )
    out["profit"] = report_profit.where(has_price_report)

    if "promo_discounts" not in out.columns:
        out["promo_discounts"] = 0.0
    out["promo_discounts"] = _num(out["promo_discounts"])
    out["income_after_fees"] = out["payout_if_paid"].where(has_price_report)
    out["income_after_fees_promo"] = out["income_after_fees"] + out["promo_discounts"]

    out["delivery_fee"] = _num(out.get("delivery_fee", pd.Series(0.0, index=out.index)))
    out["our_costs"] = (
        out["effective_purchase_total"] + out["ff_fee_total"] + out["socket_adapter_total"] + out["delivery_fee"]
    )
    out["profit_no_promo"] = (out["income_after_fees"] - out["our_costs"]).where(has_price_report)

    diff = _num(
        out.get("diff_from_min_price", pd.Series(np.nan, index=out.index)),
        default=np.nan,
    )
    out["diff_from_min_price"] = diff * q

    is_paid = out["date_realization"].notna()
    out["payment_status"] = np.select(
        [is_paid, has_price_report],
        ["Переведён", "Не переведён (отчёт загружен)"],
        default="Отчёт не загружен",
    )
    out["last_payment_date"] = pd.to_datetime(out["date_realization"], errors="coerce", utc=True)
    out["actual_profit"] = np.where(
        is_paid,
        out["profit"],
        np.where(has_price_report, 0.0, np.nan),
    )
    out["profit_vs_expected"] = out["actual_profit"] - out["expected_profit"]

    out["bonus_points"] = 0.0
    out["calc_commissions"] = 0.0
    out["fact_commissions"] = out["market_services"].clip(lower=0)
    out["seller_cancel_penalty"] = 0.0
    out["late_ship_penalty"] = 0.0

    status = out["fulfillment_status"].fillna("")
    refund_q = _num(out.get("refund_quantity", pd.Series(0.0, index=out.index)))
    out["is_cancelled_before"] = status.isin(_SM_CANCELLED_BEFORE)
    out["is_returned"] = status.isin(_SM_RETURNED) | (refund_q > 0)
    out["is_cancelled_any"] = out["is_cancelled_before"] | out["is_returned"]
    out["is_delivered"] = ~out["is_cancelled_any"]
    out["is_loss"] = out["profit"] < 0

    out["order_id_str"] = out["order_id"].astype(str)
    sp = out["sell_price"].replace(0, np.nan)
    bp = out["base_price_total"].replace(0, np.nan)
    out["take_rate_pct"] = (out["market_services"] / sp * 100).round(2)
    out["margin_pct"] = (out["profit"] / sp * 100).round(2)
    out["margin_plan_pct"] = (out["our_margin"] / sp * 100).round(2)
    out["margin_fact_pct"] = out["margin_pct"]
    out["margin_fact_rub"] = out["profit"]
    out["margin_plan_on_cost_pct"] = (out["our_margin"] / bp * 100).round(2)
    out["margin_fact_on_cost_pct"] = (out["profit"] / bp * 100).round(2)
    base_price_unit = out["base_price"].replace(0, np.nan)
    out["sm_profit_on_purchase_pct"] = (
        _num(out.get("profit_unit", pd.Series(0.0, index=out.index))) / base_price_unit * 100
    ).round(2)

    created = pd.to_datetime(out["created_at"], errors="coerce", utc=True)
    shipped = pd.to_datetime(out.get("shipment_date"), errors="coerce", utc=True)
    paid = pd.to_datetime(out["last_payment_date"], errors="coerce", utc=True)
    out["ship_lag_days"] = (shipped - created).dt.total_seconds() / 86400
    out["pay_lag_days"] = (paid - created).dt.total_seconds() / 86400

    return out
