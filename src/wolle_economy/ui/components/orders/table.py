import hashlib
import io

import pandas as pd
import streamlit as st

from wolle_economy.ui.columns import COLUMN_LABELS, DISPLAY_COLUMNS

# Технические колонки — скрыты по умолчанию
TECHNICAL_COLUMNS = {
    "bonus_points",
    "calc_commissions",
    "fact_commissions",
    "income_after_fees",
    "income_after_fees_promo",
    "profit_no_promo",
    "profit_vs_expected",
    "diff_from_min_price",
    "payout_if_paid",
    "fulfillment_status",
    "supplier_name",
    "offer_id",
}

MAIN_COLUMNS = [c for c in DISPLAY_COLUMNS if c not in TECHNICAL_COLUMNS]

# Конфигурация колонок таблицы: вычисляется один раз при загрузке модуля
_MONEY_FMT = "%.2f ₽"
_PCT_FMT = "%.1f %%"
_COLUMN_CONFIG: dict = {}
for _col, _label in COLUMN_LABELS.items():
    if _col in {"created_at"}:
        _COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")
    elif _col in {"shipment_date", "last_payment_date"}:
        _COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY")
    elif _col in {"margin_plan_pct", "margin_fact_pct"}:
        _COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_PCT_FMT)
    elif _col in {
        "base_price_total",
        "ff_fee_total",
        "socket_adapter_total",
        "price_with_margin",
        "our_margin",
        "min_sell_price_total",
        "expected_profit",
        "sell_price",
        "bonus_points",
        "promo_discounts",
        "diff_from_min_price",
        "calc_commissions",
        "market_services",
        "fact_commissions",
        "income_after_fees",
        "profit",
        "profit_vs_expected",
        "income_after_fees_promo",
        "profit_no_promo",
        "seller_cancel_penalty",
        "late_ship_penalty",
        "payout_if_paid",
        "expected_payout",
        "actual_profit",
        "margin_fact_rub",
    }:
        _COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_MONEY_FMT)


@st.cache_data(show_spinner=False)
def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    excel_df = df.copy()
    for col in excel_df.select_dtypes(include=["datetimetz"]).columns:
        excel_df[col] = excel_df[col].dt.tz_localize(None)
    excel_df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def _excel_session_key(df: pd.DataFrame) -> str:
    h = hashlib.md5(pd.util.hash_pandas_object(df, index=True).values).hexdigest()
    return f"excel_{h}"


def show_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False)

    cols = [c for c in (DISPLAY_COLUMNS if show_all else MAIN_COLUMNS) if c in df.columns]
    view = df[cols].rename(columns=COLUMN_LABELS)

    st.dataframe(view, width="stretch", hide_index=True, column_config=_COLUMN_CONFIG)
    st.caption(f"Строк: {len(df):,}")

    excel_key = _excel_session_key(view)
    excel_ready = excel_key in st.session_state

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Скачать CSV", csv, "orders.csv", "text/csv")
    with col2:
        st.download_button(
            "Скачать Excel",
            st.session_state.get(excel_key, b""),
            "orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=not excel_ready,
        )

    if not excel_ready:
        st.session_state[excel_key] = _to_excel(view)
        st.rerun()
