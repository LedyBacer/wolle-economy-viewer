import io
import streamlit as st
import pandas as pd
from db.connection import get_engine
from db.queries import ORDER_ITEMS_SQL, PAYMENT_AGGREGATES_SQL
from economics import calc_economics, merge_with_payments, COLUMN_LABELS, DISPLAY_COLUMNS


@st.cache_data(ttl=3600, show_spinner="Загрузка данных...")
def load_data() -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        orders = pd.read_sql(ORDER_ITEMS_SQL, conn)
        payments = pd.read_sql(PAYMENT_AGGREGATES_SQL, conn)

    df = merge_with_payments(orders, payments)
    df = calc_economics(df)
    return df


def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Фильтры")

        # Продавец
        sellers = sorted(df["seller_name"].dropna().unique())
        sel_sellers = st.multiselect("Магазин", sellers, default=sellers)

        # Период
        dates = df["created_at"].dropna()
        if not dates.empty:
            d_min, d_max = dates.min().date(), dates.max().date()
            date_range = st.date_input("Дата создания", (d_min, d_max), d_min, d_max)
        else:
            date_range = None

        # Статус заказа 2
        statuses = sorted(df["fulfillment_status"].dropna().unique())
        sel_statuses = st.multiselect("Статус заказа 2", statuses, default=statuses)

        # Статус платежа
        pay_statuses = sorted(df["payment_status"].dropna().unique())
        sel_pay = st.multiselect("Статус платежа", pay_statuses, default=pay_statuses)

        # Текстовые фильтры
        offer_q = st.text_input("Offer ID (содержит)")
        supplier_q = st.text_input("Поставщик (содержит)")

    mask = (
        df["seller_name"].isin(sel_sellers)
        & df["fulfillment_status"].isin(sel_statuses)
        & df["payment_status"].isin(sel_pay)
    )

    if date_range and len(date_range) == 2:
        d_from = pd.Timestamp(date_range[0], tz="UTC")
        d_to = pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        mask &= df["created_at"].between(d_from, d_to)

    if offer_q:
        mask &= df["offer_id"].str.contains(offer_q, case=False, na=False)
    if supplier_q:
        mask &= df["supplier_name"].str.contains(supplier_q, case=False, na=False)

    return df[mask].copy()


def show_data_quality_warning(df: pd.DataFrame) -> None:
    """Тонкое уведомление, если в выборке есть продавцы без полного margin_report."""
    no_margin_report = {"ТехноПравда Гонконг", "WolleBuy"}
    affected = no_margin_report & set(df["seller_name"].dropna().unique())
    if not affected:
        return
    with st.expander(
        f"ℹ️ В выборке магазины со справочными данными: {', '.join(sorted(affected))}",
        expanded=False,
    ):
        st.markdown(
            "Для этих магазинов в источнике отсутствует отчёт о марже Маркета. "
            "Комиссии ЯМ и сумма выплаты для них рассчитаны по упрощённой формуле "
            "и носят справочный характер."
        )


def show_metrics(df: pd.DataFrame) -> None:
    # sell_price / market_services / expected_payout хранятся на уровне заказа,
    # но строки — позиции. Для корректной суммы берём первую строку каждого заказа.
    orders_dedup = df.drop_duplicates(subset="ya_order_id")
    c = st.columns(5)
    c[0].metric("Заказов", f"{orders_dedup['ya_order_id'].nunique():,}")
    c[1].metric("Ожид. прибыль", f"{df['expected_profit'].sum():,.0f} ₽")
    c[2].metric("Факт. прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    c[3].metric("Комиссии ЯМ", f"{orders_dedup['market_services'].sum():,.0f} ₽")
    c[4].metric("Сумма выплат", f"{orders_dedup['expected_payout'].sum():,.0f} ₽")


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

# Основные колонки — всегда видны
MAIN_COLUMNS = [c for c in DISPLAY_COLUMNS if c not in TECHNICAL_COLUMNS]

MONEY_COLUMNS = {
    "Заказ создан":                              "DatetimeColumn",
    "Дата отгрузки":                             "DatetimeColumn",
    "Дата выплаты":                              "DatetimeColumn",
    "Цена закупки":                              "money",
    "Цена упаковки":                             "money",
    "Цена переходника":                          "money",
    "Цена + маржа":                              "money",
    "Наша маржа на заказ":                       "money",
    "Минимальная цена":                          "money",
    "Ожидаемая прибыль":                         "money",
    "Цена продажи":                              "money",
    "Субсидия ЯМ (справочно, в sell_price)":    "money",
    "Промо-расходы (наши баллы)":               "money",
    "Разница от мин. цены":                      "money",
    "Расчётные комиссии":                        "money",
    "Комиссии (margin_report)":                  "money",
    "Факт. комиссии (ЛК)":                       "money",
    "Доход за вычетом комиссий":                "money",
    "Прибыль":                                   "money",
    "Разница Прибыли Факт/Ожид":                "money",
    "Доход за вычетом комиссий и промо":        "money",
    "Прибыль без учёта промо-расходов":         "money",
    "Штраф за отмену заказа":                   "money",
    "Штраф за позднюю отгрузку":               "money",
    "Нам перевели за заказ":                    "money",
    "Сумма выплаты (если нет даты, то ожидаемая)": "money",
    "Фактическая прибыль":                      "money",
}


def _build_column_config() -> dict:
    money_fmt = "%.2f ₽"
    cfg = {}
    for col, kind in MONEY_COLUMNS.items():
        if kind == "DatetimeColumn":
            fmt = "DD.MM.YYYY HH:mm" if "создан" in col else "DD.MM.YYYY"
            cfg[col] = st.column_config.DatetimeColumn(format=fmt)
        else:
            cfg[col] = st.column_config.NumberColumn(format=money_fmt)
    return cfg


def show_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False)

    if show_all:
        cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
    else:
        cols = [c for c in MAIN_COLUMNS if c in df.columns]

    view = df[cols].rename(columns=COLUMN_LABELS)

    st.dataframe(
        view,
        width='stretch',
        hide_index=True,
        column_config=_build_column_config(),
    )

    st.caption(f"Строк: {len(df):,}")

    col1, col2 = st.columns(2)
    with col1:
        csv = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Скачать CSV", csv, "orders.csv", "text/csv")
    with col2:
        buf = io.BytesIO()
        excel_view = view.copy()
        for col in excel_view.select_dtypes(include=["datetimetz"]).columns:
            excel_view[col] = excel_view[col].dt.tz_localize(None)
        excel_view.to_excel(buf, index=False, engine="openpyxl")
        st.download_button(
            "Скачать Excel",
            buf.getvalue(),
            "orders.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def main():
    st.title("Заказы")
    st.caption("Позиции заказов с расчётом юнит-экономики. Используйте фильтры в боковой панели.")

    try:
        df = load_data()
    except Exception as e:
        st.error(f"Ошибка загрузки: {e}")
        st.stop()

    filtered = sidebar_filters(df)

    show_data_quality_warning(filtered)
    show_metrics(filtered)
    st.divider()
    show_table(filtered)


main()
