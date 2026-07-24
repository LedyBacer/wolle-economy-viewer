import io

import pandas as pd
import streamlit as st

from wolle_economy.ui.columns import COLUMN_LABELS, DISPLAY_COLUMNS

# Технические колонки — скрыты по умолчанию
TECHNICAL_COLUMNS = {
    "bonus_points",
    "calc_category_fee_total",
    "fact_category_fee",
    "category_fee_diff",
    "calc_transfer_fee_total",
    "fact_transfer_fee",
    "transfer_fee_diff",
    "calc_delivery_fee_total",
    "fact_delivery_fee",
    "yandex_delivery_fee_diff",
    "calc_accepting_payment_fee_total",
    "fact_accepting_payment_fee",
    "accepting_payment_fee_diff",
    "calc_order_processing_fee_total",
    "fact_order_processing_fee",
    "order_processing_fee_diff",
    "calc_commissions",
    "fact_commissions",
    "commissions_diff",
    "fact_other_fees",
    "fact_unclassified_fees",
    "fact_commissions_available",
    "fact_commission_details_complete",
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
    elif _col in {
        "margin_plan_pct",
        "margin_fact_pct",
        "margin_plan_on_cost_pct",
        "margin_fact_on_cost_pct",
    }:
        _COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_PCT_FMT)
    elif _col in {
        "base_price_total",
        "effective_purchase_total",
        "ff_fee_total",
        "socket_adapter_total",
        "custom_delivery_fee_total",
        "price_with_margin",
        "our_margin",
        "min_sell_price_total",
        "expected_profit",
        "sell_price",
        "bonus_points",
        "promo_discounts",
        "diff_from_min_price",
        "calc_category_fee_total",
        "fact_category_fee",
        "category_fee_diff",
        "calc_transfer_fee_total",
        "fact_transfer_fee",
        "transfer_fee_diff",
        "calc_delivery_fee_total",
        "fact_delivery_fee",
        "yandex_delivery_fee_diff",
        "calc_accepting_payment_fee_total",
        "fact_accepting_payment_fee",
        "accepting_payment_fee_diff",
        "calc_order_processing_fee_total",
        "fact_order_processing_fee",
        "order_processing_fee_diff",
        "calc_commissions",
        "market_services",
        "fact_commissions",
        "commissions_diff",
        "fact_other_fees",
        "fact_unclassified_fees",
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


def show_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False)

    cols = [c for c in (DISPLAY_COLUMNS if show_all else MAIN_COLUMNS) if c in df.columns]
    view = df[cols].rename(columns=COLUMN_LABELS)

    st.dataframe(view, width="stretch", hide_index=True, column_config=_COLUMN_CONFIG)
    st.caption(f"Строк: {len(df):,}")

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Скачать CSV", csv, "orders.csv", "text/csv")
    with col2:
        st.download_button(
            "Скачать Excel",
            _to_excel(view),
            "orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
