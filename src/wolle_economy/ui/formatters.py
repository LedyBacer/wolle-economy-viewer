"""
Утилиты форматирования чисел для отображения в UI.
"""

import pandas as pd


def fmt_money(x: float) -> str:
    """Форматирует число как денежную сумму в рублях. NaN → «—»."""
    if pd.isna(x):
        return "—"
    return f"{x:,.0f} ₽".replace(",", " ")


def fmt_money_compact(x: float) -> str:
    """Компактный денежный формат для узких KPI-карточек."""
    if pd.isna(x):
        return "—"

    value = float(x)
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} млрд ₽"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн ₽"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f} тыс ₽"
    return f"{value:.0f} ₽"


def fmt_pct(x: float, digits: int = 1) -> str:
    """Форматирует число как процент. NaN → «—»."""
    if pd.isna(x):
        return "—"
    return f"{x:.{digits}f}%"
