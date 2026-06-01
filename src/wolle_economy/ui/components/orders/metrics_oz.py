import pandas as pd
import streamlit as st

from wolle_economy.ui.helpers import oz_orders_dedup


def show_oz_metrics(df: pd.DataFrame) -> None:
    od = oz_orders_dedup(df)
    c = st.columns(5)
    c[0].metric("Заказов", f"{od['oz_order_id'].nunique():,}")
    c[1].metric("Ожид. прибыль", f"{df['expected_profit'].sum():,.0f} ₽")
    c[2].metric("Факт. прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    c[3].metric("Комиссии OZ", f"{od['market_services'].sum():,.0f} ₽")
    c[4].metric("Сумма выплат", f"{od['expected_payout'].sum():,.0f} ₽")
