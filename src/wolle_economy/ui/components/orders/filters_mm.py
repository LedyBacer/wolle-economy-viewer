import datetime

import pandas as pd
import streamlit as st

from wolle_economy.domain.loader import load_mm_date_range, load_mm_sellers


def sidebar_mm_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """
    Рендерит фильтры по продавцу и дате в боковой панели для ММ.
    Возвращает параметры для DB-запроса: (seller_ids, date_from, date_to).
    """
    sellers_df = load_mm_sellers()
    min_date, max_date = load_mm_date_range()

    with st.sidebar:
        st.header("Фильтры МегаМаркет")

        all_names = sellers_df["seller_name"].tolist()
        sel_names = st.multiselect("Магазин (ММ)", all_names, default=all_names, key="mm_seller")

        date_range = st.date_input(
            "Дата создания (ММ)",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="mm_date_range",
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

    return seller_ids, date_from, date_to


def sidebar_mm_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    In-memory фильтры для ММ-заказов (статусы, канал, поиск).
    """
    with st.sidebar:
        statuses = sorted(df["fulfillment_status"].dropna().unique())
        sel_statuses = st.multiselect(
            "Статус заказа (ММ)", statuses, default=statuses, key="mm_status"
        )

        channels = sorted(df["channel"].dropna().unique())
        sel_channels = st.multiselect(
            "Канал", channels, default=channels, key="mm_channel"
        )

        offer_q = st.text_input("Offer ID (содержит)", key="mm_offer")

    mask = df["fulfillment_status"].isin(sel_statuses) & df["channel"].isin(sel_channels)
    if offer_q:
        mask &= df["offer_id"].str.contains(offer_q, case=False, na=False)

    return df[mask].copy()
