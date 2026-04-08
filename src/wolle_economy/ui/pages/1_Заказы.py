import datetime
import io
import logging

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.domain.loader import load_date_range, load_orders, load_sellers
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.columns import COLUMN_LABELS, DISPLAY_COLUMNS
from wolle_economy.ui.helpers import orders_dedup, show_data_quality_warning, show_load_error

setup_logging()
logger = logging.getLogger(__name__)


def sidebar_db_filters() -> tuple[tuple[int, ...] | None, datetime.date, datetime.date]:
    """
    Рендерит фильтры по продавцу и дате в боковой панели.
    Возвращает параметры для DB-запроса: (seller_ids, date_from, date_to).
    """
    sellers_df = load_sellers()
    min_date, max_date = load_date_range()

    with st.sidebar:
        st.header("Фильтры")

        all_names = sellers_df["seller_name"].tolist()
        sel_names = st.multiselect("Магазин", all_names, default=all_names)

        date_range = st.date_input(
            "Дата создания",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

    # Маппинг имён → ID для DB-запроса
    if set(sel_names) == set(all_names):
        seller_ids = None  # все продавцы — без фильтра
    else:
        id_map = sellers_df.set_index("seller_name")["id"]
        seller_ids = tuple(int(id_map[n]) for n in sel_names if n in id_map)

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        date_from, date_to = date_range[0], date_range[1]
    else:
        date_from, date_to = min_date, max_date

    return seller_ids, date_from, date_to


def sidebar_memory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Дополнительные in-memory фильтры (статусы, поиск по тексту).
    Должны применяться ПОСЛЕ загрузки данных из БД.
    """
    with st.sidebar:
        statuses = sorted(df["fulfillment_status"].dropna().unique())
        sel_statuses = st.multiselect("Статус заказа", statuses, default=statuses)

        pay_statuses = sorted(df["payment_status"].dropna().unique())
        sel_pay = st.multiselect("Статус платежа", pay_statuses, default=pay_statuses)

        offer_q = st.text_input("Offer ID (содержит)")
        supplier_q = st.text_input("Поставщик (содержит)")

    mask = df["fulfillment_status"].isin(sel_statuses) & df["payment_status"].isin(sel_pay)
    if offer_q:
        mask &= df["offer_id"].str.contains(offer_q, case=False, na=False)
    if supplier_q:
        mask &= df["supplier_name"].str.contains(supplier_q, case=False, na=False)

    return df[mask].copy()


def show_metrics(df: pd.DataFrame) -> None:
    # sell_price / market_services / expected_payout хранятся на уровне заказа,
    # но строки — позиции. Для корректной суммы дедуплицируем по заказу.
    od = orders_dedup(df)
    c = st.columns(5)
    c[0].metric("Заказов", f"{od['ya_order_id'].nunique():,}")
    c[1].metric("Ожид. прибыль", f"{df['expected_profit'].sum():,.0f} ₽")
    c[2].metric("Факт. прибыль", f"{df['actual_profit'].sum():,.0f} ₽")
    c[3].metric("Комиссии ЯМ", f"{od['market_services'].sum():,.0f} ₽")
    c[4].metric("Сумма выплат", f"{od['expected_payout'].sum():,.0f} ₽")


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
_COLUMN_CONFIG: dict = {}
for _col, _label in COLUMN_LABELS.items():
    if _col in {"created_at"}:
        _COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")
    elif _col in {"shipment_date", "last_payment_date"}:
        _COLUMN_CONFIG[_label] = st.column_config.DatetimeColumn(format="DD.MM.YYYY")
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
    }:
        _COLUMN_CONFIG[_label] = st.column_config.NumberColumn(format=_MONEY_FMT)


def show_table(df: pd.DataFrame) -> None:
    show_all = st.toggle("Показать все колонки", value=False)

    cols = [c for c in (DISPLAY_COLUMNS if show_all else MAIN_COLUMNS) if c in df.columns]
    view = df[cols].rename(columns=COLUMN_LABELS)

    st.dataframe(view, width="stretch", hide_index=True, column_config=_COLUMN_CONFIG)
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


def main() -> None:
    st.title("Заказы")
    st.caption("Позиции заказов с расчётом юнит-экономики. Используйте фильтры в боковой панели.")

    # Шаг 1: DB-фильтры (продавец, дата) — рендерятся до загрузки данных
    seller_ids, date_from, date_to = sidebar_db_filters()

    # Шаг 2: Загрузка данных с фильтрацией на стороне БД
    try:
        df = load_orders(seller_ids=seller_ids, date_from=date_from, date_to=date_to)
    except SQLAlchemyError as e:
        show_load_error(
            title="Не удалось загрузить данные из базы данных.",
            exc=e,
            details="Проверьте `.env`/переменные окружения и доступность PostgreSQL.",
        )
        st.stop()
        return
    except (ValueError, KeyError, TypeError) as e:
        show_load_error(
            title="Данные из БД имеют неожиданный формат.",
            exc=e,
            details="Проверьте актуальность схемы/запросов и наличие нужных колонок.",
        )
        st.stop()
        return

    # Шаг 3: In-memory фильтры (статусы, текстовый поиск)
    filtered = sidebar_memory_filters(df)

    show_data_quality_warning(filtered)
    show_metrics(filtered)
    st.divider()
    show_table(filtered)


main()
