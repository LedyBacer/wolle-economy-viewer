import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.domain.loader import load_orders
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.orders.filters import (
    sidebar_db_filters,
    sidebar_memory_filters,
)
from wolle_economy.ui.components.orders.metrics import show_metrics
from wolle_economy.ui.components.orders.table import show_table
from wolle_economy.ui.helpers import show_data_quality_warning, show_load_error

setup_logging()
logger = logging.getLogger(__name__)

def main() -> None:
    st.title("Заказы")
    st.caption("Позиции заказов с расчётом юнит-экономики. Используйте фильтры в боковой панели.")

    # Шаг 1: DB-фильтры (продавец, дата) — рендерятся до загрузки данных
    seller_ids, date_from, date_to = sidebar_db_filters()

    # Шаг 2: Загрузка данных с фильтрацией на стороне БД
    try:
        df = load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)
    except SQLAlchemyError as e:
        show_load_error(
            title="Не удалось загрузить данные из базы данных.",
            exc=e,
            details="Проверьте `.env`/переменные окружения и доступность PostgreSQL.",
        )
        st.stop()
        return
    except (ValueError, KeyError, TypeError) as e:
        show_load_error(
            title="Данные из БД имеют неожиданный формат.",
            exc=e,
            details="Проверьте актуальность схемы/запросов и наличие нужных колонок.",
        )
        st.stop()
        return

    # Шаг 3: In-memory фильтры (статусы, текстовый поиск)
    filtered = sidebar_memory_filters(df)

    show_data_quality_warning(filtered)
    show_metrics(filtered)
    st.divider()
    show_table(filtered)


main()
