"""
Wolle — Юнит-экономика Яндекс Маркет.
Точка входа Streamlit. Содержит обзорный дашборд с ключевыми показателями
и навигацией к детальным разделам.
"""

import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.config import get_settings
from wolle_economy.domain.loader import load_orders
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.components.home.kpis import render_kpis
from wolle_economy.ui.components.home.navigation import render_navigation
from wolle_economy.ui.components.home.trend import render_trend
from wolle_economy.ui.helpers import show_load_error

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    st.title("Wolle — юнит-экономика Яндекс Маркет")
    st.caption("Сводный обзор по магазинам с полной отчётностью маржи Маркета.")

    try:
        df = load_orders()
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

    df_clean = df[~df["seller_name"].isin(get_settings().low_quality_sellers)]
    if df_clean.empty:
        df_clean = df

    render_kpis(df_clean)
    st.divider()
    render_trend(df_clean)
    st.divider()
    render_navigation()


main()
