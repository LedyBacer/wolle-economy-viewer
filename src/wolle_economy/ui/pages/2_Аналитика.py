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
from wolle_economy.ui.helpers import safe_load_marketplace_orders, offer_data_refresh
from wolle_economy.ui.marketplaces import iter_marketplace_ui

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    st.title("Аналитика юнит-экономики")
    st.caption("Все денежные показатели в рублях.")

    marketplace_ui = iter_marketplace_ui()
    tabs = st.tabs([spec.title for spec, _ in marketplace_ui], on_change="rerun")
    # Streamlit удаляет состояние виджетов, которые не были отрисованы.
    inactive = tuple(f"{spec.code}_" for tab, (spec, _) in zip(tabs, marketplace_ui) if not tab.open)
    for key in st.session_state:
        if key.startswith(inactive):
            st.session_state[key] = st.session_state[key]

    for tab, (spec, ui) in zip(tabs, marketplace_ui):
        if not tab.open:
            continue
        with tab:
            offer_data_refresh(spec)
            seller_ids, date_from, date_to = ui.db_filters()
            df = safe_load_marketplace_orders(
                spec,
                seller_ids=seller_ids,
                date_from=date_from,
                date_to=date_to,
            )

            if df.empty:
                st.warning(f"Нет данных {spec.title} по выбранным фильтрам.")
            else:
                ui.analytics(df)


main()
