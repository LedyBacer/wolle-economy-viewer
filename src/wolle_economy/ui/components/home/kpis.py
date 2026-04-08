import pandas as pd
import streamlit as st

from wolle_economy.ui.formatters import fmt_money, fmt_pct
from wolle_economy.ui.helpers import orders_dedup


def render_kpis(df: pd.DataFrame) -> None:
    od = orders_dedup(df)

    revenue = od["sell_price"].sum()
    profit = df["profit"].sum()
    payout = od["expected_payout"].sum()
    n_orders = od["ya_order_id"].nunique()
    margin = profit / revenue * 100 if revenue else float("nan")
    aov = revenue / n_orders if n_orders else float("nan")

    c = st.columns(4)
    c[0].metric("Выручка", fmt_money(revenue))
    c[1].metric("Чистая прибыль", fmt_money(profit), help="С учётом промо-расходов")
    c[2].metric("Маржа", fmt_pct(margin))
    c[3].metric("Заказов", f"{n_orders:,}".replace(",", " "))

    c = st.columns(4)
    c[0].metric("Средний чек", fmt_money(aov))
    c[1].metric("Выплачено от ЯМ", fmt_money(payout))
    c[2].metric("Комиссии ЯМ", fmt_money(od["market_services"].sum()))
    c[3].metric("Наши затраты", fmt_money(df["our_costs"].sum()))

