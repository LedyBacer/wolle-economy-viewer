import io

import pandas as pd
import streamlit as st

from wolle_economy.ui.columns import MM_COLUMN_LABELS, MM_DISPLAY_COLUMNS

# Технические колонки — скрыты по умолчанию
_MM_TECHNICAL_COLUMNS = {
    "income_after_fees",
    "income_after_fees_promo",
    "profit_no_promo",
    "profit_vs_expected",
    "diff_from_min_price",
    "payout_if_paid",
    "offer_id",
    "cdek_status",
    "item_status",
    "delivery_commission",
    "return_commission",
    "cancellation_commission",
    "bonus_from_mm",
}

_MM_MAIN_COLUMNS = [c for c in MM_DISPLAY_COLUMNS if c not in _MM_TECHNICAL_COLUMNS]

_MONEY_FMT = "%.2f ₽"
_PCT_FMT = "%.1f %%"
_MM_COLUMN_CONFIG: dict = {}
for _col, _label in MM_COLUMN_LABELS.items():
    if _col in {"created_at", "delivered_at"}:
        _MM_COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")
    elif _col in {"last_payment_date", "deduction_date"}:
        _MM_COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY")
    elif _col in {"margin_plan_pct", "margin_fact_pct", "margin_plan_on_cost_pct", "margin_fact_on_cost_pct"}:
        _MM_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_PCT_FMT)
    elif _col in {
        "base_price_total",
        "effective_purchase_total",
        "price_with_margin",
        "our_margin",
        "min_sell_price_total",
        "expected_profit",
        "sell_price",
        "promo_discounts",
        "bonus_from_mm",
        "diff_from_min_price",
        "market_services",
        "delivery_commission",
        "return_commission",
        "cancellation_commission",
        "return_delivery_cost",
        "cdek_delivery_cost",
        "delivery_cost",
        "incentive_amount",
        "vat_on_incentive",
        "income_after_fees",
        "profit",
        "profit_vs_expected",
        "income_after_fees_promo",
        "profit_no_promo",
        "expected_payout",
        "payout_if_paid",
        "actual_profit",
        "margin_fact_rub",
        "our_costs",
    }:
        _MM_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_MONEY_FMT)


@st.cache_data(show_spinner=False)
def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    excel_df = df.copy()
    for col in excel_df.select_dtypes(include=["datetimetz"]).columns:
        excel_df[col] = excel_df[col].dt.tz_localize(None)
    excel_df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def show_mm_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False, key="mm_show_all_cols")

    cols = [c for c in (MM_DISPLAY_COLUMNS if show_all else _MM_MAIN_COLUMNS) if c in df.columns]
    view = df[cols].rename(columns=MM_COLUMN_LABELS)

    st.dataframe(view, width="stretch", hide_index=True, column_config=_MM_COLUMN_CONFIG)
    st.caption(f"Строк: {len(df):,}")

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Скачать CSV", csv, "mm_orders.csv", "text/csv", key="mm_csv")
    with col2:
        st.download_button(
            "Скачать Excel",
            _to_excel(view),
            "mm_orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="mm_xlsx",
        )
