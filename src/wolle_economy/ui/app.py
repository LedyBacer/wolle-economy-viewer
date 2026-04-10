"""
Wolle — Юнит-экономика Яндекс Маркет.
Точка входа Streamlit. Содержит обзорный дашборд с ключевыми показателями
и навигацией к детальным разделам.
"""

import logging

import streamlit as st

from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.home.kpis import render_kpis
from wolle_economy.ui.components.home.navigation import render_navigation
from wolle_economy.ui.components.home.trend import render_trend
from wolle_economy.ui.helpers import safe_load_orders

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    st.title("Wolle — юнит-экономика Яндекс Маркет")
    st.caption("Сводный обзор юнит-экономики по всем магазинам.")

    df = safe_load_orders()

    render_kpis(df)
    st.divider()
    render_trend(df)
    st.divider()
    render_navigation()


main()
