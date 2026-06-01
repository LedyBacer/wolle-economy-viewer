"""Расчёт и нормализация юнит-экономики Wildberries."""

from __future__ import annotations

import numpy as np
import pandas as pd

_WB_CANCELLED_BEFORE = frozenset({"declined_by_client"})
_WB_RETURNED = frozenset({"canceled", "canceled_by_client", "defect"})
_WB_DELIVERED = frozenset({"sold"})


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def calc_wb_economics(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит сырые данные WB к каноническому контракту приложения."""
    if df.empty:
        return df

    out = df.copy()
    q = _num(out.get("quantity", pd.Series(1.0, index=out.index)), default=1.0)
    out["quantity"] = q

    out["ya_order_id"] = out["wb_order_id"]
    out["channel"] = "wildberries"

    out["base_price"] = _num(out.get("base_price", pd.Series(0.0, index=out.index)))
    out["base_price_total"] = out["base_price"] * q

    out["supplier_price_fact"] = _num(out.get("supplier_price_fact", pd.Series(0.0, index=out.index)))
    out["effective_purchase_total"] = np.where(
        out["supplier_price_fact"] > 0,
        out["supplier_price_fact"] * q,
        out["base_price_total"],
    )
    out["uses_fact_purchase_price"] = out["supplier_price_fact"] > 0

    out["ff_fee"] = _num(out.get("ff_fee", pd.Series(50.0, index=out.index)), default=50.0)
    out["socket_adapter_fee"] = _num(out.get("socket_adapter_fee", pd.Series(0.0, index=out.index)))
    out["ff_fee_total"] = out["ff_fee"] * q
    out["socket_adapter_total"] = out["socket_adapter_fee"] * q
    out["custom_delivery_fee_total"] = 0.0

    out["min_sell_price"] = _num(out.get("min_sell_price", pd.Series(0.0, index=out.index)))
    out["min_sell_price_total"] = out["min_sell_price"] * q

    out["price_with_margin"] = out["min_sell_price_total"]
    out["our_margin"] = out["price_with_margin"] - out["base_price_total"]

    out["sell_price_plan"] = _num(out.get("sell_price_plan", pd.Series(0.0, index=out.index)))
    out["calc_commissions"] = (
        _num(out.get("category_fee", pd.Series(0.0, index=out.index)))
        + _num(out.get("acquiring_fee_plan", pd.Series(0.0, index=out.index)))
        + _num(out.get("delivery_fee_plan", pd.Series(0.0, index=out.index)))
    )

    out["expected_payout"] = (out["sell_price_plan"] - out["calc_commissions"]).clip(lower=0)
    out["expected_profit"] = out["expected_payout"] - (
        out["base_price_total"] + out["ff_fee_total"] + out["socket_adapter_total"]
    )

    wb_status = out.get("wb_status", pd.Series("", index=out.index)).fillna("")
    return_docs = _num(out.get("return_docs", pd.Series(0.0, index=out.index)))

    out["is_cancelled_before"] = wb_status.isin(_WB_CANCELLED_BEFORE)
    out["is_returned"] = wb_status.isin(_WB_RETURNED) | (return_docs > 0)
    out["is_delivered"] = wb_status.isin(_WB_DELIVERED) & ~out["is_returned"]
    out["is_cancelled_any"] = out["is_cancelled_before"] | out["is_returned"]

    report_sell = _num(out.get("report_sell_price", pd.Series(0.0, index=out.index)))
    report_rows = _num(out.get("report_rows", pd.Series(0.0, index=out.index)))

    out["sell_price"] = np.where(
        out["is_delivered"],
        np.where(report_rows > 0, report_sell, out["sell_price_plan"]),
        0.0,
    )

    report_market_services = _num(out.get("report_market_services", pd.Series(0.0, index=out.index)))
    out["market_services"] = np.where(
        report_rows > 0,
        report_market_services,
        np.where(out["is_delivered"], out["calc_commissions"], 0.0),
    )
    out["fact_commissions"] = out["market_services"].clip(lower=0)

    report_compensation = _num(out.get("report_compensation", pd.Series(0.0, index=out.index)))
    out["compensations"] = report_compensation.clip(lower=0)

    out["income_after_fees"] = (out["sell_price"] - out["market_services"]).clip(lower=0)
    if "promo_discounts" not in out.columns:
        out["promo_discounts"] = 0.0
    out["promo_discounts"] = _num(out["promo_discounts"])
    out["income_after_fees_promo"] = out["income_after_fees"] + out["promo_discounts"]

    out["our_costs"] = np.where(
        out["is_delivered"],
        out["effective_purchase_total"] + out["ff_fee_total"] + out["socket_adapter_total"],
        np.where(out["is_returned"], out["ff_fee_total"] + out["socket_adapter_total"], 0.0),
    )

    base_profit = np.where(
        out["is_delivered"],
        out["income_after_fees"] - out["our_costs"],
        np.where(out["is_returned"], report_compensation - out["market_services"], 0.0),
    )

    out["profit_no_promo"] = base_profit
    out["profit"] = base_profit + out["promo_discounts"]
    out["diff_from_min_price"] = out["sell_price"] - out["min_sell_price_total"]

    out["bonus_points"] = 0.0
    out["seller_cancel_penalty"] = 0.0
    out["late_ship_penalty"] = 0.0
    out["payment_status"] = np.where(report_rows > 0, "Переведён", None)
    out["payout_if_paid"] = np.where(out["payment_status"] == "Переведён", out["income_after_fees"], 0.0)
    out["last_payment_date"] = pd.to_datetime(
        np.where(out["payment_status"] == "Переведён", out.get("created_at"), pd.NaT),
        errors="coerce",
        utc=True,
    )
    out["actual_profit"] = np.where(out["payment_status"] == "Переведён", out["profit"], 0.0)
    out["profit_vs_expected"] = out["actual_profit"] - out["expected_profit"]

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

    created = pd.to_datetime(out["created_at"], errors="coerce", utc=True)
    shipped = pd.to_datetime(out.get("shipment_date"), errors="coerce", utc=True)
    paid = pd.to_datetime(out["last_payment_date"], errors="coerce", utc=True)
    out["ship_lag_days"] = (shipped - created).dt.total_seconds() / 86400
    out["pay_lag_days"] = (paid - created).dt.total_seconds() / 86400

    return out
