import pandas as pd
import streamlit as st

from wolle_economy.ui.helpers import sm_orders_dedup


def show_sm_metrics(df: pd.DataFrame) -> None:
    od = sm_orders_dedup(df)
    c = st.columns(5)
    c[0].metric("Заказов", f"{od['sm_order_id'].nunique():,}")
    c[1].metric("Ожид. прибыль", f"{df['expected_profit'].sum():,.0f} ₽")
    c[2].metric("Факт. прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    c[3].metric("Комиссии SM", f"{od['market_services'].sum():,.0f} ₽")
    c[4].metric("Сумма выплат", f"{od['expected_payout'].sum():,.0f} ₽")
