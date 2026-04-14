"""Аналитика юнит-экономики: KPI-дашборд, ABC-анализ, возвраты, поставщики,
ценообразование, денежный поток, операционные метрики и тренды.
"""

import logging

import pandas as pd
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
from wolle_economy.ui.components.orders.filters_mm import sidebar_mm_db_filters
from wolle_economy.ui.helpers import safe_load_mm_orders, safe_load_orders

setup_logging()
logger = logging.getLogger(__name__)


def _render_mm_analytics(df: pd.DataFrame) -> None:
    """Аналитики для МегаМаркет."""
    from wolle_economy.ui.components.analytics.tabs.abc import tab_abc
    from wolle_economy.ui.components.analytics.tabs.cashflow import tab_cashflow
    from wolle_economy.ui.components.analytics.tabs.distribution import tab_distribution
    from wolle_economy.ui.components.analytics.tabs.kpi import tab_kpi
    from wolle_economy.ui.components.analytics.tabs.ops import tab_ops
    from wolle_economy.ui.components.analytics.tabs.pricing import tab_pricing
    from wolle_economy.ui.components.analytics.tabs.returns import tab_returns
    from wolle_economy.ui.components.analytics.tabs.suppliers import tab_suppliers
    from wolle_economy.ui.components.analytics.tabs.trends import tab_trends

    tabs = st.tabs([
        "KPI",
        "ABC-анализ",
        "Возвраты и отмены",
        "Поставщики",
        "Ценообразование",
        "Денежный поток",
        "Операционные метрики",
        "Тренды",
        "Распределение прибыли",
    ])
    with tabs[0]:
        tab_kpi(df)
    with tabs[1]:
        tab_abc(df)
    with tabs[2]:
        tab_returns(df)
    with tabs[3]:
        tab_suppliers(df)
    with tabs[4]:
        tab_pricing(df)
    with tabs[5]:
        tab_cashflow(df)
    with tabs[6]:
        tab_ops(df)
    with tabs[7]:
        tab_trends(df, key_prefix="mm")
    with tabs[8]:
        tab_distribution(df)


def main() -> None:
    st.title("Аналитика юнит-экономики")
    st.caption("Все денежные показатели в рублях.")

    tab_ym, tab_mm = st.tabs(["Яндекс Маркет", "МегаМаркет"])

    with tab_ym:
        seller_ids, date_from, date_to = sidebar_db_filters()
        df = safe_load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)

        if df.empty:
            st.warning("Нет данных по выбранным фильтрам.")
        else:
            render_analytics_tabs(df)

    with tab_mm:
        mm_seller_ids, mm_date_from, mm_date_to = sidebar_mm_db_filters()
        mm_df = safe_load_mm_orders(
            seller_ids=mm_seller_ids, date_from=mm_date_from, date_to=mm_date_to
        )

        if mm_df.empty:
            st.warning("Нет данных МегаМаркет по выбранным фильтрам.")
        else:
            _render_mm_analytics(mm_df)


main()
