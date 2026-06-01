import datetime

import pandas as pd

from wolle_economy.domain.loader import load_oz_date_range, load_oz_sellers
from wolle_economy.ui.components.orders.filters import (
    sidebar_db_filters_for,
    sidebar_memory_filters_for,
)


def sidebar_oz_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """DB-фильтры для Ozon."""
    return sidebar_db_filters_for(
        load_sellers_fn=load_oz_sellers,
        load_date_range_fn=load_oz_date_range,
        header="Фильтры Ozon",
        seller_label="Магазин (Ozon)",
        date_label="Дата создания (Ozon)",
        key_prefix="oz",
    )


def sidebar_oz_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """In-memory фильтры для Ozon."""
    return sidebar_memory_filters_for(
        df,
        key_prefix="oz",
        status_label="Статус заказа (Ozon)",
        offer_label="Offer ID (содержит)",
        supplier_label="Поставщик (содержит)",
    )
