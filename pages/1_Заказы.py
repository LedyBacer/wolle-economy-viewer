import streamlit as st
import pandas as pd
from db.connection import get_engine
from db.queries import ORDERS_ECONOMICS_SQL
from economics import add_derived_columns, get_display_columns, COLUMN_LABELS


@st.cache_data(ttl=300, show_spinner="Загрузка данных из БД...")
def load_orders() -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(ORDERS_ECONOMICS_SQL, conn)
    df = add_derived_columns(df)
    return df


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Фильтры")

        sellers = sorted(df["seller_name"].dropna().unique())
        selected_sellers = st.multiselect("Продавец", sellers, default=sellers)

        date_min = df["created_at"].min()
        date_max = df["created_at"].max()
        if pd.notna(date_min) and pd.notna(date_max):
            date_range = st.date_input(
                "Дата создания",
                value=(date_min.date(), date_max.date()),
                min_value=date_min.date(),
                max_value=date_max.date(),
            )
        else:
            date_range = None

        statuses = sorted(df["margin_report_status"].dropna().unique())
        selected_statuses = st.multiselect("Статус заказа 2", statuses, default=statuses)

        payment_statuses = sorted(df["margin_report_payment_status"].dropna().unique())
        selected_payment_statuses = st.multiselect(
            "Статус платежа", payment_statuses, default=payment_statuses
        )

        offer_filter = st.text_input("Артикул (содержит)")
        supplier_filter = st.text_input("Поставщик (содержит)")

    mask = (
        df["seller_name"].isin(selected_sellers)
        & df["margin_report_status"].isin(selected_statuses)
        & df["margin_report_payment_status"].isin(selected_payment_statuses)
    )

    if date_range and len(date_range) == 2:
        d_from = pd.Timestamp(date_range[0], tz="UTC")
        d_to = pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        mask &= df["created_at"].between(d_from, d_to)

    if offer_filter:
        mask &= df["offer_id"].str.contains(offer_filter, case=False, na=False)

    if supplier_filter:
        mask &= df["supplier_name"].str.contains(supplier_filter, case=False, na=False)

    return df[mask]


def show_summary(df: pd.DataFrame):
    cols = st.columns(4)
    cols[0].metric("Заказов", f"{len(df):,}")
    cols[1].metric("Сумма выплат", f"{df['sum_vyplat'].sum():,.0f} ₽")
    cols[2].metric("Фактическая прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    cols[3].metric("Маржа (расчёт)", f"{df['margin_value'].sum():,.0f} ₽")


def main():
    st.title("Заказы — юнит-экономика")

    try:
        df = load_orders()
    except Exception as e:
        st.error(f"Ошибка загрузки данных: {e}")
        return

    filtered = apply_filters(df)

    show_summary(filtered)

    st.divider()

    display_cols = [c for c in get_display_columns() if c in filtered.columns]
    display_df = filtered[display_cols].rename(columns=COLUMN_LABELS)

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Дата создания": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
            "Дата отгрузки": st.column_config.DatetimeColumn(format="DD.MM.YYYY"),
            "Дата выплат": st.column_config.DatetimeColumn(format="DD.MM.YYYY"),
            "Цена закупки": st.column_config.NumberColumn(format="%.2f ₽"),
            "Цена упаковки": st.column_config.NumberColumn(format="%.2f ₽"),
            "Цена переходника": st.column_config.NumberColumn(format="%.2f ₽"),
            "Цена с наценкой": st.column_config.NumberColumn(format="%.2f ₽"),
            "Финальная цена": st.column_config.NumberColumn(format="%.2f ₽"),
            "Маржа (руб)": st.column_config.NumberColumn(format="%.2f ₽"),
            "Цена покупателя + субсидия": st.column_config.NumberColumn(format="%.2f ₽"),
            "Баллы (бонус)": st.column_config.NumberColumn(format="%.2f ₽"),
            "Услуги маркета": st.column_config.NumberColumn(format="%.2f ₽"),
            "Разница цен": st.column_config.NumberColumn(format="%.2f ₽"),
            "Расчётные комиссии": st.column_config.NumberColumn(format="%.2f ₽"),
            "Скидка за акцию": st.column_config.NumberColumn(format="%.2f ₽"),
            "E72+E20+E21": st.column_config.NumberColumn(format="%.2f ₽"),
            "E72+E20+E21−E73": st.column_config.NumberColumn(format="%.2f ₽"),
            "% маржинальности": st.column_config.NumberColumn(format="%.1f%%"),
            "E72": st.column_config.NumberColumn(format="%.2f ₽"),
            "E72−E73": st.column_config.NumberColumn(format="%.2f ₽"),
            "Штраф (отмена)": st.column_config.NumberColumn(format="%.2f ₽"),
            "Штраф (опоздание)": st.column_config.NumberColumn(format="%.2f ₽"),
            "E72 (условная)": st.column_config.NumberColumn(format="%.2f ₽"),
            "Сумма выплат": st.column_config.NumberColumn(format="%.2f ₽"),
            "Фактическая прибыль": st.column_config.NumberColumn(format="%.2f ₽"),
        },
    )

    st.caption(f"Показано строк: {len(filtered):,} из {len(df):,}")

    csv = display_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Скачать CSV",
        data=csv,
        file_name="orders_economics.csv",
        mime="text/csv",
    )


main()
