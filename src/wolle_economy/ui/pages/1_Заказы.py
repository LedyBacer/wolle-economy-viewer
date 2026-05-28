import logging

import streamlit as st

st.set_page_config(
    page_title="Wolle — Заказы",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.helpers import safe_load_marketplace_orders
from wolle_economy.ui.marketplaces import iter_marketplace_ui

setup_logging()
logger = logging.getLogger(__name__)

def main() -> None:
    st.title("Заказы")
    st.caption("Позиции заказов с расчётом юнит-экономики. Используйте фильтры в боковой панели.")

    marketplace_ui = iter_marketplace_ui()
    tabs = st.tabs([spec.title for spec, _ in marketplace_ui])

    for tab, (spec, ui) in zip(tabs, marketplace_ui):
        with tab:
            seller_ids, date_from, date_to = ui.db_filters()
            df = safe_load_marketplace_orders(
                spec,
                seller_ids=seller_ids,
                date_from=date_from,
                date_to=date_to,
            )
            filtered = ui.memory_filters(df)
            ui.metrics(filtered)
            st.divider()
            ui.table(filtered)


main()
