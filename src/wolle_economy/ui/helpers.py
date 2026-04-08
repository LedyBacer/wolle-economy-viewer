"""
Общие UI-хелперы: дедупликация DataFrame по заказу, предупреждения о качестве данных.
"""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from wolle_economy.config import get_settings

logger = logging.getLogger(__name__)


def orders_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """
    Возвращает DataFrame с одной строкой на заказ.
    Нужен для корректной агрегации полей уровня заказа
    (sell_price, market_services, expected_payout), которые дублируются
    для каждой позиции заказа.
    """
    return df.drop_duplicates(subset="ya_order_id")


def show_data_quality_warning(df: pd.DataFrame) -> None:
    """
    Показывает раскрывающееся уведомление, если в выборке есть магазины
    без полного отчёта о марже ЯМ (данные носят справочный характер).
    """
    affected = get_settings().low_quality_sellers & set(df["seller_name"].dropna().unique())
    if not affected:
        return
    with st.expander(
        f"ℹ️ В выборке магазины со справочными данными: {', '.join(sorted(affected))}",
        expanded=False,
    ):
        st.markdown(
            "Для этих магазинов в источнике отсутствует отчёт о марже Маркета. "
            "Комиссии ЯМ и сумма выплаты для них рассчитаны по упрощённой формуле "
            "и носят справочный характер."
        )


def show_load_error(
    *,
    title: str,
    exc: Exception,
    details: str | None = None,
) -> None:
    """
    Единый формат сообщения об ошибке загрузки данных в UI.
    Детали логируются, пользователю показывается короткий текст.
    """
    logger.exception("%s: %s", title, exc)
    st.error(title)
    if details:
        st.caption(details)
