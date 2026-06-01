"""
Загрузка и подготовка данных.
Единственное место, где выполняется запрос к БД + расчёт экономики.
Все страницы Streamlit используют эти функции — кэш общий.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.config import get_settings
from wolle_economy.db.engine import get_engine
from wolle_economy.db.queries import (
    DATE_RANGE_SQL,
    MM_DATE_RANGE_SQL,
    MM_SELLERS_SQL,
    OZ_DATE_RANGE_SQL,
    OZ_SELLERS_SQL,
    SELLERS_SQL,
    SM_DATE_RANGE_SQL,
    SM_SELLERS_SQL,
    WB_DATE_RANGE_SQL,
    WB_SELLERS_SQL,
    build_mm_dbs_order_items_query,
    build_mm_poizon_order_items_query,
    build_order_items_query,
    build_oz_order_items_query,
    build_payment_aggregates_query,
    build_sm_order_items_query,
    build_supplier_price_fact_query,
    build_wb_order_items_query,
)
from wolle_economy.domain.economics import calc_economics, merge_with_payments
from wolle_economy.domain.economics_mm import calc_mm_economics
from wolle_economy.domain.economics_oz import calc_oz_economics
from wolle_economy.domain.economics_sm import calc_sm_economics
from wolle_economy.domain.economics_wb import calc_wb_economics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketplaceSpec:
    """Описание подключенного маркетплейса."""

    code: str
    title: str
    load_orders: Callable[
        [tuple[int, ...] | None, datetime.date | None, datetime.date | None], pd.DataFrame
    ]
    load_sellers: Callable[[], pd.DataFrame]
    load_date_range: Callable[[], tuple[datetime.date, datetime.date]]
    order_key: str
    ui_profile: dict[str, str]


def _fallback_date_range() -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    return today - datetime.timedelta(days=365), today


def _load_orders_for_code(
    code: str,
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    canonical_code = _normalize_marketplace_code(code)
    impl_by_code: dict[str, Callable[..., pd.DataFrame]] = {
        "ym": _load_ym_orders_impl,
        "mm": _load_mm_orders_impl,
        "sm": _load_sm_orders_impl,
        "wb": _load_wb_orders_impl,
        "oz": _load_oz_orders_impl,
    }
    return impl_by_code[canonical_code](
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Яндекс Маркет
# ═══════════════════════════════════════════════════════════════════════════


def _load_ym_orders_impl(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    logger.info(
        "Загрузка заказов YM: seller_ids=%s date_from=%s date_to=%s",
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
        logger.exception("Ошибка SQLAlchemy при загрузке данных YM из БД")
        raise

    logger.info(
        "Загружено строк YM: заказов=%d, платежей=%d, закупочных=%d",
        len(orders),
        len(payments),
        len(supplier_prices),
    )
    orders = orders.merge(supplier_prices, on="item_id", how="left")
    return calc_economics(merge_with_payments(orders, payments))


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_sellers() -> pd.DataFrame:
    """Возвращает DataFrame с колонками id, seller_name для ЯМ."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(SELLERS_SQL, conn)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_date_range() -> tuple[datetime.date, datetime.date]:
    """Возвращает (min_date, max_date) дат создания заказов ЯМ."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(DATE_RANGE_SQL).fetchone()
    if row is None or row[0] is None:
        return _fallback_date_range()
    return row[0], row[1]


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner="Загрузка данных…")
def load_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Публичный загрузчик заказов ЯМ (совместимость)."""
    return _load_orders_for_code(
        "ym",
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# ═══════════════════════════════════════════════════════════════════════════
# МегаМаркет
# ═══════════════════════════════════════════════════════════════════════════


def _load_mm_orders_impl(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    logger.info(
        "Загрузка заказов MM: seller_ids=%s date_from=%s date_to=%s",
        seller_ids,
        date_from,
        date_to,
    )
    engine = get_engine()

    dbs_sql, dbs_params = build_mm_dbs_order_items_query(seller_ids, date_from, date_to)
    poizon_sql, poizon_params = build_mm_poizon_order_items_query(
        seller_ids, date_from, date_to
    )

    try:
        with engine.connect() as conn:
            df_dbs = pd.read_sql_query(dbs_sql, conn, params=dbs_params)
            df_poizon = pd.read_sql_query(poizon_sql, conn, params=poizon_params)
    except SQLAlchemyError:
        logger.exception("Ошибка SQLAlchemy при загрузке данных MM из БД")
        raise

    logger.info(
        "Загружено строк MM: DBS=%d, Poizon=%d",
        len(df_dbs),
        len(df_poizon),
    )

    if "poizon_price" not in df_dbs.columns:
        df_dbs["poizon_price"] = np.nan

    return calc_mm_economics(pd.concat([df_dbs, df_poizon], ignore_index=True))


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_mm_sellers() -> pd.DataFrame:
    """Возвращает DataFrame с колонками id, seller_name для ММ."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(MM_SELLERS_SQL, conn)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_mm_date_range() -> tuple[datetime.date, datetime.date]:
    """Возвращает (min_date, max_date) дат создания заказов ММ."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(MM_DATE_RANGE_SQL).fetchone()
    if row is None or row[0] is None:
        return _fallback_date_range()
    return row[0], row[1]


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner="Загрузка данных МегаМаркет…")
def load_mm_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Публичный загрузчик заказов ММ (совместимость)."""
    return _load_orders_for_code(
        "mm",
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Sportmaster
# ═══════════════════════════════════════════════════════════════════════════


def _load_sm_orders_impl(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    logger.info(
        "Загрузка заказов SM: seller_ids=%s date_from=%s date_to=%s",
        seller_ids,
        date_from,
        date_to,
    )
    engine = get_engine()
    sql, params = build_sm_order_items_query(seller_ids, date_from, date_to)

    try:
        with engine.connect() as conn:
            orders = pd.read_sql_query(sql, conn, params=params)
    except SQLAlchemyError:
        logger.exception("Ошибка SQLAlchemy при загрузке данных SM из БД")
        raise

    logger.info("Загружено строк SM: %d", len(orders))
    return calc_sm_economics(orders)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_sm_sellers() -> pd.DataFrame:
    """Возвращает DataFrame с колонками id, seller_name для Sportmaster."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(SM_SELLERS_SQL, conn)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_sm_date_range() -> tuple[datetime.date, datetime.date]:
    """Возвращает (min_date, max_date) дат создания заказов SM."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(SM_DATE_RANGE_SQL).fetchone()
    if row is None or row[0] is None:
        return _fallback_date_range()
    return row[0], row[1]


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner="Загрузка данных Sportmaster…")
def load_sm_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Публичный загрузчик заказов Sportmaster."""
    return _load_orders_for_code(
        "sm",
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Wildberries
# ═══════════════════════════════════════════════════════════════════════════


def _load_wb_orders_impl(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    logger.info(
        "Загрузка заказов WB: seller_ids=%s date_from=%s date_to=%s",
        seller_ids,
        date_from,
        date_to,
    )
    engine = get_engine()
    sql, params = build_wb_order_items_query(seller_ids, date_from, date_to)

    try:
        with engine.connect() as conn:
            orders = pd.read_sql_query(sql, conn, params=params)
    except SQLAlchemyError:
        logger.exception("Ошибка SQLAlchemy при загрузке данных WB из БД")
        raise

    logger.info("Загружено строк WB: %d", len(orders))
    return calc_wb_economics(orders)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_wb_sellers() -> pd.DataFrame:
    """Возвращает DataFrame с колонками id, seller_name для Wildberries."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(WB_SELLERS_SQL, conn)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_wb_date_range() -> tuple[datetime.date, datetime.date]:
    """Возвращает (min_date, max_date) дат создания заказов WB."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(WB_DATE_RANGE_SQL).fetchone()
    if row is None or row[0] is None:
        return _fallback_date_range()
    return row[0], row[1]


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner="Загрузка данных Wildberries…")
def load_wb_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Публичный загрузчик заказов Wildberries."""
    return _load_orders_for_code(
        "wb",
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Ozon
# ═══════════════════════════════════════════════════════════════════════════


def _load_oz_orders_impl(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    logger.info(
        "Загрузка заказов OZ: seller_ids=%s date_from=%s date_to=%s",
        seller_ids,
        date_from,
        date_to,
    )
    engine = get_engine()
    sql, params = build_oz_order_items_query(seller_ids, date_from, date_to)

    try:
        with engine.connect() as conn:
            orders = pd.read_sql_query(sql, conn, params=params)
    except SQLAlchemyError:
        logger.exception("Ошибка SQLAlchemy при загрузке данных OZ из БД")
        raise

    logger.info("Загружено строк OZ: %d", len(orders))
    return calc_oz_economics(orders)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_oz_sellers() -> pd.DataFrame:
    """Возвращает DataFrame с колонками id, seller_name для Ozon."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(OZ_SELLERS_SQL, conn)


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner=False)
def load_oz_date_range() -> tuple[datetime.date, datetime.date]:
    """Возвращает (min_date, max_date) дат создания заказов Ozon."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(OZ_DATE_RANGE_SQL).fetchone()
    if row is None or row[0] is None:
        return _fallback_date_range()
    return row[0], row[1]


@st.cache_data(ttl=get_settings().cache_ttl, show_spinner="Загрузка данных Ozon…")
def load_oz_orders(
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Публичный загрузчик заказов Ozon."""
    return _load_orders_for_code(
        "oz",
        seller_ids=seller_ids,
        date_from=date_from,
        date_to=date_to,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Реестр маркетплейсов
# ═══════════════════════════════════════════════════════════════════════════


MARKETPLACE_SPECS: tuple[MarketplaceSpec, ...] = (
    MarketplaceSpec(
        code="ym",
        title="Яндекс Маркет",
        load_orders=load_orders,
        load_sellers=load_sellers,
        load_date_range=load_date_range,
        order_key="ya_order_id",
        ui_profile={"filters_key": "ym", "table": "ym", "analytics": "ym"},
    ),
    MarketplaceSpec(
        code="mm",
        title="МегаМаркет",
        load_orders=load_mm_orders,
        load_sellers=load_mm_sellers,
        load_date_range=load_mm_date_range,
        order_key="mm_order_id",
        ui_profile={"filters_key": "mm", "table": "mm", "analytics": "mm"},
    ),
    MarketplaceSpec(
        code="sm",
        title="Sportmaster",
        load_orders=load_sm_orders,
        load_sellers=load_sm_sellers,
        load_date_range=load_sm_date_range,
        order_key="sm_order_id",
        ui_profile={"filters_key": "sm", "table": "sm", "analytics": "sm"},
    ),
    MarketplaceSpec(
        code="wb",
        title="Wildberries",
        load_orders=load_wb_orders,
        load_sellers=load_wb_sellers,
        load_date_range=load_wb_date_range,
        order_key="wb_order_id",
        ui_profile={"filters_key": "wb", "table": "wb", "analytics": "wb"},
    ),
    MarketplaceSpec(
        code="oz",
        title="Ozon",
        load_orders=load_oz_orders,
        load_sellers=load_oz_sellers,
        load_date_range=load_oz_date_range,
        order_key="oz_order_id",
        ui_profile={"filters_key": "oz", "table": "oz", "analytics": "oz"},
    ),
)

_MARKETPLACE_ALIASES: dict[str, str] = {
    "ym": "ym",
    "yandex": "ym",
    "яндекс": "ym",
    "mm": "mm",
    "megamarket": "mm",
    "мегамаркет": "mm",
    "sm": "sm",
    "sportmaster": "sm",
    "спортмастер": "sm",
    "wb": "wb",
    "wildberries": "wb",
    "вайлдберриз": "wb",
    "oz": "oz",
    "ozon": "oz",
    "озон": "oz",
}


def _normalize_marketplace_code(code: str) -> str:
    return _MARKETPLACE_ALIASES.get(code.strip().lower(), code.strip().lower())


def get_marketplace_specs() -> tuple[MarketplaceSpec, ...]:
    """Возвращает все подключённые маркетплейсы."""
    return MARKETPLACE_SPECS


def get_marketplace_spec(code: str) -> MarketplaceSpec:
    """Возвращает spec маркетплейса по коду."""
    canonical_code = _normalize_marketplace_code(code)
    for spec in MARKETPLACE_SPECS:
        if spec.code == canonical_code:
            return spec
    raise KeyError(f"Unknown marketplace code: {code}")


def load_orders_by_marketplace(
    code: str,
    seller_ids: tuple[int, ...] | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> pd.DataFrame:
    """Универсальный загрузчик заказов через реестр маркетплейсов."""
    spec = get_marketplace_spec(code)
    return spec.load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)
