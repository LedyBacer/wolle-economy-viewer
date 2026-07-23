"""Получение и сериализация одной строки экономики заказа."""

from __future__ import annotations

import datetime
import logging
import math
from decimal import Decimal
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from wolle_economy.db.engine import get_engine
from wolle_economy.db.queries import PLATFORM_SELLER_SQL
from wolle_economy.ui.columns import ALL_COLUMNS_BY_MARKETPLACE

_MARKETPLACE_BY_PLATFORM_ID: dict[int, str] = {
    1: "ym",
    2: "oz",
    3: "wb",
    4: "sm",
    5: "mm",
}


class SellerNotFoundError(LookupError):
    """Магазин с указанным ID отсутствует."""


class UnsupportedMarketplaceError(LookupError):
    """Магазин относится к ещё не поддержанному маркетплейсу."""


class OrderEconomicsNotFoundError(LookupError):
    """Позиция заказа не найдена."""


class AmbiguousOrderEconomicsError(RuntimeError):
    """По точному ключу найдено больше одной строки."""


def load_order_economics_data(
    code: str,
    *,
    seller_id: int,
    order_id: str,
    offer_id: str,
) -> pd.DataFrame:
    """Лениво импортирует общий loader, чтобы API стартовал без Streamlit runtime."""
    import streamlit

    _ = streamlit
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
    from wolle_economy.domain.loader import load_order_economics_data as load_data

    return load_data(
        code,
        seller_id=seller_id,
        order_id=order_id,
        offer_id=offer_id,
    )


def resolve_marketplace_code(seller_id: int) -> str:
    """Определяет код маркетплейса по записи platform_sellers."""
    with get_engine().connect() as conn:
        seller = conn.execute(
            PLATFORM_SELLER_SQL,
            {"seller_id": seller_id},
        ).mappings().one_or_none()

    if seller is None:
        raise SellerNotFoundError(f"Магазин seller_id={seller_id} не найден")

    platform_id = int(seller["platform_for_sell_id"])
    try:
        return _MARKETPLACE_BY_PLATFORM_ID[platform_id]
    except KeyError as exc:
        raise UnsupportedMarketplaceError(
            f"Маркетплейс магазина seller_id={seller_id} пока не поддерживается"
        ) from exc


def _json_value(value: Any) -> Any:
    """Приводит scalar pandas/numpy/Decimal к стандартному JSON-типу."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, Decimal):
        value = float(value)

    if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass

    return value


def serialize_order_row(row: pd.Series, marketplace_code: str) -> dict[str, Any]:
    """Возвращает только колонки режима «Показать все колонки»."""
    columns = ALL_COLUMNS_BY_MARKETPLACE[marketplace_code]
    return {column: _json_value(row[column]) for column in columns if column in row.index}


def get_order_economics(
    *,
    seller_id: int,
    order_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Возвращает единственную строку экономики по точному составному ключу."""
    marketplace_code = resolve_marketplace_code(seller_id)
    return fetch_order_economics(
        marketplace_code=marketplace_code,
        seller_id=seller_id,
        order_id=order_id,
        offer_id=offer_id,
    )


def fetch_order_economics(
    *,
    marketplace_code: str,
    seller_id: int,
    order_id: str,
    offer_id: str,
) -> dict[str, Any]:
    """Точечно читает актуальную строку известного маркетплейса из БД."""
    rows = load_order_economics_data(
        marketplace_code,
        seller_id=seller_id,
        order_id=order_id,
        offer_id=offer_id,
    )

    if rows.empty:
        raise OrderEconomicsNotFoundError(
            "Строка экономики с указанными seller_id, order_id и offer_id не найдена"
        )
    if len(rows.index) > 1:
        raise AmbiguousOrderEconomicsError(
            "По указанным seller_id, order_id и offer_id найдено несколько строк"
        )

    return serialize_order_row(rows.iloc[0], marketplace_code)
