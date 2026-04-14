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
from wolle_economy.ui.columns import UNIFIED_COLUMN_LABELS, UNIFIED_COLUMNS
from wolle_economy.ui.formatters import fmt_money, fmt_pct
from wolle_economy.ui.helpers import (
    mm_orders_dedup,
    orders_dedup,
    safe_load_mm_orders,
    safe_load_orders,
)

setup_logging()
logger = logging.getLogger(__name__)


def _add_marketplace_col(df: pd.DataFrame, marketplace: str) -> pd.DataFrame:
    """Добавляет колонку marketplace и возвращает только общие колонки."""
    out = df.copy()
    out["marketplace"] = marketplace
    # our_costs может отсутствовать в ЯМ DataFrame (уровень позиции) — обеспечим наличие
    for col in UNIFIED_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
    return out[UNIFIED_COLUMNS]


def _render_comparison_kpis(df_ym: pd.DataFrame, df_mm: pd.DataFrame) -> None:
    """KPI по каждому маркетплейсу рядом."""
    od_ym = orders_dedup(df_ym)
    od_mm = mm_orders_dedup(df_mm)

    st.subheader("Сравнение маркетплейсов")
    cols = st.columns(2)

    for col, label, od, df in [
        (cols[0], "Яндекс Маркет", od_ym, df_ym),
        (cols[1], "МегаМаркет", od_mm, df_mm),
    ]:
        with col:
            st.markdown(f"**{label}**")
            n_orders = int(od.shape[0])
            revenue = od["sell_price"].sum()
            profit = df["profit"].sum()
            commissions = od["market_services"].sum()
            margin = profit / revenue * 100 if revenue else float("nan")

            c = st.columns(3)
            c[0].metric("Заказов", f"{n_orders:,}")
            c[1].metric("Выручка", fmt_money(revenue))
            c[2].metric("Прибыль", fmt_money(profit))

            c = st.columns(3)
            c[0].metric("Маржа", fmt_pct(margin))
            c[1].metric("Комиссии МП", fmt_money(commissions))
            c[2].metric("Наши затраты", fmt_money(df["our_costs"].sum()))


def _render_unified_trend(df_all: pd.DataFrame) -> None:
    """Трендовый график выручки и прибыли с разбивкой по маркетплейсу."""
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

    df_ym = safe_load_orders()
    df_mm = safe_load_mm_orders()

    if df_ym.empty and df_mm.empty:
        st.warning("Нет данных ни по одному маркетплейсу.")
        st.stop()
        return

    _render_comparison_kpis(df_ym, df_mm)
    st.divider()

    # Объединённый DataFrame для трендов
    parts = []
    if not df_ym.empty:
        parts.append(_add_marketplace_col(df_ym, "Яндекс Маркет"))
    if not df_mm.empty:
        parts.append(_add_marketplace_col(df_mm, "МегаМаркет"))
    df_all = pd.concat(parts, ignore_index=True)

    _render_unified_trend(df_all)


main()
