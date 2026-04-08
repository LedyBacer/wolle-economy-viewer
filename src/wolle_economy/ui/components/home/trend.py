import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wolle_economy.ui.helpers import orders_dedup


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

