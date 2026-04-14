"""
Общие UI-хелперы: дедупликация DataFrame по заказу, загрузка данных с обработкой ошибок.
"""

from __future__ import annotations

import datetime
import logging
from typing import NoReturn

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.domain.loader import load_mm_orders, load_orders

logger = logging.getLogger(__name__)


def orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """
    Возвращает DataFrame с одной строкой на заказ.
    Нужен для корректной агрегации полей уровня заказа
    (sell_price, market_services, expected_payout), которые дублируются
    для каждой позиции заказа.
    """
    return df.drop_duplicates(subset="ya_order_id")



def show_load_error(
    *,
    title: str,
    exc: Exception,
    details: str | None = None,
) -> None:
    """
    Единый формат сообщения об ошибке загрузки данных в UI.
    Детали логируются, пользователю показывается короткий текст.
    """
    logger.exception("%s: %s", title, exc)
    st.error(title)
    if details:
        st.caption(details)


def safe_load_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Загружает данные заказов с единым обработчиком ошибок.

    При ошибке показывает сообщение в UI и вызывает st.stop().
    """
    kwargs: dict = {}
    if seller_ids is not None:
        kwargs["seller_ids"] = seller_ids
    if date_from is not None:
        kwargs["date_from"] = date_from
    if date_to is not None:
        kwargs["date_to"] = date_to

    try:
        return load_orders(**kwargs)
    except SQLAlchemyError as e:
        show_load_error(
            title="Не удалось загрузить данные из базы данных.",
            exc=e,
            details="Проверьте `.env`/переменные окружения и доступность PostgreSQL.",
        )
        st.stop()
    except (ValueError, KeyError, TypeError) as e:
        show_load_error(
            title="Данные из БД имеют неожиданный формат.",
            exc=e,
            details="Проверьте актуальность схемы/запросов и наличие нужных колонок.",
        )
        st.stop()


# ═══════════════════════════════════════════════════════════════════════════
# МегаМаркет
# ═══════════════════════════════════════════════════════════════════════════


def mm_orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """
    Возвращает DataFrame с одной строкой на заказ ММ.
    sell_price, market_services, expected_payout — order-level,
    дублируются в каждой позиции.
    """
    return df.drop_duplicates(subset="mm_order_id")


def safe_load_mm_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Загружает данные заказов ММ с единым обработчиком ошибок."""
    kwargs: dict = {}
    if seller_ids is not None:
        kwargs["seller_ids"] = seller_ids
    if date_from is not None:
        kwargs["date_from"] = date_from
    if date_to is not None:
        kwargs["date_to"] = date_to

    try:
        return load_mm_orders(**kwargs)
    except SQLAlchemyError as e:
        show_load_error(
            title="Не удалось загрузить данные МегаМаркет из базы данных.",
            exc=e,
            details="Проверьте `.env`/переменные окружения и доступность PostgreSQL.",
        )
        st.stop()
    except (ValueError, KeyError, TypeError) as e:
        show_load_error(
            title="Данные МегаМаркет из БД имеют неожиданный формат.",
            exc=e,
            details="Проверьте актуальность схемы/запросов и наличие нужных колонок.",
        )
        st.stop()
