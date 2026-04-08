import pandas as pd
import streamlit as st

from wolle_economy.ui.helpers import orders_dedup


def show_metrics(df: pd.DataFrame) -> None:
    # sell_price / market_services / expected_payout хранятся на уровне заказа,
    # но строки — позиции. Для корректной суммы дедуплицируем по заказу.
    od = orders_dedup(df)
    c = st.columns(5)
    c[0].metric("Заказов", f"{od['ya_order_id'].nunique():,}")
    c[1].metric("Ожид. прибыль", f"{df['expected_profit'].sum():,.0f} ₽")
    c[2].metric("Факт. прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    c[3].metric("Комиссии ЯМ", f"{od['market_services'].sum():,.0f} ₽")
    c[4].metric("Сумма выплат", f"{od['expected_payout'].sum():,.0f} ₽")

