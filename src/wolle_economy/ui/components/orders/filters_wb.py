import datetime

import pandas as pd

from wolle_economy.domain.loader import load_wb_date_range, load_wb_sellers
from wolle_economy.ui.components.orders.filters import (
    sidebar_db_filters_for,
    sidebar_memory_filters_for,
)


def sidebar_wb_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """DB-фильтры для Wildberries."""
    return sidebar_db_filters_for(
        load_sellers_fn=load_wb_sellers,
        load_date_range_fn=load_wb_date_range,
        header="Фильтры Wildberries",
        seller_label="Магазин (WB)",
        date_label="Дата создания (WB)",
        key_prefix="wb",
    )


def sidebar_wb_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """In-memory фильтры для Wildberries."""
    return sidebar_memory_filters_for(
        df,
        key_prefix="wb",
        status_label="Статус заказа (WB)",
        offer_label="Offer ID (содержит)",
        supplier_label="Поставщик (содержит)",
    )
