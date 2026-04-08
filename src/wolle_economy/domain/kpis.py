"""Агрегация ключевых KPI-метрик из DataFrame заказов."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class KPIMetrics:
    # Денежные агрегаты
    revenue: float
    payout: float
    commissions: float
    our_costs: float
    profit: float
    profit_no_promo: float
    promo: float
    penalties: float
    compensations: float

    # Количественные
    n_orders: int
    n_items: float
    n_delivered: int
    n_returned: int
    n_cancelled: int
    n_loss: int

    # Производные (могут быть nan)
    aov: float
    aov_net: float
    net_margin: float
    take_rate: float
    contrib: float
    return_rate: float
    cancel_rate: float
    fulfill_rate: float
    loss_share: float
    items_per_o: float


def compute_kpis(df: pd.DataFrame) -> KPIMetrics:
    """Вычисляет KPI-метрики из DataFrame позиций заказов.

    df — полный DataFrame (одна строка = одна позиция заказа).
    Поля уровня заказа (sell_price, market_services, expected_payout)
    дедуплицируются по ya_order_id перед суммированием.
    """
    from wolle_economy.ui.helpers import orders_dedup  # локальный импорт — нет цикла

    od = orders_dedup(df)
    delivered = od[~od["is_cancelled_any"]]

    revenue = od["sell_price"].sum()
    payout = od["expected_payout"].sum()
    commissions = od["market_services"].sum()
    our_costs = df["our_costs"].sum()
    profit = df["profit"].sum()
    profit_no_promo = df["profit_no_promo"].sum()
    promo = df["promo_discounts"].sum()
    penalties = (
        od.get("seller_cancel_penalty", pd.Series(dtype=float)).fillna(0).sum()
        + od.get("late_ship_penalty", pd.Series(dtype=float)).fillna(0).sum()
    )
    compensations = od.get("compensations", pd.Series(dtype=float)).fillna(0).sum()

    n_orders = int(od["ya_order_id"].nunique())
    n_items = float(df["quantity"].fillna(1).sum())
    n_delivered = int(delivered["ya_order_id"].nunique())
    n_returned = int(od[od["is_returned"]]["ya_order_id"].nunique())
    n_cancelled = int(od[od["is_cancelled_before"]]["ya_order_id"].nunique())
    n_loss = int(df.groupby("ya_order_id")["profit"].sum().lt(0).sum())

    nan = float("nan")
    aov = revenue / n_orders if n_orders else nan
    aov_net = payout / n_orders if n_orders else nan
    net_margin = profit / revenue * 100 if revenue else nan
    take_rate = commissions / revenue * 100 if revenue else nan
    contrib = (payout - our_costs) / revenue * 100 if revenue else nan
    return_rate = n_returned / n_orders * 100 if n_orders else nan
    cancel_rate = n_cancelled / n_orders * 100 if n_orders else nan
    fulfill_rate = n_delivered / n_orders * 100 if n_orders else nan
    loss_share = n_loss / n_orders * 100 if n_orders else nan
    items_per_o = n_items / n_orders if n_orders else nan

    return KPIMetrics(
        revenue=revenue,
        payout=payout,
        commissions=commissions,
        our_costs=our_costs,
        profit=profit,
        profit_no_promo=profit_no_promo,
        promo=promo,
        penalties=penalties,
        compensations=compensations,
        n_orders=n_orders,
        n_items=n_items,
        n_delivered=n_delivered,
        n_returned=n_returned,
        n_cancelled=n_cancelled,
        n_loss=n_loss,
        aov=aov,
        aov_net=aov_net,
        net_margin=net_margin,
        take_rate=take_rate,
        contrib=contrib,
        return_rate=return_rate,
        cancel_rate=cancel_rate,
        fulfill_rate=fulfill_rate,
        loss_share=loss_share,
        items_per_o=items_per_o,
    )
