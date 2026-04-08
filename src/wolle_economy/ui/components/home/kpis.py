import pandas as pd
import streamlit as st

from wolle_economy.domain.kpis import compute_kpis
from wolle_economy.ui.formatters import fmt_money, fmt_pct


def render_kpis(df: pd.DataFrame) -> None:
    m = compute_kpis(df)

    c = st.columns(4)
    c[0].metric("Выручка", fmt_money(m.revenue))
    c[1].metric("Чистая прибыль", fmt_money(m.profit), help="С учётом промо-расходов")
    c[2].metric("Маржа", fmt_pct(m.net_margin))
    c[3].metric("Заказов", f"{m.n_orders:,}".replace(",", " "))

    c = st.columns(4)
    c[0].metric("Средний чек", fmt_money(m.aov))
    c[1].metric("Выплачено от ЯМ", fmt_money(m.payout))
    c[2].metric("Комиссии ЯМ", fmt_money(m.commissions))
    c[3].metric("Наши затраты", fmt_money(m.our_costs))

