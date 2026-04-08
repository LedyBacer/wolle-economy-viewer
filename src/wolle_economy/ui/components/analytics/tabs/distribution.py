import pandas as pd
import plotly.express as px
import streamlit as st

from wolle_economy.ui.formatters import fmt_money


def tab_distribution(df: pd.DataFrame) -> None:
    st.subheader("Распределение прибыли по заказам")

    by_order = (
        df.groupby("ya_order_id")
        .agg(
            profit=("profit", "sum"),
            sell_price=("sell_price", "first"),
            seller_name=("seller_name", "first"),
        )
        .reset_index()
    )
    by_order = by_order[by_order["sell_price"].fillna(0) > 0]

    n_loss = (by_order["profit"] < 0).sum()
    n_total = len(by_order)
    avg_profit = by_order["profit"].mean()
    median_profit = by_order["profit"].median()

    c = st.columns(4)
    c[0].metric("Заказов всего", f"{n_total:,}".replace(",", " "))
    c[1].metric("Убыточных", f"{n_loss:,}".replace(",", " "))
    c[2].metric("Средняя прибыль/заказ", fmt_money(avg_profit))
    c[3].metric("Медианная прибыль/заказ", fmt_money(median_profit))

    fig = px.histogram(
        by_order,
        x="profit",
        nbins=80,
        color="seller_name",
        labels={"profit": "Прибыль за заказ, ₽", "seller_name": "Магазин"},
    )
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=400, margin={"l": 20, "r": 20, "t": 10, "b": 20})
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Топ-20 самых убыточных заказов**")
    losers = by_order.nsmallest(20, "profit").copy()
    losers["profit"] = losers["profit"].map(fmt_money)
    losers["sell_price"] = losers["sell_price"].map(fmt_money)
    st.dataframe(
        losers.rename(
            columns={
                "ya_order_id": "ID заказа",
                "profit": "Прибыль",
                "sell_price": "Выручка",
                "seller_name": "Магазин",
            }
        ),
        hide_index=True,
        width="stretch",
    )

