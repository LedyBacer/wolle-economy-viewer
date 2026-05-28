import datetime

import pandas as pd
import streamlit as st

from wolle_economy.domain.loader import load_date_range, load_sellers


def sidebar_db_filters_for(
    *,
    load_sellers_fn,
    load_date_range_fn,
    header: str,
    seller_label: str,
    date_label: str,
    key_prefix: str,
) -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """Универсальные DB-фильтры по продавцам и датам."""
    sellers_df = load_sellers_fn()
    min_date, max_date = load_date_range_fn()

    with st.sidebar:
        st.header(header)
        all_names = sellers_df["seller_name"].tolist()
        sel_names = st.multiselect(
            seller_label,
            all_names,
            default=all_names,
            key=f"{key_prefix}_seller",
        )
        date_range = st.date_input(
            date_label,
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key=f"{key_prefix}_date_range",
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


def sidebar_memory_filters_for(
    df: pd.DataFrame,
    *,
    key_prefix: str,
    status_label: str,
    offer_label: str,
    supplier_label: str | None = None,
    include_channel: bool = False,
) -> pd.DataFrame:
    """Универсальные in-memory фильтры по статусам и поиску."""
    with st.sidebar:
        statuses = sorted(df["fulfillment_status"].dropna().unique())
        sel_statuses = st.multiselect(
            status_label,
            statuses,
            default=statuses,
            key=f"{key_prefix}_status",
        )

        pay_statuses = sorted(df["payment_status"].dropna().unique())
        sel_pay = st.multiselect(
            "Статус платежа",
            pay_statuses,
            default=pay_statuses,
            key=f"{key_prefix}_pay",
        )

        if include_channel and "channel" in df.columns:
            channels = sorted(df["channel"].dropna().unique())
            sel_channels = st.multiselect(
                "Канал",
                channels,
                default=channels,
                key=f"{key_prefix}_channel",
            )
        else:
            sel_channels = None

        offer_q = st.text_input(offer_label, key=f"{key_prefix}_offer")
        supplier_q = (
            st.text_input(supplier_label, key=f"{key_prefix}_supplier")
            if supplier_label and "supplier_name" in df.columns
            else ""
        )

    mask = df["fulfillment_status"].isin(sel_statuses) & df["payment_status"].isin(sel_pay)
    if sel_channels is not None:
        mask &= df["channel"].isin(sel_channels)
    if offer_q:
        mask &= df["offer_id"].str.contains(offer_q, case=False, na=False)
    if supplier_q:
        mask &= df["supplier_name"].str.contains(supplier_q, case=False, na=False)

    return df[mask].copy()


def sidebar_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """Фильтры Яндекс Маркет (backward compatibility)."""
    return sidebar_db_filters_for(
        load_sellers_fn=load_sellers,
        load_date_range_fn=load_date_range,
        header="Фильтры",
        seller_label="Магазин",
        date_label="Дата создания",
        key_prefix="ym",
    )


def sidebar_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """In-memory фильтры Яндекс Маркет (backward compatibility)."""
    return sidebar_memory_filters_for(
        df,
        key_prefix="ym",
        status_label="Статус заказа",
        offer_label="Offer ID (содержит)",
        supplier_label="Поставщик (содержит)",
    )
