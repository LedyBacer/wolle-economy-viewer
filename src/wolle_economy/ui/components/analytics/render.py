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


def render_analytics_tabs(df: pd.DataFrame) -> None:
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
        ]
    )

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
        tab_trends(df)
    with tabs[8]:
        tab_distribution(df)

