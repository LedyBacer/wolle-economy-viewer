"""Тесты формул и нормализации юнит-экономики Sportmaster."""

import pandas as pd
import pytest

from wolle_economy.domain.economics_sm import calc_sm_economics
from wolle_economy.db.queries import build_sm_order_items_query
from wolle_economy.ui.components.orders.table_sm import _SM_ALL_COLUMNS

_SM_BASE_ROW: dict = {
    "sm_order_id": 7001,
    "item_id": 7001,
    "order_id": "SM-7001",
    "created_at": "2025-01-10T09:00:00+00:00",
    "date_realization": "2025-01-12T12:00:00+00:00",
    "order_status": "DELIVERED",
    "fulfillment_status": "Доставлен",
    "offer_id": "SM-OFFER-1",
    "product_name": "Тестовый товар SM",
    "quantity": 2,
    "seller_id": 1,
    "seller_name": "Sportmaster",
    "supplier_name": "SM Supplier",
    "shipment_date": "2025-01-11T06:00:00+00:00",
    "base_price": 1000.0,
    "supplier_price_fact": 900.0,
    "ff_fee": 50.0,
    "socket_adapter_fee": 20.0,
    "delivery_fee": 100.0,
    "margin_price": 1600.0,
    "margin_price_total": 3200.0,
    "sell_price": 3400.0,
    "expected_payout": 2600.0,
    "expected_profit": 500.0,
    "profit": 450.0,
    "payout_if_paid": 2550.0,
    "diff_from_min_price": 100.0,
    "refund_quantity": 0,
}


def make_sm_orders(**overrides) -> pd.DataFrame:
    return pd.DataFrame([{**_SM_BASE_ROW, **overrides}])


def test_mapping_and_aliases() -> None:
    df = calc_sm_economics(make_sm_orders())
    assert df["ya_order_id"].iloc[0] == df["sm_order_id"].iloc[0]
    assert df["channel"].iloc[0] == "sportmaster"
    assert df["seller_name"].iloc[0] == "Sportmaster"


def test_fact_purchase_price_used() -> None:
    df = calc_sm_economics(make_sm_orders(supplier_price_fact=800.0, quantity=3))
    assert df["effective_purchase_total"].iloc[0] == pytest.approx(2400.0)
    assert df["uses_fact_purchase_price"].iloc[0] == True  # noqa: E712


def test_fact_purchase_price_fallback() -> None:
    df = calc_sm_economics(make_sm_orders(supplier_price_fact=0.0, quantity=3, base_price=700.0))
    assert df["effective_purchase_total"].iloc[0] == pytest.approx(2100.0)
    assert df["uses_fact_purchase_price"].iloc[0] == False  # noqa: E712


def test_payment_status_and_actual_profit_paid() -> None:
    df = calc_sm_economics(make_sm_orders(date_realization="2025-01-12T12:00:00+00:00", profit=777.0))
    assert df["payment_status"].iloc[0] == "Переведён"
    assert df["actual_profit"].iloc[0] == pytest.approx(777.0)
    assert pd.notna(df["last_payment_date"].iloc[0])


def test_payment_status_and_actual_profit_unpaid() -> None:
    df = calc_sm_economics(make_sm_orders(date_realization=None, profit=777.0))
    assert pd.isna(df["payment_status"].iloc[0])
    assert df["actual_profit"].iloc[0] == pytest.approx(0.0)


def test_cancelled_and_returned_flags() -> None:
    cancelled = calc_sm_economics(make_sm_orders(fulfillment_status="Отменен", refund_quantity=0))
    assert cancelled["is_cancelled_before"].iloc[0] == True  # noqa: E712
    assert cancelled["is_cancelled_any"].iloc[0] == True  # noqa: E712

    returned = calc_sm_economics(make_sm_orders(fulfillment_status="Отказ при получении", refund_quantity=1))
    assert returned["is_returned"].iloc[0] == True  # noqa: E712
    assert returned["is_cancelled_any"].iloc[0] == True  # noqa: E712
    assert returned["is_delivered"].iloc[0] == False  # noqa: E712


def test_lags_and_margin_fields_exist() -> None:
    df = calc_sm_economics(make_sm_orders())
    assert "ship_lag_days" in df.columns
    assert "pay_lag_days" in df.columns
    assert "margin_plan_pct" in df.columns
    assert "margin_fact_pct" in df.columns
    assert pd.notna(df["ship_lag_days"].iloc[0])


def test_reference_fields_exist() -> None:
    df = calc_sm_economics(make_sm_orders(profit_unit=225.0))

    assert df["supplier_price_fact_total"].iloc[0] == pytest.approx(1800.0)
    assert df["sm_profit_on_purchase_pct"].iloc[0] == pytest.approx(22.5)


def test_show_all_columns_include_datalens_reference_fields() -> None:
    expected = {
        "date_realization",
        "supplier_price_fact_total",
        "category_fee_percent",
        "agent_rate_percent",
        "logistic",
        "modifier_price",
        "sm_profit_on_purchase_pct",
        "seller_price_unit",
        "profit_unit",
        "payout_if_paid",
    }

    assert expected.issubset(_SM_ALL_COLUMNS)


def test_sm_query_matches_datalens_row_grouping() -> None:
    sql, _ = build_sm_order_items_query()

    assert str(sql).lstrip().startswith("SELECT DISTINCT * FROM")
