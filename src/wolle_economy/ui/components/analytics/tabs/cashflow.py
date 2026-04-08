import pandas as pd
import plotly.express as px
import streamlit as st

from wolle_economy.ui.formatters import fmt_money
from wolle_economy.ui.helpers import orders_dedup


def tab_cashflow(df: pd.DataFrame) -> None:
    st.subheader("Денежный поток и выплаты")

    od = orders_dedup(df).copy()
    received = od[od["payment_status"].isin({"Переведён", "Удержан из платежей покупателей"})]
    pending = od[~od.index.isin(received.index) & ~od["is_cancelled_any"]]

    c = st.columns(4)
    c[0].metric("Получено всего", fmt_money(received["expected_payout"].sum()))
    c[1].metric("Ожидается выплата", fmt_money(pending["expected_payout"].sum()))
    c[2].metric("Заказов в ожидании", f"{len(pending):,}".replace(",", " "))

    avg_lag = od["pay_lag_days"].dropna()
    avg_lag = avg_lag[(avg_lag >= 0) & (avg_lag < 180)]
    c[3].metric("Средний лаг выплаты", f"{avg_lag.mean():.1f} дн" if len(avg_lag) else "—")

    st.markdown("**Outstanding (ожидающие выплаты) по магазинам**")
    out = (
        pending.groupby("seller_name", observed=True)
        .agg(
            заказов=("ya_order_id", "nunique"),
            ожидается=("expected_payout", "sum"),
        )
        .reset_index()
        .sort_values("ожидается", ascending=False)
    )
    out["ожидается"] = out["ожидается"].map(fmt_money)
    st.dataframe(out.rename(columns={"seller_name": "Магазин"}), hide_index=True, width="stretch")

    st.markdown("**Распределение лага выплаты (дни от заказа до денег)**")
    if len(avg_lag):
        fig = px.histogram(avg_lag, nbins=40, labels={"value": "Дней до выплаты"})
        fig.update_layout(
            height=300,
            margin={"l": 20, "r": 20, "t": 10, "b": 20},
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")

