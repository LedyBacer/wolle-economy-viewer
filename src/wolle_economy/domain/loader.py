"""
Загрузка и подготовка данных.
Единственное место, где выполняется запрос к БД + расчёт экономики.
Все страницы Streamlit используют эти функции — кэш общий.
"""

from __future__ import annotations

import datetime
import logging

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.config import get_settings
from wolle_economy.db.engine import get_engine
from wolle_economy.db.queries import (
    DATE_RANGE_SQL,
    SELLERS_SQL,
    build_order_items_query,
    build_payment_aggregates_query,
    build_supplier_price_fact_query,
)
from wolle_economy.domain.economics import calc_economics, merge_with_payments

logger = logging.getLogger(__name__)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_sellers() -> pd.DataFrame:
    """Возвращает DataFrame с колонками id, seller_name."""
    logger.debug("Загрузка списка продавцов из БД")
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(SELLERS_SQL, conn)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_date_range() -> tuple[datetime.date, datetime.date]:
    """
    Возвращает (min_date, max_date) дат создания заказов.
    Используется для инициализации date picker в боковой панели.
    """
    logger.debug("Загрузка диапазона дат из БД")
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(DATE_RANGE_SQL).fetchone()
    if row is None or row[0] is None:
        today = datetime.date.today()
        return today - datetime.timedelta(days=365), today
    return row[0], row[1]


@st.cache_data(
    ttl=get_settings().cache_ttl,
    show_spinner="Загрузка данных…",
)
def load_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """
    Загружает позиции заказов из БД, объединяет с агрегатами платежей
    и возвращает DataFrame со всеми расчётными финансовыми метриками.

    Параметры передаются как bind-параметры в SQL — фильтрация на стороне БД
    снижает объём передаваемых данных.

    Args:
        seller_ids: кортеж ID продавцов; None — все продавцы.
        date_from:  нижняя граница даты заказа; None — без ограничения.
        date_to:    верхняя граница даты заказа (включительно); None — без ограничения.
    """
    logger.info(
        "Загрузка заказов: seller_ids=%s date_from=%s date_to=%s",
        seller_ids,
        date_from,
        date_to,
    )
    engine = get_engine()
    orders_sql, orders_params = build_order_items_query(seller_ids, date_from, date_to)
    payments_sql, payments_params = build_payment_aggregates_query(seller_ids, date_from, date_to)
    supplier_sql, supplier_params = build_supplier_price_fact_query(
        seller_ids, date_from, date_to
    )

    try:
        with engine.connect() as conn:
            orders = pd.read_sql_query(orders_sql, conn, params=orders_params)
            payments = pd.read_sql_query(payments_sql, conn, params=payments_params)
            supplier_prices = pd.read_sql_query(supplier_sql, conn, params=supplier_params)
    except SQLAlchemyError:
        logger.exception("Ошибка SQLAlchemy при загрузке данных из БД")
        raise

    logger.info(
        "Загружено строк заказов: %d, платежей: %d, фактических закупочных цен: %d",
        len(orders),
        len(payments),
        len(supplier_prices),
    )
    # Фактическая закупочная цена per item; в economics.py делается fallback
    # на плановый base_price, если значение отсутствует или равно 0.
    orders = orders.merge(supplier_prices, on="item_id", how="left")
    df = merge_with_payments(orders, payments)
    return calc_economics(df)
