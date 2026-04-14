import logging

import streamlit as st

st.set_page_config(
    page_title="Wolle — Заказы",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.orders.filters import (
    sidebar_db_filters,
    sidebar_memory_filters,
)
from wolle_economy.ui.components.orders.filters_mm import (
    sidebar_mm_db_filters,
    sidebar_mm_memory_filters,
)
from wolle_economy.ui.components.orders.metrics import show_metrics
from wolle_economy.ui.components.orders.metrics_mm import show_mm_metrics
from wolle_economy.ui.components.orders.table import show_table
from wolle_economy.ui.components.orders.table_mm import show_mm_table
from wolle_economy.ui.helpers import safe_load_mm_orders, safe_load_orders

setup_logging()
logger = logging.getLogger(__name__)

def main() -> None:
    st.title("Заказы")
    st.caption("Позиции заказов с расчётом юнит-экономики. Используйте фильтры в боковой панели.")

    tab_ym, tab_mm = st.tabs(["Яндекс Маркет", "МегаМаркет"])

    with tab_ym:
        seller_ids, date_from, date_to = sidebar_db_filters()
        df = safe_load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)
        filtered = sidebar_memory_filters(df)

        show_metrics(filtered)
        st.divider()
        show_table(filtered)

    with tab_mm:
        mm_seller_ids, mm_date_from, mm_date_to = sidebar_mm_db_filters()
        mm_df = safe_load_mm_orders(
            seller_ids=mm_seller_ids, date_from=mm_date_from, date_to=mm_date_to
        )
        mm_filtered = sidebar_mm_memory_filters(mm_df)

        show_mm_metrics(mm_filtered)
        st.divider()
        show_mm_table(mm_filtered)


main()
