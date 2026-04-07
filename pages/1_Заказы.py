import streamlit as st
import pandas as pd
from db.connection import get_engine
from db.queries import ORDER_ITEMS_SQL, PAYMENT_AGGREGATES_SQL
from economics import calc_economics, merge_with_payments, COLUMN_LABELS, DISPLAY_COLUMNS


@st.cache_data(ttl=300, show_spinner="Загрузка данных...")
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


def show_metrics(df: pd.DataFrame) -> None:
    c = st.columns(5)
    c[0].metric("Заказов", f"{len(df):,}")
    c[1].metric("Ожид. прибыль", f"{df['expected_profit'].sum():,.0f} ₽")
    c[2].metric("Факт. прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    c[3].metric("Комиссии ЯМ", f"{df['market_services'].sum():,.0f} ₽")
    c[4].metric("Сумма выплат", f"{df['expected_payout'].sum():,.0f} ₽")


def show_table(df: pd.DataFrame) -> None:
    display_cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
    view = df[display_cols].rename(columns=COLUMN_LABELS)

    money_fmt = "%.2f ₽"
    pct_fmt = "%.1f%%"

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Заказ создан":                          st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
            "Дата отгрузки":                         st.column_config.DatetimeColumn(format="DD.MM.YYYY"),
            "Дата выплаты":                          st.column_config.DatetimeColumn(format="DD.MM.YYYY"),
            "Цена закупки":                          st.column_config.NumberColumn(format=money_fmt),
            "Цена упаковки":                         st.column_config.NumberColumn(format=money_fmt),
            "Цена переходника":                      st.column_config.NumberColumn(format=money_fmt),
            "Цена + маржа":                          st.column_config.NumberColumn(format=money_fmt),
            "Наша маржа на заказ":                   st.column_config.NumberColumn(format=money_fmt),
            "Минимальная цена":                      st.column_config.NumberColumn(format=money_fmt),
            "Ожидаемая прибыль":                     st.column_config.NumberColumn(format=money_fmt),
            "Цена продажи":                          st.column_config.NumberColumn(format=money_fmt),
            "Начислено баллов":                      st.column_config.NumberColumn(format=money_fmt),
            "Списано баллов":                        st.column_config.NumberColumn(format=money_fmt),
            "Разница от мин. цены":                  st.column_config.NumberColumn(format=money_fmt),
            "Расчётные комиссии":                    st.column_config.NumberColumn(format=money_fmt),
            "Комиссии":                              st.column_config.NumberColumn(format=money_fmt),
            "Доход за вычетом комиссий":             st.column_config.NumberColumn(format=money_fmt),
            "Прибыль":                               st.column_config.NumberColumn(format=money_fmt),
            "Разница Прибыли Факт/Ожид":             st.column_config.NumberColumn(format=money_fmt),
            "Доход за вычетом комиссий (с баллами)": st.column_config.NumberColumn(format=money_fmt),
            "Прибыль без учёта баллов":              st.column_config.NumberColumn(format=money_fmt),
            "Штраф за отмену заказа":                st.column_config.NumberColumn(format=money_fmt),
            "Штраф за позднюю отгрузку":             st.column_config.NumberColumn(format=money_fmt),
            "Нам перевели за заказ":                 st.column_config.NumberColumn(format=money_fmt),
            "Сумма выплаты (если нет даты, то ожидаемая)": st.column_config.NumberColumn(format=money_fmt),
            "Фактическая прибыль":                   st.column_config.NumberColumn(format=money_fmt),
        },
    )

    st.caption(f"Строк: {len(df):,}")

    csv = view.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ Скачать CSV", csv, "orders.csv", "text/csv")


def main():
    st.title("Заказы — юнит-экономика")

    try:
        df = load_data()
    except Exception as e:
        st.error(f"Ошибка загрузки: {e}")
        st.stop()

    filtered = sidebar_filters(df)

    show_metrics(filtered)
    st.divider()
    show_table(filtered)


main()
