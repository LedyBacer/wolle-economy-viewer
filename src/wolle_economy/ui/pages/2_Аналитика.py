"""Аналитика юнит-экономики: KPI-дашборд, ABC-анализ, возвраты, поставщики,
ценообразование, денежный поток, операционные метрики и тренды.
"""

import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.domain.loader import load_orders
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.analytics.filters import (
    apply_memory_filters,
    sidebar_db_filters,
)
from wolle_economy.ui.components.analytics.render import render_analytics_tabs
from wolle_economy.ui.helpers import show_load_error

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    st.title("Аналитика юнит-экономики")
    st.caption(
        "Все денежные показатели в рублях. Магазины без отчёта о марже Маркета по умолчанию исключены — переключите фильтр в боковой панели, чтобы включить их в выборку."
    )

    # Шаг 1: DB-фильтры (продавец, дата)
    seller_ids, date_from, date_to, exclude_low_quality = sidebar_db_filters()

    # Шаг 2: Загрузка с фильтрацией на стороне БД
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

    # Шаг 3: In-memory фильтр (low-quality sellers)
    filtered = apply_memory_filters(df, exclude_low_quality)

    if filtered.empty:
        st.warning("Нет данных по выбранным фильтрам.")
        st.stop()
        return

    render_analytics_tabs(filtered)


main()
