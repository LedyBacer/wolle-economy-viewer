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

from wolle_economy.domain.loader import (
    MarketplaceSpec,
    get_marketplace_spec,
)

logger = logging.getLogger(__name__)


def orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Возвращает DataFrame с одной строкой на заказ (совместимость по ya_order_id)."""
    return df.drop_duplicates(subset="ya_order_id")


def orders_dedup_by_key(df: pd.DataFrame, order_key: str) -> pd.DataFrame:
    """Возвращает DataFrame с одной строкой на заказ по заданному order key."""
    return df.drop_duplicates(subset=order_key)


def dedup_for_marketplace(df: pd.DataFrame, spec: MarketplaceSpec) -> pd.DataFrame:
    """Дедуп по ключу заказа из marketplace spec."""
    return orders_dedup_by_key(df, spec.order_key)


def show_load_error(
    *,
    title: str,
    exc: Exception,
    details: str | None = None,
) -> None:
    """Единый формат сообщения об ошибке загрузки данных в UI."""
    logger.exception("%s: %s", title, exc)
    st.error(title)
    if details:
        st.caption(details)


def _stop() -> NoReturn:
    st.stop()
    raise RuntimeError("unreachable")


def safe_load_marketplace_orders(
    spec: MarketplaceSpec,
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Универсальная безопасная загрузка заказов маркетплейса."""
    kwargs: dict = {}
    if seller_ids is not None:
        kwargs["seller_ids"] = seller_ids
    if date_from is not None:
        kwargs["date_from"] = date_from
    if date_to is not None:
        kwargs["date_to"] = date_to

    try:
        return spec.load_orders(**kwargs)
    except SQLAlchemyError as e:
        show_load_error(
            title=f"Не удалось загрузить данные {spec.title} из базы данных.",
            exc=e,
            details="Проверьте `.env`/переменные окружения и доступность PostgreSQL.",
        )
        _stop()
    except (ValueError, KeyError, TypeError) as e:
        show_load_error(
            title=f"Данные {spec.title} из БД имеют неожиданный формат.",
            exc=e,
            details="Проверьте актуальность схемы/запросов и наличие нужных колонок.",
        )
        _stop()


def safe_load_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Safe loader Яндекс Маркет (совместимость)."""
    return safe_load_marketplace_orders(
        get_marketplace_spec("ym"),
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


def mm_orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Дедуп заказов ММ (совместимость)."""
    return orders_dedup_by_key(df, "mm_order_id")


def safe_load_mm_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Safe loader МегаМаркет (совместимость)."""
    return safe_load_marketplace_orders(
        get_marketplace_spec("mm"),
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


def sm_orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Дедуп заказов Sportmaster."""
    return orders_dedup_by_key(df, "sm_order_id")


def safe_load_sm_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Safe loader Sportmaster."""
    return safe_load_marketplace_orders(
        get_marketplace_spec("sm"),
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


def wb_orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Дедуп заказов Wildberries."""
    return orders_dedup_by_key(df, "wb_order_id")


def safe_load_wb_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Safe loader Wildberries."""
    return safe_load_marketplace_orders(
        get_marketplace_spec("wb"),
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# Явные re-export для обратной совместимости импортов в других модулях.
__all__ = [
    "dedup_for_marketplace",
    "mm_orders_dedup",
    "orders_dedup",
    "orders_dedup_by_key",
    "safe_load_marketplace_orders",
    "safe_load_mm_orders",
    "safe_load_orders",
    "safe_load_sm_orders",
    "safe_load_wb_orders",
    "sm_orders_dedup",
    "wb_orders_dedup",
]
