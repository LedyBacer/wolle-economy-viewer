"""
Wolle — Юнит-экономика Яндекс Маркет.
Точка входа Streamlit. Содержит обзорный дашборд с ключевыми показателями
и навигацией к детальным разделам.
"""

import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.config import get_settings
from wolle_economy.domain.loader import load_orders
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.formatters import fmt_money, fmt_pct
from wolle_economy.ui.helpers import orders_dedup, show_load_error

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def render_kpis(df: pd.DataFrame) -> None:
    od = orders_dedup(df)

    revenue = od["sell_price"].sum()
    profit = df["profit"].sum()
    payout = od["expected_payout"].sum()
    n_orders = od["ya_order_id"].nunique()
    margin = profit / revenue * 100 if revenue else float("nan")
    aov = revenue / n_orders if n_orders else float("nan")

    c = st.columns(4)
    c[0].metric("Выручка", fmt_money(revenue))
    c[1].metric("Чистая прибыль", fmt_money(profit), help="С учётом промо-расходов")
    c[2].metric("Маржа", fmt_pct(margin))
    c[3].metric("Заказов", f"{n_orders:,}".replace(",", " "))

    c = st.columns(4)
    c[0].metric("Средний чек", fmt_money(aov))
    c[1].metric("Выплачено от ЯМ", fmt_money(payout))
    c[2].metric("Комиссии ЯМ", fmt_money(od["market_services"].sum()))
    c[3].metric("Наши затраты", fmt_money(df["our_costs"].sum()))


def render_trend(df: pd.DataFrame) -> None:
    if df["created_at"].isna().all():
        return
    od = orders_dedup(df).copy()
    items = df.copy()
    od["week"] = od["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time
    items["week"] = items["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time

    weekly = (
        od.groupby("week")
        .agg(revenue=("sell_price", "sum"))
        .join(items.groupby("week").agg(profit=("profit", "sum")))
        .reset_index()
    )

    fig = go.Figure()
    fig.add_bar(x=weekly["week"], y=weekly["revenue"], name="Выручка", marker_color="#cfd8dc")
    fig.add_trace(
        go.Scatter(
            x=weekly["week"],
            y=weekly["profit"],
            name="Прибыль",
            mode="lines+markers",
            line={"color": "#2e7d32", "width": 3},
        )
    )
    fig.update_layout(
        height=320,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0},
        xaxis_title="",
        yaxis_title="₽",
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")


def render_navigation() -> None:
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("### 📦 Заказы")
        st.markdown(
            "Детализированная таблица позиций заказов с фильтрами "
            "по магазину, периоду, статусам, поиском по товару и поставщику. "
            "Экспорт в CSV / Excel."
        )
        st.page_link("pages/1_Заказы.py", label="Открыть раздел →")
    with c2, st.container(border=True):
        st.markdown("### 📈 Аналитика")
        st.markdown(
            "KPI-дашборд, ABC-анализ ассортимента, возвраты и отмены, "
            "поставщики, ценообразование, денежный поток и тренды."
        )
        st.page_link("pages/2_Аналитика.py", label="Открыть раздел →")


def main() -> None:
    st.title("Wolle — юнит-экономика Яндекс Маркет")
    st.caption("Сводный обзор по магазинам с полной отчётностью маржи Маркета.")

    try:
        df = load_orders()
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

    df_clean = df[~df["seller_name"].isin(get_settings().low_quality_sellers)]
    if df_clean.empty:
        df_clean = df

    render_kpis(df_clean)
    st.divider()
    render_trend(df_clean)
    st.divider()
    render_navigation()


main()
