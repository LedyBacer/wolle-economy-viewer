import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from wolle_economy.ui.formatters import fmt_money
from wolle_economy.ui.helpers import orders_dedup


def tab_trends(df: pd.DataFrame) -> None:
    st.subheader("Тренды и динамика")

    if df["created_at"].isna().all():
        st.info("Нет дат заказов.")
        return

    granularity = st.radio("Гранулярность", ["День", "Неделя", "Месяц"], horizontal=True, index=1)
    freq = {"День": "D", "Неделя": "W", "Месяц": "MS"}[granularity]

    od = orders_dedup(df).copy()
    od["период"] = (
        od["created_at"]
        .dt.tz_localize(None)
        .dt.to_period({"D": "D", "W": "W", "MS": "M"}[freq])
        .dt.start_time
    )

    items = df.copy()
    items["период"] = (
        items["created_at"]
        .dt.tz_localize(None)
        .dt.to_period({"D": "D", "W": "W", "MS": "M"}[freq])
        .dt.start_time
    )

    order_agg = od.groupby("период").agg(
        выручка=("sell_price", "sum"),
        заказов=("ya_order_id", "nunique"),
        выплата=("expected_payout", "sum"),
    )
    item_agg = items.groupby("период").agg(
        прибыль=("profit", "sum"),
        затраты=("our_costs", "sum"),
    )
    trend = order_agg.join(item_agg).reset_index()
    trend["AOV"] = trend["выручка"] / trend["заказов"]
    trend["маржа_%"] = (trend["прибыль"] / trend["выручка"] * 100).round(1)
    trend["MoM_выручка_%"] = (trend["выручка"].pct_change() * 100).round(1)

    fig = go.Figure()
    fig.add_bar(x=trend["период"], y=trend["выручка"], name="Выручка")
    fig.add_trace(
        go.Scatter(
            x=trend["период"],
            y=trend["прибыль"],
            name="Прибыль",
            mode="lines+markers",
            line={"color": "green", "width": 3},
        )
    )
    fig.update_layout(
        height=400,
        title="Выручка и прибыль",
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(trend, x="период", y="AOV", title="AOV (средний чек)", markers=True)
        fig.update_layout(height=300, margin={"l": 20, "r": 20, "t": 40, "b": 20})
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = px.line(trend, x="период", y="маржа_%", title="Маржа, %", markers=True)
        fig.add_hline(y=0, line_dash="dash", line_color="red")
        fig.update_layout(height=300, margin={"l": 20, "r": 20, "t": 40, "b": 20})
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Сводная таблица**")
    disp = trend.copy()
    for col in ["выручка", "выплата", "прибыль", "затраты", "AOV"]:
        disp[col] = disp[col].map(fmt_money)
    disp["маржа_%"] = disp["маржа_%"].astype(str) + "%"
    disp["MoM_выручка_%"] = disp["MoM_выручка_%"].fillna(0).astype(str) + "%"
    st.dataframe(disp, hide_index=True, width="stretch")

    # Heat-map: день недели × неделя
    st.markdown("**Heat-map: день недели × неделя (выручка)**")
    hm = od.copy()
    hm["неделя"] = hm["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time
    hm["день_недели"] = hm["created_at"].dt.day_name()
    pivot = hm.pivot_table(
        index="день_недели",
        columns="неделя",
        values="sell_price",
        aggfunc="sum",
        fill_value=0,
    )
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    pivot = pivot.reindex([d for d in days_order if d in pivot.index])
    if not pivot.empty:
        fig = px.imshow(
            pivot,
            aspect="auto",
            color_continuous_scale="Viridis",
            labels={"color": "Выручка, ₽"},
        )
        fig.update_layout(height=320, margin={"l": 20, "r": 20, "t": 10, "b": 20})
        st.plotly_chart(fig, width="stretch")

