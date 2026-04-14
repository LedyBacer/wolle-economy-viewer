"""
Wolle — Юнит-экономика Яндекс Маркет.
Точка входа Streamlit. Содержит обзорный дашборд с ключевыми показателями
и навигацией к детальным разделам.
"""

import logging

import pandas as pd
import streamlit as st

from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.home.kpis import render_kpis
from wolle_economy.ui.components.home.navigation import render_navigation
from wolle_economy.ui.components.home.trend import render_trend
from wolle_economy.ui.helpers import safe_load_mm_orders, safe_load_orders

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _render_mm_kpis(df: pd.DataFrame) -> None:
    """Краткие KPI МегаМаркет на главной странице."""
    from wolle_economy.ui.formatters import fmt_money, fmt_pct
    from wolle_economy.ui.helpers import mm_orders_dedup

    od = mm_orders_dedup(df)
    revenue = od["sell_price"].sum()
    profit = df["profit"].sum()
    n_orders = int(od["mm_order_id"].nunique())
    margin = profit / revenue * 100 if revenue else float("nan")

    c = st.columns(4)
    c[0].metric("Выручка", fmt_money(revenue))
    c[1].metric("Чистая прибыль", fmt_money(profit))
    c[2].metric("Маржа", fmt_pct(margin))
    c[3].metric("Заказов", f"{n_orders:,}".replace(",", " "))


def main() -> None:
    st.title("Wolle — юнит-экономика")
    st.caption("Сводный обзор юнит-экономики по всем маркетплейсам.")

    df = safe_load_orders()

    st.subheader("Яндекс Маркет")
    render_kpis(df)

    mm_df = safe_load_mm_orders()
    if not mm_df.empty:
        st.subheader("МегаМаркет")
        _render_mm_kpis(mm_df)

    st.divider()
    render_trend(df)
    st.divider()
    render_navigation()


main()
