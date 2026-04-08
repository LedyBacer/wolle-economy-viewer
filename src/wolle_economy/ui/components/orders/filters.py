import datetime

import pandas as pd
import streamlit as st

from wolle_economy.domain.loader import load_date_range, load_sellers


def sidebar_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """
    Рендерит фильтры по продавцу и дате в боковой панели.
    Возвращает параметры для DB-запроса: (seller_ids, date_from, date_to).
    """
    sellers_df = load_sellers()
    min_date, max_date = load_date_range()

    with st.sidebar:
        st.header("Фильтры")

        all_names = sellers_df["seller_name"].tolist()
        sel_names = st.multiselect("Магазин", all_names, default=all_names)

        date_range = st.date_input(
            "Дата создания",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

    # Маппинг имён → ID для DB-запроса
    if set(sel_names) == set(all_names):
        seller_ids = None  # все продавцы — без фильтра
    else:
        id_map = sellers_df.set_index("seller_name")["id"]
        seller_ids = tuple(int(id_map[n]) for n in sel_names if n in id_map)

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        date_from, date_to = date_range[0], date_range[1]
    else:
        date_from, date_to = min_date, max_date

    return seller_ids, date_from, date_to


def sidebar_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Дополнительные in-memory фильтры (статусы, поиск по тексту).
    Должны применяться ПОСЛЕ загрузки данных из БД.
    """
    with st.sidebar:
        statuses = sorted(df["fulfillment_status"].dropna().unique())
        sel_statuses = st.multiselect("Статус заказа", statuses, default=statuses)

        pay_statuses = sorted(df["payment_status"].dropna().unique())
        sel_pay = st.multiselect("Статус платежа", pay_statuses, default=pay_statuses)

        offer_q = st.text_input("Offer ID (содержит)")
        supplier_q = st.text_input("Поставщик (содержит)")

    mask = df["fulfillment_status"].isin(sel_statuses) & df["payment_status"].isin(sel_pay)
    if offer_q:
        mask &= df["offer_id"].str.contains(offer_q, case=False, na=False)
    if supplier_q:
        mask &= df["supplier_name"].str.contains(supplier_q, case=False, na=False)

    return df[mask].copy()

