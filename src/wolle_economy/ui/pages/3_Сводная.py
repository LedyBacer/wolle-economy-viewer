"""Сводная аналитика по всем маркетплейсам."""

import logging

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Wolle — Сводная",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)
from wolle_economy.logging_setup import setup_logging
from wolle_economy.ui.columns import UNIFIED_COLUMNS
from wolle_economy.ui.formatters import fmt_money, fmt_money_compact, fmt_pct
from wolle_economy.ui.helpers import dedup_for_marketplace, safe_load_marketplace_orders
from wolle_economy.ui.marketplaces import iter_marketplace_ui

setup_logging()
logger = logging.getLogger(__name__)


def _add_marketplace_col(df: pd.DataFrame, marketplace: str) -> pd.DataFrame:
    out = df.copy()
    out["marketplace"] = marketplace
    for col in UNIFIED_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
    return out[UNIFIED_COLUMNS]


def _render_comparison_kpis(parts: list[tuple[str, pd.DataFrame, pd.DataFrame]]) -> None:
    st.subheader("Сравнение маркетплейсов")
    for idx, (title, od, df) in enumerate(parts):
        with st.container(border=True):
            st.markdown(f"### {title}")
            n_orders = int(od.shape[0])
            revenue = od["sell_price"].sum()
            profit = df["profit"].sum()
            commissions = od["market_services"].sum()
            margin = profit / revenue * 100 if revenue else float("nan")
            our_costs = df["our_costs"].sum()

            c = st.columns(3)
            c[0].metric("Заказов", f"{n_orders:,}".replace(",", " "))
            c[1].metric("Выручка", fmt_money_compact(revenue), help=fmt_money(revenue))
            c[2].metric("Прибыль", fmt_money_compact(profit), help=fmt_money(profit))

            c = st.columns(3)
            c[0].metric("Маржа", fmt_pct(margin))
            c[1].metric("Комиссии МП", fmt_money_compact(commissions), help=fmt_money(commissions))
            c[2].metric("Наши затраты", fmt_money_compact(our_costs), help=fmt_money(our_costs))

        if idx < len(parts) - 1:
            st.markdown("")


def _render_unified_trend(df_all: pd.DataFrame) -> None:
    st.subheader("Тренд выручки и прибыли")

    df = df_all.copy()
    df["date"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True).dt.date

    agg = (
        df.groupby(["date", "marketplace"])
        .agg(
            выручка=("sell_price", "sum"),
            прибыль=("profit", "sum"),
        )
        .reset_index()
    )

    tab_rev, tab_prof = st.tabs(["Выручка", "Прибыль"])
    with tab_rev:
        pivot = agg.pivot_table(index="date", columns="marketplace", values="выручка", fill_value=0)
        st.line_chart(pivot)
    with tab_prof:
        pivot = agg.pivot_table(index="date", columns="marketplace", values="прибыль", fill_value=0)
        st.line_chart(pivot)


def main() -> None:
    st.title("Сводная аналитика")
    st.caption("Общие метрики по всем маркетплейсам.")

    loaded: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
    parts: list[pd.DataFrame] = []

    for spec, _ in iter_marketplace_ui():
        df = safe_load_marketplace_orders(spec)
        if df.empty:
            continue
        od = dedup_for_marketplace(df, spec)
        loaded.append((spec.title, od, df))
        parts.append(_add_marketplace_col(df, spec.title))

    if not loaded:
        st.warning("Нет данных ни по одному маркетплейсу.")
        st.stop()
        return

    _render_comparison_kpis(loaded)
    st.divider()
    _render_unified_trend(pd.concat(parts, ignore_index=True))


main()
