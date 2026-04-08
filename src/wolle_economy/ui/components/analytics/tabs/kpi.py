import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wolle_economy.ui.formatters import fmt_money, fmt_pct
from wolle_economy.ui.helpers import orders_dedup


def tab_kpi(df: pd.DataFrame) -> None:
    st.subheader("Ключевые показатели")

    od = orders_dedup(df)
    delivered = od[~od["is_cancelled_any"]]

    # Денежные агрегаты
    revenue = od["sell_price"].sum()
    payout = od["expected_payout"].sum()
    commissions = od["market_services"].sum()
    our_costs = df["our_costs"].sum()
    profit = df["profit"].sum()
    profit_no_pr = df["profit_no_promo"].sum()
    promo = df["promo_discounts"].sum()
    penalties = (
        od.get("seller_cancel_penalty", pd.Series(dtype=float)).fillna(0).sum()
        + od.get("late_ship_penalty", pd.Series(dtype=float)).fillna(0).sum()
    )
    compensations = od.get("compensations", pd.Series(dtype=float)).fillna(0).sum()

    n_orders = od["ya_order_id"].nunique()
    n_items = df["quantity"].fillna(1).sum()
    n_delivered = delivered["ya_order_id"].nunique()
    n_returned = od[od["is_returned"]]["ya_order_id"].nunique()
    n_cancelled = od[od["is_cancelled_before"]]["ya_order_id"].nunique()
    n_loss = df.groupby("ya_order_id")["profit"].sum().lt(0).sum()

    aov = revenue / n_orders if n_orders else np.nan
    aov_net = payout / n_orders if n_orders else np.nan
    take_rate = commissions / revenue * 100 if revenue else np.nan
    net_margin = profit / revenue * 100 if revenue else np.nan
    contrib = (payout - our_costs) / revenue * 100 if revenue else np.nan
    return_rate = n_returned / n_orders * 100 if n_orders else np.nan
    cancel_rate = n_cancelled / n_orders * 100 if n_orders else np.nan
    fulfill_rate = n_delivered / n_orders * 100 if n_orders else np.nan
    loss_share = n_loss / n_orders * 100 if n_orders else np.nan
    items_per_o = n_items / n_orders if n_orders else np.nan

    # ---- Деньги ----
    st.markdown("**Деньги**")
    c = st.columns(4)
    c[0].metric("Выручка (GMV)", fmt_money(revenue))
    c[1].metric("Выплата от ЯМ", fmt_money(payout))
    c[2].metric("Прибыль (с промо)", fmt_money(profit))
    c[3].metric("Прибыль без промо", fmt_money(profit_no_pr))

    c = st.columns(4)
    c[0].metric("Комиссии ЯМ", fmt_money(commissions))
    c[1].metric("Наши затраты", fmt_money(our_costs))
    c[2].metric("Промо-расходы", fmt_money(promo))
    c[3].metric("Штрафы / Компенсации", f"{fmt_money(penalties)} / {fmt_money(compensations)}")

    # ---- Маржинальность и тейк ----
    st.markdown("**Маржинальность**")
    c = st.columns(4)
    c[0].metric("Net Margin", fmt_pct(net_margin), help="Прибыль / GMV")
    c[1].metric("Contribution Margin", fmt_pct(contrib), help="(Выплата − затраты) / GMV")
    c[2].metric("Take Rate ЯМ", fmt_pct(take_rate), help="Комиссии ЯМ / GMV")
    c[3].metric("Доля убыточных заказов", fmt_pct(loss_share))

    # ---- Объёмы ----
    st.markdown("**Объёмы и средние чеки**")
    c = st.columns(4)
    c[0].metric("Заказов", f"{n_orders:,}".replace(",", " "))
    c[1].metric("Позиций / шт", f"{int(n_items):,}".replace(",", " "))
    c[2].metric("AOV (брутто)", fmt_money(aov), help="Средний чек по sell_price")
    c[3].metric("AOV (нетто, после комиссий)", fmt_money(aov_net))

    c = st.columns(4)
    c[0].metric("Позиций на заказ", f"{items_per_o:.2f}")
    c[1].metric("Fulfillment Rate", fmt_pct(fulfill_rate), help="Доставлено / всего")
    c[2].metric("Cancel Rate", fmt_pct(cancel_rate), help="Отменено до отгрузки / всего")
    c[3].metric("Return Rate", fmt_pct(return_rate), help="Возвраты+невыкупы / всего")

    st.divider()

    # ---- Водопад: выручка → прибыль ----
    st.markdown("**Декомпозиция прибыли (waterfall)**")
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=["Выручка (GMV)", "− Комиссии ЯМ", "− Наши затраты", "+ Промо (−)", "Прибыль"],
            y=[revenue, -commissions, -our_costs, promo, 0],
            textposition="outside",
            text=[fmt_money(v) for v in [revenue, -commissions, -our_costs, promo, profit]],
            connector={"line": {"color": "rgb(120,120,120)"}},
        )
    )
    fig.update_layout(height=420, margin={"l": 20, "r": 20, "t": 20, "b": 20})
    st.plotly_chart(fig, width="stretch")

