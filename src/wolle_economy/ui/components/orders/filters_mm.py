import datetime

import pandas as pd

from wolle_economy.domain.loader import load_mm_date_range, load_mm_sellers
from wolle_economy.ui.components.orders.filters import (
    sidebar_db_filters_for,
    sidebar_memory_filters_for,
)


def sidebar_mm_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """DB-фильтры для МегаМаркет."""
    return sidebar_db_filters_for(
        load_sellers_fn=load_mm_sellers,
        load_date_range_fn=load_mm_date_range,
        header="Фильтры МегаМаркет",
        seller_label="Магазин (ММ)",
        date_label="Дата создания (ММ)",
        key_prefix="mm",
    )


def sidebar_mm_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """In-memory фильтры для МегаМаркет."""
    return sidebar_memory_filters_for(
        df,
        key_prefix="mm",
        status_label="Статус заказа (ММ)",
        offer_label="Offer ID (содержит)",
        include_channel=True,
    )
