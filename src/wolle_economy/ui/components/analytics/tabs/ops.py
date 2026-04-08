import pandas as pd
import plotly.express as px
import streamlit as st

from wolle_economy.ui.formatters import fmt_money
from wolle_economy.ui.helpers import orders_dedup


def tab_ops(df: pd.DataFrame) -> None:
    st.subheader("Операционные метрики")

    od = orders_dedup(df)

    ship = od["ship_lag_days"].dropna()
    ship = ship[(ship >= 0) & (ship < 60)]

    cancel_pen = od.get("seller_cancel_penalty", pd.Series(dtype=float)).fillna(0).sum()
    late_pen = od.get("late_ship_penalty", pd.Series(dtype=float)).fillna(0).sum()
    comp = od.get("compensations", pd.Series(dtype=float)).fillna(0).sum()

    c = st.columns(4)
    c[0].metric("Средний срок отгрузки", f"{ship.mean():.1f} дн" if len(ship) else "—")
    c[1].metric("Штрафы за отмену", fmt_money(cancel_pen))
    c[2].metric("Штрафы за позднюю отгрузку", fmt_money(late_pen))
    c[3].metric("Компенсации в нашу пользу", fmt_money(comp))

    if len(ship):
        st.markdown("**Распределение времени до отгрузки (дни)**")
        fig = px.histogram(ship, nbins=30, labels={"value": "Дней"})
        fig.update_layout(
            height=300,
            margin={"l": 20, "r": 20, "t": 10, "b": 20},
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Воронка статусов**")
    funnel_counts = od.groupby("fulfillment_status", observed=True)["ya_order_id"].nunique()
    funnel_df = funnel_counts.sort_values(ascending=False).reset_index()
    funnel_df.columns = ["Статус", "Заказов"]
    fig = px.funnel(funnel_df, x="Заказов", y="Статус")
    fig.update_layout(height=400, margin={"l": 20, "r": 20, "t": 10, "b": 20})
    st.plotly_chart(fig, width="stretch")

