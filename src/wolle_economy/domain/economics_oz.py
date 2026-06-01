"""Расчёт и нормализация юнит-экономики Ozon."""

from __future__ import annotations

import numpy as np
import pandas as pd

_OZ_CANCELLED_BEFORE = frozenset({"cancelled"})
_OZ_RETURNED_LABELS = frozenset({"Возврат", "Частичный возврат"})
_OZ_DELIVERED_LABELS = frozenset({"Доставлен"})


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def calc_oz_economics(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит сырые данные Ozon к каноническому контракту приложения."""
    if df.empty:
        return df

    out = df.copy()
    q = _num(out.get("quantity", pd.Series(1.0, index=out.index)), default=1.0)
    out["quantity"] = q

    out["ya_order_id"] = out["oz_order_id"]
    out["channel"] = "ozon"

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

    out["expected_payout"] = out["sell_price_plan"] - out["calc_commissions"]
    out["expected_profit"] = out["expected_payout"] - (
        out["base_price_total"] + out["ff_fee_total"] + out["socket_adapter_total"]
    )

    oz_status = out.get("oz_status", pd.Series("", index=out.index)).fillna("")
    return_docs = _num(out.get("return_docs", pd.Series(0.0, index=out.index)))
    refund_qty = _num(out.get("refund_quantity", pd.Series(0.0, index=out.index)))
    fulfillment = out.get("fulfillment_status", pd.Series("", index=out.index)).fillna("")

    is_oz_delivered = oz_status == "delivered"
    out["is_cancelled_before"] = oz_status.isin(_OZ_CANCELLED_BEFORE)
    out["is_returned"] = (~out["is_cancelled_before"]) & is_oz_delivered & (
        fulfillment.isin(_OZ_RETURNED_LABELS) | (return_docs > 0)
    )
    out["is_delivered"] = (~out["is_cancelled_before"]) & is_oz_delivered & ~out["is_returned"]
    out["is_cancelled_any"] = out["is_cancelled_before"] | out["is_returned"]
    has_refund = is_oz_delivered & (return_docs > 0)
    is_partial_return = has_refund & (refund_qty > 0) & (refund_qty < q)
    is_full_return = has_refund & ~is_partial_return
    is_delivered_no_refund = out["is_delivered"] & ~has_refund

    report_sell = _num(out.get("report_sell_price", pd.Series(0.0, index=out.index)))
    report_rows = _num(out.get("report_rows", pd.Series(0.0, index=out.index)))
    is_final = out["is_delivered"] | out["is_returned"] | out["is_cancelled_before"]
    out["sell_price"] = np.where(out["is_delivered"] | out["is_returned"], report_sell, 0.0)

    report_market_services = _num(out.get("report_market_services", pd.Series(0.0, index=out.index)))
    out["market_services"] = np.where((report_rows > 0) & is_final, report_market_services, 0.0)
    out["fact_commissions"] = out["market_services"].clip(lower=0)

    out["revenue_after_commission"] = _num(
        out.get("revenue_after_commission", pd.Series(0.0, index=out.index))
    )
    out["income_after_fees"] = np.where(
        is_delivered_no_refund | is_partial_return | is_full_return,
        out["revenue_after_commission"],
        0.0,
    )

    if "promo_discounts" not in out.columns:
        out["promo_discounts"] = 0.0
    out["promo_discounts"] = _num(out["promo_discounts"])
    out["income_after_fees_promo"] = out["income_after_fees"] + out["promo_discounts"]

    delivered_qty = (q - refund_qty).clip(lower=0)
    purchase_unit = np.where(out["supplier_price_fact"] > 0, out["supplier_price_fact"], out["base_price"])
    purchase_delivered_total = purchase_unit * delivered_qty
    socket_delivered_total = out["socket_adapter_fee"] * delivered_qty

    out["our_costs"] = np.where(
        is_delivered_no_refund,
        out["effective_purchase_total"] + out["ff_fee_total"] + out["socket_adapter_total"],
        np.where(
            is_partial_return,
            out["ff_fee_total"] + socket_delivered_total + purchase_delivered_total,
            np.where(
                is_full_return,
                out["ff_fee_total"],
                np.where(
                    out["is_cancelled_before"]
                    & out.get("cancelled_after_ship", pd.Series(False, index=out.index)).fillna(False),
                    out["ff_fee_total"],
                    0.0,
                ),
            ),
        ),
    )

    out["seller_cancel_penalty"] = _num(out.get("cancel_penalty", pd.Series(0.0, index=out.index)))
    out["late_ship_penalty"] = _num(
        out.get("late_shipment_penalty", pd.Series(0.0, index=out.index))
    ) + _num(out.get("late_recommend_penalty", pd.Series(0.0, index=out.index)))

    cancelled_after_ship = out.get("cancelled_after_ship", pd.Series(False, index=out.index)).fillna(False)
    logistics_fact = _num(out.get("logistics_fact", pd.Series(0.0, index=out.index)))
    order_process_fact = _num(out.get("order_process_fact", pd.Series(0.0, index=out.index)))

    delivered_no_refund_profit = (
        out["revenue_after_commission"] - out["ff_fee_total"] - out["socket_adapter_total"] - out["effective_purchase_total"]
    )
    delivered_partial_return_profit = (
        out["revenue_after_commission"] - out["ff_fee_total"] - socket_delivered_total - purchase_delivered_total
    )
    delivered_full_return_profit = out["revenue_after_commission"] - out["ff_fee_total"]
    cancelled_after_ship_profit = -logistics_fact - order_process_fact - out["ff_fee_total"]

    base_profit = np.where(
        out["is_cancelled_before"],
        np.where(cancelled_after_ship, cancelled_after_ship_profit, 0.0),
        np.where(
            is_delivered_no_refund,
            delivered_no_refund_profit,
            np.where(
                is_partial_return,
                delivered_partial_return_profit,
                np.where(is_full_return, delivered_full_return_profit, 0.0),
            ),
        ),
    )

    out["profit_no_promo"] = base_profit
    out["profit"] = base_profit + out["promo_discounts"]
    out["diff_from_min_price"] = out["sell_price"] - out["min_sell_price_total"]
    out["bonus_points"] = 0.0

    out["payment_status"] = np.where(
        (report_rows > 0) & (is_delivered_no_refund | is_partial_return | is_full_return),
        "Переведён",
        None,
    )
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
