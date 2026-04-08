import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from wolle_economy.ui.formatters import fmt_money


def tab_suppliers(df: pd.DataFrame) -> None:
    st.subheader("Аналитика по поставщикам")
    st.caption("Поставщик берётся из `ya_order_items.supplier_name` (откуда фактически отгружено).")

    has_sup = df[df["supplier_name"].notna() & (df["supplier_name"] != "")]
    if has_sup.empty:
        st.info("Нет данных по поставщикам.")
        return

    agg = (
        has_sup.groupby("supplier_name", observed=True)
        .agg(
            заказов=("ya_order_id", "nunique"),
            позиций=("item_id", "count"),
            шт=("quantity", "sum"),
            выручка=("sell_price", "sum"),
            наши_затраты=("our_costs", "sum"),
            прибыль=("profit", "sum"),
            возвратов=("is_returned", "sum"),
        )
        .reset_index()
    )
    agg["маржа_%"] = (agg["прибыль"] / agg["выручка"].replace(0, np.nan) * 100).round(1)
    agg["return_rate_%"] = (agg["возвратов"] / agg["позиций"] * 100).round(1)
    agg = agg.sort_values("прибыль", ascending=False)

    disp = agg.copy()
    for col in ["выручка", "наши_затраты", "прибыль"]:
        disp[col] = disp[col].map(fmt_money)
    disp["маржа_%"] = disp["маржа_%"].fillna(0).map(lambda x: f"{x:.1f}%")
    disp["return_rate_%"] = disp["return_rate_%"].fillna(0).map(lambda x: f"{x:.1f}%")
    st.dataframe(
        disp.rename(columns={"supplier_name": "Поставщик"}),
        hide_index=True,
        width="stretch",
    )

    fig = px.bar(
        agg.head(15),
        x="supplier_name",
        y="прибыль",
        color="маржа_%",
        color_continuous_scale="RdYlGn",
        title="Топ-15 поставщиков по прибыли",
    )
    fig.update_layout(height=380, xaxis_title="", yaxis_title="Прибыль, ₽")
    st.plotly_chart(fig, width="stretch")

