import datetime

import pandas as pd
import streamlit as st

from wolle_economy.config import get_settings
from wolle_economy.domain.loader import load_date_range, load_sellers


def sidebar_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date, bool]:
    """
    Рендерит фильтры по продавцу и периоду.

    Возвращает параметры для DB-запроса и флаг для in-memory фильтрации:
    (seller_ids, date_from, date_to, exclude_low_quality).
    """
    sellers_df = load_sellers()
    min_date, max_date = load_date_range()

    with st.sidebar:
        st.header("Фильтры")

        all_names = sellers_df["seller_name"].tolist()
        sel_names = st.multiselect("Магазин", all_names, default=all_names)

        date_range = st.date_input(
            "Период (дата заказа)",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

        exclude_low_quality = st.checkbox(
            "Исключить магазины без margin_report",
            value=True,
            help="WolleBuy — для него нет точных данных о выручке/комиссиях",
        )

    if set(sel_names) == set(all_names):
        seller_ids = None
    else:
        id_map = sellers_df.set_index("seller_name")["id"]
        seller_ids = tuple(int(id_map[n]) for n in sel_names if n in id_map)

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        date_from, date_to = date_range[0], date_range[1]
    else:
        date_from, date_to = min_date, max_date

    return seller_ids, date_from, date_to, exclude_low_quality


def apply_memory_filters(df: pd.DataFrame, exclude_low_quality: bool) -> pd.DataFrame:
    """In-memory фильтр, применяемый после загрузки данных из БД."""
    if exclude_low_quality:
        return df[~df["seller_name"].isin(get_settings().low_quality_sellers)]
    return df

