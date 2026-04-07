"""
Расчёт производных показателей юнит-экономики.
Чистые функции без side-эффектов.
"""
import pandas as pd
import numpy as np


# Читаемые названия колонок для отображения
COLUMN_LABELS = {
    "created_at": "Дата создания",
    "shipment_date": "Дата отгрузки",
    "seller_name": "Продавец",
    "order_id_str": "Номер заказа",
    "offer_id": "Артикул",
    "product_name": "Товар",
    "effective_order_status": "Статус заказа",
    "margin_report_status": "Статус заказа 2",
    "margin_report_payment_status": "Статус платежа",
    "item_count": "Кол-во",
    "supplier_name": "Поставщик",
    "base_price_total": "Цена закупки",
    "ff_fee_total": "Цена упаковки",
    "socket_adapter_fee_total": "Цена переходника",
    "price_with_margin": "Цена с наценкой",
    "margin_percent": "% наценки",
    "final_price_total": "Финальная цена",
    "margin_value": "Маржа (руб)",
    "buyer_price_subsidy_total": "Цена покупателя + субсидия",
    "sum_bonus_points": "Баллы (бонус)",
    "market_services": "Услуги маркета",
    "price_diff": "Разница цен",
    "commission_calc": "Расчётные комиссии",
    "sum_promo_discount": "Скидка за акцию",
    "e72_e20_e21": "E72+E20+E21",
    "e72_e20_e21_minus_e73": "E72+E20+E21−E73",
    "margin_percent_calc": "% маржинальности",
    "avg_e72": "E72",
    "e72_minus_e73": "E72−E73",
    "seller_cancel_fee": "Штраф (отмена)",
    "late_ship_fee": "Штраф (опоздание)",
    "conditional_e72": "E72 (условная)",
    "sum_vyplat": "Сумма выплат",
    "date_vyplat": "Дата выплат",
    "actual_profit": "Фактическая прибыль",
}


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет производные колонки: расчётные комиссии и фактическую прибыль."""
    df = df.copy()

    # Расчётные комиссии = сумма 6 компонент
    df["commission_calc"] = (
        df["markup_accepting_payments"].fillna(0)
        + df["markup_order_processing"].fillna(0)
        + df["commission_transfer_payments"].fillna(0)
        + df["commission_category"].fillna(0)
        + df["commission_delivery"].fillna(0)
        + df["markup_custom_delivery"].fillna(0)
    )

    # Фактическая прибыль
    cancelled_statuses = {
        "Отменен при обработке",
        "Полный возврат принят на складе",
        "Заказ отменен до обработки",
    }

    def calc_actual_profit(row):
        if pd.isna(row["date_vyplat"]):
            return 0.0
        if (
            row["margin_report_status"] in cancelled_statuses
            or row["margin_report_payment_status"] == "Не будет переведён из-за отмены заказа"
        ):
            return float(row["sum_vyplat"])
        if row["margin_report_payment_status"] == "Будет переведён":
            return float(row["sum_vyplat"])
        return float(row["sum_vyplat"]) - float(row["socket_adapter_fee_total"]) - float(row["ff_fee_total"]) - float(row["base_price_total"])

    df["actual_profit"] = df.apply(calc_actual_profit, axis=1)

    return df


def get_display_columns() -> list[str]:
    """Порядок колонок для отображения в таблице."""
    return [
        "created_at",
        "shipment_date",
        "seller_name",
        "order_id_str",
        "offer_id",
        "product_name",
        "effective_order_status",
        "margin_report_status",
        "margin_report_payment_status",
        "item_count",
        "supplier_name",
        "base_price_total",
        "ff_fee_total",
        "socket_adapter_fee_total",
        "price_with_margin",
        "margin_percent",
        "final_price_total",
        "margin_value",
        "buyer_price_subsidy_total",
        "sum_bonus_points",
        "market_services",
        "price_diff",
        "commission_calc",
        "sum_promo_discount",
        "e72_e20_e21",
        "e72_e20_e21_minus_e73",
        "margin_percent_calc",
        "avg_e72",
        "e72_minus_e73",
        "seller_cancel_fee",
        "late_ship_fee",
        "conditional_e72",
        "sum_vyplat",
        "date_vyplat",
        "actual_profit",
    ]
