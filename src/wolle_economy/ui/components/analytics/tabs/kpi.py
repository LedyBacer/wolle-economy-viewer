import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wolle_economy.domain.kpis import compute_kpis
from wolle_economy.ui.formatters import fmt_money, fmt_pct


def tab_kpi(df: pd.DataFrame) -> None:
    st.subheader("Ключевые показатели")

    m = compute_kpis(df)
    revenue, payout, commissions, our_costs = m.revenue, m.payout, m.commissions, m.our_costs
    profit, profit_no_pr, promo = m.profit, m.profit_no_promo, m.promo
    penalties, compensations = m.penalties, m.compensations
    n_orders, n_items = m.n_orders, m.n_items
    aov, aov_net = m.aov, m.aov_net
    net_margin, take_rate, contrib = m.net_margin, m.take_rate, m.contrib
    return_rate, cancel_rate, fulfill_rate = m.return_rate, m.cancel_rate, m.fulfill_rate
    loss_share, items_per_o = m.loss_share, m.items_per_o

    # ---- Деньги ----
    st.markdown("**Деньги**")
    c = st.columns(4)
    c[0].metric("Выручка (GMV)", fmt_money(revenue))
    c[1].metric("Выплата от ЯМ", fmt_money(payout))
    c[2].metric("Прибыль (с промо)", fmt_money(profit))
    c[3].metric("Прибыль без промо", fmt_money(profit_no_pr))

    c = st.columns(4)
    c[0].metric("Комиссии ЯМ", fmt_money(commissions))
    c[1].metric("Наши затраты", fmt_money(our_costs))
    c[2].metric("Промо-расходы", fmt_money(promo))
    c[3].metric("Штрафы / Компенсации", f"{fmt_money(penalties)} / {fmt_money(compensations)}")

    # ---- Маржинальность и тейк ----
    st.markdown("**Маржинальность**")
    c = st.columns(4)
    c[0].metric("Net Margin", fmt_pct(net_margin), help="Прибыль / GMV")
    c[1].metric("Contribution Margin", fmt_pct(contrib), help="(Выплата − затраты) / GMV")
    c[2].metric("Take Rate ЯМ", fmt_pct(take_rate), help="Комиссии ЯМ / GMV")
    c[3].metric("Доля убыточных заказов", fmt_pct(loss_share))

    # ---- Объёмы ----
    st.markdown("**Объёмы и средние чеки**")
    c = st.columns(4)
    c[0].metric("Заказов", f"{n_orders:,}".replace(",", " "))
    c[1].metric("Позиций / шт", f"{int(n_items):,}".replace(",", " "))
    c[2].metric("AOV (брутто)", fmt_money(aov), help="Средний чек по sell_price")
    c[3].metric("AOV (нетто, после комиссий)", fmt_money(aov_net))

    c = st.columns(4)
    c[0].metric("Позиций на заказ", f"{items_per_o:.2f}")
    c[1].metric("Fulfillment Rate", fmt_pct(fulfill_rate), help="Доставлено / всего")
    c[2].metric("Cancel Rate", fmt_pct(cancel_rate), help="Отменено до отгрузки / всего")
    c[3].metric("Return Rate", fmt_pct(return_rate), help="Возвраты+невыкупы / всего")

    st.divider()

    # ---- Водопад: выручка → прибыль ----
    st.markdown("**Декомпозиция прибыли (waterfall)**")
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=["Выручка (GMV)", "− Комиссии ЯМ", "− Наши затраты", "+ Промо (−)", "Прибыль"],
            y=[revenue, -commissions, -our_costs, promo, 0],
            textposition="outside",
            text=[fmt_money(v) for v in [revenue, -commissions, -our_costs, promo, profit]],
            connector={"line": {"color": "rgb(120,120,120)"}},
        )
    )
    fig.update_layout(height=420, margin={"l": 20, "r": 20, "t": 20, "b": 20})
    st.plotly_chart(fig, width="stretch")

