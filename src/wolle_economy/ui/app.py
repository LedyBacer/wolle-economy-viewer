"""
Wolle — Юнит-экономика маркетплейсов.
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
from wolle_economy.ui.helpers import safe_load_marketplace_orders
from wolle_economy.ui.marketplaces import iter_marketplace_ui

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    st.title("Wolle — юнит-экономика")
    st.caption("Сводный обзор юнит-экономики по всем маркетплейсам.")

    all_parts: list[pd.DataFrame] = []
    for spec, _ in iter_marketplace_ui():
        df = safe_load_marketplace_orders(spec)
        if df.empty:
            continue
        st.subheader(spec.title)
        render_kpis(df)
        all_parts.append(df)

    if all_parts:
        st.divider()
        render_trend(pd.concat(all_parts, ignore_index=True))

    st.divider()
    render_navigation()


main()
