import datetime

import streamlit as st

from wolle_economy.domain.loader import load_date_range, load_sellers


def sidebar_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """
    Рендерит фильтры по продавцу и периоду.

    Возвращает параметры для DB-запроса: (seller_ids, date_from, date_to).
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

