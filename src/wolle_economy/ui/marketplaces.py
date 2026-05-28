"""UI-профили маркетплейсов: фильтры, метрики, таблицы, аналитика."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from wolle_economy.domain.loader import MarketplaceSpec, get_marketplace_specs
from wolle_economy.ui.components.analytics.render import render_analytics_tabs
from wolle_economy.ui.components.orders.filters import sidebar_db_filters, sidebar_memory_filters
from wolle_economy.ui.components.orders.filters_mm import (
    sidebar_mm_db_filters,
    sidebar_mm_memory_filters,
)
from wolle_economy.ui.components.orders.filters_sm import (
    sidebar_sm_db_filters,
    sidebar_sm_memory_filters,
)
from wolle_economy.ui.components.orders.metrics import show_metrics
from wolle_economy.ui.components.orders.metrics_mm import show_mm_metrics
from wolle_economy.ui.components.orders.metrics_sm import show_sm_metrics
from wolle_economy.ui.components.orders.table import show_table
from wolle_economy.ui.components.orders.table_mm import show_mm_table
from wolle_economy.ui.components.orders.table_sm import show_sm_table

DbFiltersFn = Callable[[], tuple[tuple[int, ...] | None, datetime.date, datetime.date]]
MemoryFiltersFn = Callable[[pd.DataFrame], pd.DataFrame]
MetricsFn = Callable[[pd.DataFrame], None]
TableFn = Callable[[pd.DataFrame], None]
AnalyticsFn = Callable[[pd.DataFrame], None]


@dataclass(frozen=True)
class MarketplaceUIHandlers:
    db_filters: DbFiltersFn
    memory_filters: MemoryFiltersFn
    metrics: MetricsFn
    table: TableFn
    analytics: AnalyticsFn


def _render_ym_analytics(df: pd.DataFrame) -> None:
    render_analytics_tabs(df, key_prefix="ym")


def _render_mm_analytics(df: pd.DataFrame) -> None:
    render_analytics_tabs(df, key_prefix="mm")


def _render_sm_analytics(df: pd.DataFrame) -> None:
    render_analytics_tabs(df, key_prefix="sm")


_UI_BY_CODE: dict[str, MarketplaceUIHandlers] = {
    "ym": MarketplaceUIHandlers(
        db_filters=sidebar_db_filters,
        memory_filters=sidebar_memory_filters,
        metrics=show_metrics,
        table=show_table,
        analytics=_render_ym_analytics,
    ),
    "mm": MarketplaceUIHandlers(
        db_filters=sidebar_mm_db_filters,
        memory_filters=sidebar_mm_memory_filters,
        metrics=show_mm_metrics,
        table=show_mm_table,
        analytics=_render_mm_analytics,
    ),
    "sm": MarketplaceUIHandlers(
        db_filters=sidebar_sm_db_filters,
        memory_filters=sidebar_sm_memory_filters,
        metrics=show_sm_metrics,
        table=show_sm_table,
        analytics=_render_sm_analytics,
    ),
}


def get_ui_handlers(code: str) -> MarketplaceUIHandlers:
    return _UI_BY_CODE[code]


def iter_marketplace_ui() -> list[tuple[MarketplaceSpec, MarketplaceUIHandlers]]:
    return [(spec, get_ui_handlers(spec.code)) for spec in get_marketplace_specs()]
