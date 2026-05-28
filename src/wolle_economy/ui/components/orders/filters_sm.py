import datetime

import pandas as pd

from wolle_economy.domain.loader import load_sm_date_range, load_sm_sellers
from wolle_economy.ui.components.orders.filters import (
    sidebar_db_filters_for,
    sidebar_memory_filters_for,
)


def sidebar_sm_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """DB-фильтры для Sportmaster."""
    return sidebar_db_filters_for(
        load_sellers_fn=load_sm_sellers,
        load_date_range_fn=load_sm_date_range,
        header="Фильтры Sportmaster",
        seller_label="Магазин (SM)",
        date_label="Дата создания (SM)",
        key_prefix="sm",
    )


def sidebar_sm_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """In-memory фильтры для Sportmaster."""
    return sidebar_memory_filters_for(
        df,
        key_prefix="sm",
        status_label="Статус заказа (SM)",
        offer_label="Offer ID (содержит)",
        supplier_label="Поставщик (содержит)",
    )
