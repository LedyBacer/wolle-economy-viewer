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
from wolle_economy.ui.components.orders.metrics import show_metrics
from wolle_economy.ui.components.orders.table import show_table
from wolle_economy.ui.helpers import safe_load_orders, show_data_quality_warning

setup_logging()
logger = logging.getLogger(__name__)

def main() -> None:
    st.title("Заказы")
    st.caption("Позиции заказов с расчётом юнит-экономики. Используйте фильтры в боковой панели.")

    # Шаг 1: DB-фильтры (продавец, дата) — рендерятся до загрузки данных
    seller_ids, date_from, date_to = sidebar_db_filters()

    # Шаг 2: Загрузка данных с фильтрацией на стороне БД
    df = safe_load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)

    # Шаг 3: In-memory фильтры (статусы, текстовый поиск)
    filtered = sidebar_memory_filters(df)

    show_data_quality_warning(filtered)
    show_metrics(filtered)
    st.divider()
    show_table(filtered)


main()
