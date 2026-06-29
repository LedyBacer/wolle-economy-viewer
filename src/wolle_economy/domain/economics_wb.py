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

    base_price_raw = pd.to_numeric(out.get("base_price", pd.Series(np.nan, index=out.index)), errors="coerce")
    sell_price_plan_raw = pd.to_numeric(
        out.get("sell_price_plan", pd.Series(np.nan, index=out.index)),
        errors="coerce",
    )

    out["base_price"] = base_price_raw.fillna(0.0)
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

    out["sell_price_plan"] = sell_price_plan_raw.fillna(0.0)
    out["calc_commissions"] = (
        _num(out.get("category_fee", pd.Series(0.0, index=out.index)))
        + _num(out.get("acquiring_fee_plan", pd.Series(0.0, index=out.index)))
        + _num(out.get("delivery_fee_plan", pd.Series(0.0, index=out.index)))
    )
    out["commission_fee_diff"] = np.where(
        _num(out.get("report_commission", pd.Series(0.0, index=out.index))) != 0,
        _num(out.get("category_fee", pd.Series(0.0, index=out.index)))
        - _num(out.get("report_commission", pd.Series(0.0, index=out.index))),
        0.0,
    )
    out["delivery_fee_diff"] = np.where(
        _num(out.get("report_delivery_fee", pd.Series(0.0, index=out.index))) != 0,
        _num(out.get("delivery_fee_plan", pd.Series(0.0, index=out.index)))
        - _num(out.get("report_delivery_fee", pd.Series(0.0, index=out.index))),
        0.0,
    )

    planned_payout = (out["sell_price_plan"] - out["calc_commissions"]).clip(lower=0)
    out["expected_payout"] = planned_payout
    expected_profit_raw = (
        sell_price_plan_raw
        - out["socket_adapter_total"]
        - (base_price_raw * q)
        - out["ff_fee_total"]
        - _num(out.get("category_fee", pd.Series(0.0, index=out.index)))
        - _num(out.get("acquiring_fee_plan", pd.Series(0.0, index=out.index)))
        - _num(out.get("delivery_fee_plan", pd.Series(0.0, index=out.index)))
    )
    out["expected_profit"] = expected_profit_raw.fillna(0.0)

    wb_status = out.get("wb_status", pd.Series("", index=out.index)).fillna("")
    return_docs = _num(out.get("return_docs", pd.Series(0.0, index=out.index)))

    out["is_cancelled_before"] = wb_status.isin(_WB_CANCELLED_BEFORE)
    out["is_returned"] = wb_status.isin(_WB_RETURNED) | (return_docs > 0)
    is_sold_status = wb_status.isin(_WB_DELIVERED)
    out["is_delivered"] = is_sold_status & ~out["is_returned"]
    out["is_cancelled_any"] = out["is_cancelled_before"] | out["is_returned"]

    report_sell_raw = pd.to_numeric(
        out.get("report_sell_price", pd.Series(np.nan, index=out.index)),
        errors="coerce",
    )
    report_sell = report_sell_raw.fillna(0.0)
    report_rows = _num(out.get("report_rows", pd.Series(0.0, index=out.index)))

    out["sell_price"] = np.where(report_rows > 0, report_sell, 0.0)

    report_market_services_raw = pd.to_numeric(
        out.get("report_market_services", pd.Series(np.nan, index=out.index)),
        errors="coerce",
    )
    report_income_raw = report_sell_raw - report_market_services_raw
    out["compensations"] = _num(out.get("report_compensation", pd.Series(0.0, index=out.index))).clip(lower=0)

    report_income = report_income_raw.fillna(0.0)
    out["income_after_fees"] = np.where(report_rows > 0, report_income, 0.0)
    out["expected_payout"] = np.where(report_rows > 0, out["income_after_fees"], planned_payout)
    out["market_services"] = np.where(
        report_rows > 0,
        out["sell_price"] - out["income_after_fees"],
        0.0,
    )
    out["fact_commissions"] = out["market_services"].clip(lower=0)
    if "promo_discounts" not in out.columns:
        out["promo_discounts"] = 0.0
    out["promo_discounts"] = _num(out["promo_discounts"])
    out["income_after_fees_promo"] = out["income_after_fees"] + out["promo_discounts"]

    report_retail_sum = pd.to_numeric(out.get("report_retail_sum", report_sell_raw), errors="coerce")
    returned_once = return_docs == 1
    sold_profit = np.select(
        [
            report_retail_sum.fillna(0.0) == 0,
            report_income_raw.isna(),
            returned_once,
        ],
        [
            0.0,
            0.0,
            out["income_after_fees"] - out["socket_adapter_total"] - out["ff_fee_total"],
        ],
        default=(
            out["income_after_fees"]
            - out["effective_purchase_total"]
            - out["socket_adapter_total"]
            - out["ff_fee_total"]
        ),
    )
    base_profit = np.select(
        [
            is_sold_status,
            wb_status.isin(_WB_RETURNED),
        ],
        [
            sold_profit,
            out["income_after_fees"],
        ],
        default=0.0,
    )
    out["our_costs"] = np.select(
        [
            is_sold_status & ~returned_once & (report_retail_sum.fillna(0.0) != 0),
            is_sold_status & returned_once,
        ],
        [
            out["effective_purchase_total"] + out["ff_fee_total"] + out["socket_adapter_total"],
            out["ff_fee_total"] + out["socket_adapter_total"],
        ],
        default=0.0,
    )

    out["profit_no_promo"] = base_profit
    out["profit"] = base_profit + out["promo_discounts"]
    out["diff_from_min_price"] = out["sell_price"] - out["min_sell_price_total"]

    out["bonus_points"] = 0.0
    out["seller_cancel_penalty"] = 0.0
    out["late_ship_penalty"] = 0.0
    out["payment_status"] = np.where(report_rows > 0, "Переведён", None)
    out["payout_if_paid"] = np.where(out["payment_status"] == "Переведён", out["income_after_fees"], 0.0)
    payment_date = out.get("report_payment_date", out.get("created_at"))
    out["last_payment_date"] = pd.to_datetime(
        np.where(out["payment_status"] == "Переведён", payment_date, pd.NaT),
        errors="coerce",
        utc=True,
    )
    out["actual_profit"] = np.where(out["payment_status"] == "Переведён", out["profit"], 0.0)
    out["profit_vs_expected"] = np.where(out["profit"] != 0, out["profit"] - out["expected_profit"], 0.0)

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
    effective_purchase = pd.Series(out["effective_purchase_total"], index=out.index).replace(0, np.nan)
    out["wb_profit_on_purchase_pct"] = (out["profit"] / effective_purchase * 100).round(2)

    created = pd.to_datetime(out["created_at"], errors="coerce", utc=True)
    shipped = pd.to_datetime(out.get("shipment_date"), errors="coerce", utc=True)
    paid = pd.to_datetime(out["last_payment_date"], errors="coerce", utc=True)
    out["ship_lag_days"] = (shipped - created).dt.total_seconds() / 86400
    out["pay_lag_days"] = (paid - created).dt.total_seconds() / 86400

    return out
