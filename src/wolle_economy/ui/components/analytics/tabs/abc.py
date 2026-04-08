import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from wolle_economy.ui.formatters import fmt_money


def tab_abc(df: pd.DataFrame) -> None:
    st.subheader("ABC-анализ товаров (Парето)")
    st.caption(
        "A — товары, дающие 80% выручки; B — следующие 15%; C — последние 5%. "
        "Класс A — ядро ассортимента, требует контроля наличия и цен."
    )

    agg = (
        df.groupby(["offer_id", "product_name"], observed=True)
        .agg(
            выручка=("sell_price", "sum"),
            прибыль=("profit", "sum"),
            продаж=("quantity", "sum"),
            заказов=("ya_order_id", "nunique"),
        )
        .reset_index()
    )
    agg = agg[agg["выручка"] > 0].sort_values("выручка", ascending=False)
    if agg.empty:
        st.info("Нет данных.")
        return

    agg["доля_%"] = agg["выручка"] / agg["выручка"].sum() * 100
    agg["накоп_%"] = agg["доля_%"].cumsum()
    agg["класс"] = np.where(agg["накоп_%"] <= 80, "A", np.where(agg["накоп_%"] <= 95, "B", "C"))
    agg["маржа_%"] = (agg["прибыль"] / agg["выручка"] * 100).round(1)

    # Сводка по классам
    summary = (
        agg.groupby("класс")
        .agg(
            товаров=("offer_id", "count"),
            выручка=("выручка", "sum"),
            прибыль=("прибыль", "sum"),
        )
        .reset_index()
    )
    summary["доля_выручки_%"] = (summary["выручка"] / summary["выручка"].sum() * 100).round(1)
    summary["маржа_%"] = (summary["прибыль"] / summary["выручка"] * 100).round(1)

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Классы**")
        disp = summary.copy()
        disp["выручка"] = disp["выручка"].map(fmt_money)
        disp["прибыль"] = disp["прибыль"].map(fmt_money)
        disp["доля_выручки_%"] = disp["доля_выручки_%"].map(lambda x: f"{x:.1f}%")
        disp["маржа_%"] = disp["маржа_%"].map(lambda x: f"{x:.1f}%")
        st.dataframe(disp, hide_index=True, width="stretch")
    with c2:
        # Кривая Парето
        fig = px.line(
            agg.reset_index(drop=True).reset_index(),
            x="index",
            y="накоп_%",
            title="Кривая Парето",
            labels={"index": "Товары (отсортированы)", "накоп_%": "Накопленная доля выручки, %"},
        )
        fig.add_hline(y=80, line_dash="dot", line_color="green", annotation_text="A=80%")
        fig.add_hline(y=95, line_dash="dot", line_color="orange", annotation_text="B=95%")
        fig.update_layout(height=320, margin={"l": 20, "r": 20, "t": 40, "b": 20})
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Полный список товаров**")
    show = agg.copy()
    for col in ["выручка", "прибыль"]:
        show[col] = show[col].map(fmt_money)
    show["доля_%"] = show["доля_%"].round(2).astype(str) + "%"
    show["накоп_%"] = show["накоп_%"].round(1).astype(str) + "%"
    show["маржа_%"] = show["маржа_%"].astype(str) + "%"
    st.dataframe(
        show.rename(
            columns={
                "offer_id": "Offer ID",
                "product_name": "Товар",
                "продаж": "Шт",
                "заказов": "Заказов",
            }
        ),
        hide_index=True,
        width="stretch",
        height=420,
    )

    st.markdown("**⚠ Убыточные «лидеры» — товары класса A/B с отрицательной маржой**")
    losers = agg[(agg["класс"].isin({"A", "B"})) & (agg["прибыль"] < 0)]
    if losers.empty:
        st.success("Все товары классов A и B прибыльны.")
    else:
        disp = losers.copy()
        for col in ["выручка", "прибыль"]:
            disp[col] = disp[col].map(fmt_money)
        st.dataframe(
            disp[["offer_id", "product_name", "класс", "выручка", "прибыль", "маржа_%"]],
            hide_index=True,
            width="stretch",
        )

