import pandas as pd
import streamlit as st

from wolle_economy.ui.formatters import fmt_money
from wolle_economy.ui.helpers import orders_dedup


def tab_returns(df: pd.DataFrame) -> None:
    st.subheader("Возвраты и отмены")

    od = orders_dedup(df)
    by_seller = od.groupby("seller_name", observed=True).agg(
        заказов=("ya_order_id", "nunique"),
        возвратов=("is_returned", "sum"),
        отмен_до_отгрузки=("is_cancelled_before", "sum"),
    )
    by_seller["return_rate_%"] = (by_seller["возвратов"] / by_seller["заказов"] * 100).round(1)
    by_seller["cancel_rate_%"] = (
        by_seller["отмен_до_отгрузки"] / by_seller["заказов"] * 100
    ).round(1)

    # Потерянная выручка и стоимость возврата (наши затраты на вернувшийся товар)
    lost_rev = od[od["is_cancelled_any"]].groupby("seller_name", observed=True)["sell_price"].sum()
    cost_of_returns = df[df["is_returned"]].groupby("seller_name", observed=True)["our_costs"].sum()
    by_seller["потерянная_выручка"] = lost_rev
    by_seller["затраты_на_возвраты"] = cost_of_returns
    by_seller = by_seller.fillna(0).reset_index().rename(columns={"seller_name": "Магазин"})

    disp = by_seller.copy()
    for col in ["потерянная_выручка", "затраты_на_возвраты"]:
        disp[col] = disp[col].map(fmt_money)
    disp["return_rate_%"] = disp["return_rate_%"].map(lambda x: f"{x:.1f}%")
    disp["cancel_rate_%"] = disp["cancel_rate_%"].map(lambda x: f"{x:.1f}%")
    st.dataframe(disp, hide_index=True, width="stretch")

    st.markdown("**Топ товаров по возвратам**")
    by_prod = (
        df.groupby(["offer_id", "product_name"], observed=True)
        .agg(
            продано=("quantity", "sum"),
            возвратов=("is_returned", "sum"),
            потерянная_выручка=(
                "sell_price",
                lambda s: s[df.loc[s.index, "is_returned"]].sum(),
            ),
        )
        .reset_index()
    )
    by_prod = by_prod[by_prod["возвратов"] > 0].copy()
    by_prod["return_rate_%"] = (by_prod["возвратов"] / by_prod["продано"] * 100).round(1)
    by_prod = by_prod.sort_values("возвратов", ascending=False).head(30)
    by_prod["потерянная_выручка"] = by_prod["потерянная_выручка"].map(fmt_money)
    by_prod["return_rate_%"] = by_prod["return_rate_%"].map(lambda x: f"{x:.1f}%")
    st.dataframe(
        by_prod.rename(columns={"offer_id": "Offer ID", "product_name": "Товар"}),
        hide_index=True,
        width="stretch",
    )

