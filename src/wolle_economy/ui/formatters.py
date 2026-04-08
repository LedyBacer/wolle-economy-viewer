"""
Утилиты форматирования чисел для отображения в UI.
"""

import pandas as pd


def fmt_money(x: float) -> str:
    """Форматирует число как денежную сумму в рублях. NaN → «—»."""
    if pd.isna(x):
        return "—"
    return f"{x:,.0f} ₽".replace(",", " ")


def fmt_pct(x: float, digits: int = 1) -> str:
    """Форматирует число как процент. NaN → «—»."""
    if pd.isna(x):
        return "—"
    return f"{x:.{digits}f}%"
