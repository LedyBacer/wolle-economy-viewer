import pandas as pd
import streamlit as st

from wolle_economy.ui.components.analytics.tabs.abc import tab_abc
from wolle_economy.ui.components.analytics.tabs.cashflow import tab_cashflow
from wolle_economy.ui.components.analytics.tabs.distribution import tab_distribution
from wolle_economy.ui.components.analytics.tabs.kpi import tab_kpi
from wolle_economy.ui.components.analytics.tabs.ops import tab_ops
from wolle_economy.ui.components.analytics.tabs.pricing import tab_pricing
from wolle_economy.ui.components.analytics.tabs.returns import tab_returns
from wolle_economy.ui.components.analytics.tabs.suppliers import tab_suppliers
from wolle_economy.ui.components.analytics.tabs.trends import tab_trends


def render_analytics_tabs(df: pd.DataFrame, key_prefix: str = "ym") -> None:
    tabs = st.tabs(
        [
            "KPI",
            "ABC-анализ",
            "Возвраты и отмены",
            "Поставщики",
            "Ценообразование",
            "Денежный поток",
            "Операционные метрики",
            "Тренды",
            "Распределение прибыли",
        ],
        key=f"{key_prefix}_analytics_tab",
        on_change="rerun",
    )

    granularity_key = f"{key_prefix}_trends_granularity"
    if not tabs[7].open and granularity_key in st.session_state:
        st.session_state[granularity_key] = st.session_state[granularity_key]

    if tabs[0].open:
        with tabs[0]:
            tab_kpi(df)
    if tabs[1].open:
        with tabs[1]:
            tab_abc(df)
    if tabs[2].open:
        with tabs[2]:
            tab_returns(df)
    if tabs[3].open:
        with tabs[3]:
            tab_suppliers(df)
    if tabs[4].open:
        with tabs[4]:
            tab_pricing(df)
    if tabs[5].open:
        with tabs[5]:
            tab_cashflow(df)
    if tabs[6].open:
        with tabs[6]:
            tab_ops(df)
    if tabs[7].open:
        with tabs[7]:
            tab_trends(df, key_prefix=key_prefix)
    if tabs[8].open:
        with tabs[8]:
            tab_distribution(df)
