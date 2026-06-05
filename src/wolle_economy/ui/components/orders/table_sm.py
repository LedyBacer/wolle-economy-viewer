import io

import pandas as pd
import streamlit as st

from wolle_economy.ui.columns import COLUMN_LABELS, DISPLAY_COLUMNS

_SM_TECHNICAL_COLUMNS = {
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

_SM_MAIN_COLUMNS = [c for c in DISPLAY_COLUMNS if c not in _SM_TECHNICAL_COLUMNS]
_SM_REFERENCE_COLUMNS = [
    "created_at",
    "date_realization",
    "order_id_str",
    "order_status",
    "offer_id",
    "product_name",
    "quantity",
    "supplier_name",
    "shipment_date",
    "base_price_total",
    "supplier_price_fact_total",
    "ff_fee",
    "socket_adapter_fee",
    "category_fee_percent",
    "agent_rate_percent",
    "category_fee",
    "agent_rate",
    "delivery_fee",
    "logistic",
    "modifier_price",
    "min_price_multiplier",
    "sm_profit_on_purchase_pct",
    "margin_price",
    "margin_price_total",
    "seller_price_unit",
    "diff_from_min_price",
    "expected_profit",
    "profit_unit",
    "profit",
    "expected_payout",
    "payout_if_paid",
]
_SM_ALL_COLUMNS = _SM_REFERENCE_COLUMNS + [c for c in DISPLAY_COLUMNS if c not in _SM_REFERENCE_COLUMNS]
_SM_COLUMN_LABELS = {
    **COLUMN_LABELS,
    "date_realization": "Дата реализации",
    "base_price": "Цена закупки за шт.",
    "supplier_price_fact": "Факт. закупка поставщика за шт.",
    "supplier_price_fact_total": "Факт. закупка поставщика",
    "ff_fee": "Цена упаковки за шт.",
    "socket_adapter_fee": "Цена переходника за шт.",
    "category_fee_percent": "Комиссия категории %",
    "agent_rate_percent": "Агентская комиссия %",
    "category_fee": "Комиссия категории",
    "agent_rate": "Агентская комиссия",
    "delivery_fee": "Доставка план",
    "logistic": "Логистика факт",
    "modifier_price": "Цена с модификаторами",
    "min_price_multiplier": "Коэф. мин. цены",
    "sm_profit_on_purchase_pct": "Прибыль факт % от закупки",
    "margin_price": "Минимальная цена за шт.",
    "margin_price_total": "Минимальная цена",
    "seller_price_unit": "Цена продажи за шт.",
    "profit_unit": "Прибыль за шт.",
    "total": "Итого по отчёту SM",
    "refund_quantity": "Количество возврата",
    "refund_total_to_seller": "Возврат продавцу",
}

_MONEY_FMT = "%.2f ₽"
_PCT_FMT = "%.1f %%"
_SM_COLUMN_CONFIG: dict = {}
for _col, _label in _SM_COLUMN_LABELS.items():
    if _col in {"created_at"}:
        _SM_COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")
    elif _col in {"date_realization", "shipment_date", "last_payment_date"}:
        _SM_COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY")
    elif _col in {
        "margin_plan_pct",
        "margin_fact_pct",
        "margin_plan_on_cost_pct",
        "margin_fact_on_cost_pct",
        "category_fee_percent",
        "agent_rate_percent",
        "sm_profit_on_purchase_pct",
    }:
        _SM_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_PCT_FMT)
    elif _col in {"min_price_multiplier"}:
        _SM_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format="%.4f")
    elif _col in {
        "base_price",
        "base_price_total",
        "supplier_price_fact",
        "supplier_price_fact_total",
        "effective_purchase_total",
        "ff_fee",
        "ff_fee_total",
        "socket_adapter_fee",
        "socket_adapter_total",
        "price_with_margin",
        "our_margin",
        "margin_price",
        "margin_price_total",
        "min_sell_price_total",
        "expected_profit",
        "seller_price_unit",
        "sell_price",
        "bonus_points",
        "promo_discounts",
        "diff_from_min_price",
        "category_fee",
        "agent_rate",
        "delivery_fee",
        "logistic",
        "modifier_price",
        "calc_commissions",
        "market_services",
        "fact_commissions",
        "income_after_fees",
        "profit_unit",
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
        "total",
        "refund_total_to_seller",
    }:
        _SM_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_MONEY_FMT)


@st.cache_data(show_spinner=False)
def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    excel_df = df.copy()
    for col in excel_df.select_dtypes(include=["datetimetz"]).columns:
        excel_df[col] = excel_df[col].dt.tz_localize(None)
    excel_df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def show_sm_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False, key="sm_show_all_cols")

    cols = [c for c in (_SM_ALL_COLUMNS if show_all else _SM_MAIN_COLUMNS) if c in df.columns]
    view = df[cols].rename(columns=_SM_COLUMN_LABELS)

    st.dataframe(view, width="stretch", hide_index=True, column_config=_SM_COLUMN_CONFIG)
    st.caption(f"Строк: {len(df):,}")

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Скачать CSV", csv, "sm_orders.csv", "text/csv", key="sm_csv")
    with col2:
        st.download_button(
            "Скачать Excel",
            _to_excel(view),
            "sm_orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="sm_xlsx",
        )
