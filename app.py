"""
Wolle — Юнит-экономика Яндекс Маркет.
Точка входа Streamlit. Содержит обзорный дашборд с ключевыми показателями
и навигацией к детальным разделам.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from db.connection import get_engine
from db.queries import ORDER_ITEMS_SQL, PAYMENT_AGGREGATES_SQL
from economics import calc_economics, merge_with_payments

st.set_page_config(
    page_title="Wolle — Юнит-экономика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Магазины без полного отчёта о марже — исключаем из обзорных цифр,
# чтобы не вводить в заблуждение завышенными показателями.
LOW_QUALITY_SELLERS = {"WolleBuy", "ТехноПравда Гонконг"}


@st.cache_data(ttl=3600, show_spinner="Загрузка данных…")
def load_data() -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        orders = pd.read_sql(ORDER_ITEMS_SQL, conn)
        payments = pd.read_sql(PAYMENT_AGGREGATES_SQL, conn)
    df = merge_with_payments(orders, payments)
    return calc_economics(df)


def fmt_money(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:,.0f} ₽".replace(",", " ")


def fmt_pct(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:.1f}%"


def render_kpis(df: pd.DataFrame) -> None:
    od = df.drop_duplicates(subset="ya_order_id")

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
    od = df.drop_duplicates(subset="ya_order_id").copy()
    items = df.copy()
    od["week"] = od["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time
    items["week"] = items["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time

    weekly = od.groupby("week").agg(revenue=("sell_price", "sum")).join(
        items.groupby("week").agg(profit=("profit", "sum"))
    ).reset_index()

    fig = go.Figure()
    fig.add_bar(x=weekly["week"], y=weekly["revenue"], name="Выручка",
                marker_color="#cfd8dc")
    fig.add_trace(go.Scatter(
        x=weekly["week"], y=weekly["profit"], name="Прибыль",
        mode="lines+markers", line=dict(color="#2e7d32", width=3),
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        xaxis_title="",
        yaxis_title="₽",
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_navigation() -> None:
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("### 📦 Заказы")
            st.markdown(
                "Детализированная таблица позиций заказов с фильтрами "
                "по магазину, периоду, статусам, поиском по товару и поставщику. "
                "Экспорт в CSV / Excel."
            )
            st.page_link("pages/1_Заказы.py", label="Открыть раздел →")
    with c2:
        with st.container(border=True):
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
        df = load_data()
    except Exception as e:
        st.error(f"Не удалось загрузить данные: {e}")
        st.stop()

    df_clean = df[~df["seller_name"].isin(LOW_QUALITY_SELLERS)]
    if df_clean.empty:
        df_clean = df

    render_kpis(df_clean)
    st.divider()
    render_trend(df_clean)
    st.divider()
    render_navigation()


main()
