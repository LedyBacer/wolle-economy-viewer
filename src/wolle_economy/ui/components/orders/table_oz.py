import io

import pandas as pd
import streamlit as st

from wolle_economy.ui.columns import COLUMN_LABELS, DISPLAY_COLUMNS

_OZ_TECHNICAL_COLUMNS = {
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
    "oz_status",
    "report_rows",
    "return_docs",
}

_OZ_MAIN_COLUMNS = [c for c in DISPLAY_COLUMNS if c not in _OZ_TECHNICAL_COLUMNS]
_OZ_REFERENCE_COLUMNS = [
    "created_at",
    "order_id_str",
    "order_status",
    "offer_id",
    "product_name",
    "quantity",
    "supplier_name",
    "shipment_date",
    "base_price_total",
    "supplier_price_fact_total",
    "socket_adapter_total",
    "ff_fee_total",
    "category_fee",
    "category_fee_fact",
    "acquiring_fee_plan",
    "acquiring_fee_fact",
    "last_mile",
    "last_mile_fact",
    "order_process_delivery",
    "order_process_delivery_fact",
    "min_price_multiplier",
    "margin_price",
    "price",
    "revenue_after_commission",
    "expected_profit",
    "profit_fact",
    "cancel_penalty",
    "late_shipment_penalty",
    "late_recommend_penalty",
]
_OZ_ALL_COLUMNS = _OZ_REFERENCE_COLUMNS + [c for c in DISPLAY_COLUMNS if c not in _OZ_REFERENCE_COLUMNS]
_OZ_COLUMN_LABELS = {
    **COLUMN_LABELS,
    "base_price": "Цена закупки за шт.",
    "base_price_total": "Цена закупки",
    "supplier_price_fact": "Факт. закупка поставщика за шт.",
    "supplier_price_fact_total": "Факт. закупка поставщика",
    "ff_fee": "Цена упаковки за шт.",
    "ff_fee_total": "Цена упаковки",
    "socket_adapter_fee": "Цена переходника за шт.",
    "socket_adapter_total": "Цена переходника",
    "category_fee": "Комиссия категории план",
    "category_fee_fact": "Комиссия категории факт",
    "acquiring_fee_plan": "Эквайринг план",
    "acquiring_fee_fact": "Эквайринг факт",
    "last_mile": "Последняя миля план",
    "last_mile_fact": "Последняя миля факт",
    "order_process_delivery": "Обработка и доставка план",
    "order_process_delivery_fact": "Обработка и доставка факт",
    "min_price_multiplier": "Коэф. мин. цены",
    "margin_price": "Минимальная цена",
    "price": "Цена продажи план",
    "revenue_after_commission": "Доход после комиссий",
    "expected_profit": "Прибыль план",
    "profit_fact": "Прибыль факт",
    "cancel_penalty": "Штраф за отмену",
    "late_shipment_penalty": "Штраф за позднюю отгрузку",
    "late_recommend_penalty": "Штраф за нерекомендованный слот",
    "sell_price_plan": "Плановая цена продажи",
    "delivery_fee_plan": "Доставка план",
}

_MONEY_FMT = "%.2f ₽"
_PCT_FMT = "%.1f %%"
_OZ_COLUMN_CONFIG: dict = {}
for _col, _label in _OZ_COLUMN_LABELS.items():
    if _col in {"created_at"}:
        _OZ_COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")
    elif _col in {"shipment_date", "last_payment_date"}:
        _OZ_COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY")
    elif _col in {
        "margin_plan_pct",
        "margin_fact_pct",
        "margin_plan_on_cost_pct",
        "margin_fact_on_cost_pct",
    }:
        _OZ_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_PCT_FMT)
    elif _col in {"min_price_multiplier"}:
        _OZ_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format="%.4f")
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
        "min_sell_price_total",
        "expected_profit",
        "price",
        "sell_price_plan",
        "sell_price",
        "bonus_points",
        "promo_discounts",
        "diff_from_min_price",
        "category_fee",
        "category_fee_fact",
        "acquiring_fee_plan",
        "acquiring_fee_fact",
        "last_mile",
        "last_mile_fact",
        "order_process_delivery",
        "order_process_delivery_fact",
        "delivery_fee_plan",
        "calc_commissions",
        "market_services",
        "fact_commissions",
        "revenue_after_commission",
        "income_after_fees",
        "profit",
        "profit_fact",
        "profit_vs_expected",
        "income_after_fees_promo",
        "profit_no_promo",
        "cancel_penalty",
        "late_shipment_penalty",
        "late_recommend_penalty",
        "seller_cancel_penalty",
        "late_ship_penalty",
        "payout_if_paid",
        "expected_payout",
        "actual_profit",
        "margin_fact_rub",
    }:
        _OZ_COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_MONEY_FMT)


@st.cache_data(show_spinner=False)
def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    excel_df = df.copy()
    for col in excel_df.select_dtypes(include=["datetimetz"]).columns:
        excel_df[col] = excel_df[col].dt.tz_localize(None)
    excel_df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def show_oz_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False, key="oz_show_all_cols")

    cols = [c for c in (_OZ_ALL_COLUMNS if show_all else _OZ_MAIN_COLUMNS) if c in df.columns]
    view = df[cols].rename(columns=_OZ_COLUMN_LABELS)

    st.dataframe(view, width="stretch", hide_index=True, column_config=_OZ_COLUMN_CONFIG)
    st.caption(f"Строк: {len(df):,}")

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Скачать CSV", csv, "oz_orders.csv", "text/csv", key="oz_csv")
    with col2:
        st.download_button(
            "Скачать Excel",
            _to_excel(view),
            "oz_orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="oz_xlsx",
        )
