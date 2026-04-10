"""Аналитика юнит-экономики: KPI-дашборд, ABC-анализ, возвраты, поставщики,
ценообразование, денежный поток, операционные метрики и тренды.
"""

import logging

import streamlit as st

st.set_page_config(
    page_title="Wolle — Аналитика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.analytics.filters import sidebar_db_filters
from wolle_economy.ui.components.analytics.render import render_analytics_tabs
from wolle_economy.ui.helpers import safe_load_orders

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    st.title("Аналитика юнит-экономики")
    st.caption("Все денежные показатели в рублях.")

    # Шаг 1: DB-фильтры (продавец, дата)
    seller_ids, date_from, date_to = sidebar_db_filters()

    # Шаг 2: Загрузка с фильтрацией на стороне БД
    df = safe_load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)

    if df.empty:
        st.warning("Нет данных по выбранным фильтрам.")
        st.stop()
        return

    render_analytics_tabs(df)


main()
