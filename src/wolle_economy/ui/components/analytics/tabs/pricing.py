import pandas as pd
import plotly.express as px
import streamlit as st

from wolle_economy.ui.formatters import fmt_money, fmt_pct
from wolle_economy.ui.helpers import orders_dedup


def tab_pricing(df: pd.DataFrame) -> None:
    st.subheader("Ценообразование")

    od = orders_dedup(df).copy()
    od = od[od["sell_price"].notna() & (od["sell_price"] > 0)]
    if od.empty:
        st.info("Нет данных.")
        return

    below_min = od[od["diff_from_min_price"] < 0]
    share_below = len(below_min) / len(od) * 100

    c = st.columns(3)
    c[0].metric("Заказов ниже мин. цены", f"{len(below_min):,}".replace(",", " "))
    c[1].metric("Доля ниже минимальной", fmt_pct(share_below))
    c[2].metric("Сумма недополучено vs мин.", fmt_money(below_min["diff_from_min_price"].sum()))

    st.markdown("**Распределение `diff_from_min_price` (sell_price − минимальная цена)**")
    fig = px.histogram(
        od,
        x="diff_from_min_price",
        nbins=60,
        labels={"diff_from_min_price": "Разница от мин. цены, ₽"},
    )
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=320, margin={"l": 20, "r": 20, "t": 10, "b": 20})
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Распределение маржи на заказ (%)**")
    md = df.groupby("ya_order_id").agg(
        sell_price=("sell_price", "first"),
        profit=("profit", "sum"),
    )
    md = md[md["sell_price"] > 0]
    md["margin_pct"] = md["profit"] / md["sell_price"] * 100
    md = md[md["margin_pct"].between(-100, 100)]
    fig = px.histogram(md, x="margin_pct", nbins=60, labels={"margin_pct": "Маржа на заказ, %"})
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=320, margin={"l": 20, "r": 20, "t": 10, "b": 20})
    st.plotly_chart(fig, width="stretch")

