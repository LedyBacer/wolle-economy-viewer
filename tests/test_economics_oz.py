"""Тесты формул и нормализации юнит-экономики Ozon."""

import pandas as pd
import pytest

from wolle_economy.db.queries import build_oz_order_items_query
from wolle_economy.domain.economics_oz import calc_oz_economics
from wolle_economy.ui.components.orders.table_oz import _OZ_ALL_COLUMNS, _OZ_COLUMN_LABELS

_OZ_BASE_ROW: dict = {
    "oz_order_id": 8001,
    "item_id": 8001,
    "order_id": "OZ-8001",
    "created_at": "2026-04-15T10:00:00+00:00",
    "shipment_date": "2026-04-16T06:00:00+00:00",
    "oz_status": "delivered",
    "seller_id": 18,
    "seller_name": "WolleTrade Ozon",
    "seller_location": "RU",
    "offer_id": "OZ-OFFER-1",
    "product_name": "Тестовый товар OZ",
    "supplier_name": "OZ Supplier",
    "fulfillment_status": "Доставлен",
    "quantity": 1,
    "base_price": 1000.0,
    "supplier_price_fact": 900.0,
    "ff_fee": 50.0,
    "socket_adapter_fee": 20.0,
    "min_sell_price": 1700.0,
    "sell_price_plan": 1680.0,
    "category_fee": 170.0,
    "acquiring_fee_plan": 90.0,
    "delivery_fee_plan": 40.0,
    "report_sell_price": 1680.0,
    "report_market_services": 300.0,
    "revenue_after_commission": 1380.0,
    "report_rows": 2,
    "return_docs": 0,
    "cancel_penalty": 0.0,
    "late_shipment_penalty": 0.0,
    "late_recommend_penalty": 0.0,
}


def make_oz_orders(**overrides) -> pd.DataFrame:
    return pd.DataFrame([{**_OZ_BASE_ROW, **overrides}])


def test_mapping_and_aliases() -> None:
    df = calc_oz_economics(make_oz_orders())
    assert df["ya_order_id"].iloc[0] == df["oz_order_id"].iloc[0]
    assert df["channel"].iloc[0] == "ozon"


def test_fact_purchase_price_used() -> None:
    df = calc_oz_economics(make_oz_orders(supplier_price_fact=800.0, quantity=2))
    assert df["effective_purchase_total"].iloc[0] == pytest.approx(1600.0)
    assert df["uses_fact_purchase_price"].iloc[0] == True  # noqa: E712


def test_delivered_profit_and_payout() -> None:
    df = calc_oz_economics(make_oz_orders())
    # income_after_fees = revenue_after_commission = 1380
    # our_costs = 900 + 50 + 20 = 970
    # profit = 410
    assert df["income_after_fees"].iloc[0] == pytest.approx(1380.0)
    assert df["our_costs"].iloc[0] == pytest.approx(970.0)
    assert df["profit"].iloc[0] == pytest.approx(410.0)
    assert df["payment_status"].iloc[0] == "Переведён"


def test_cancelled_before_flags_and_penalties() -> None:
    df = calc_oz_economics(
        make_oz_orders(
            oz_status="cancelled",
            fulfillment_status="Отменен",
            report_rows=0,
            report_sell_price=0.0,
            revenue_after_commission=0.0,
            cancel_penalty=100.0,
            late_shipment_penalty=20.0,
            late_recommend_penalty=10.0,
        )
    )
    assert df["is_cancelled_before"].iloc[0] == True  # noqa: E712
    assert df["is_returned"].iloc[0] == False  # noqa: E712
    assert df["sell_price"].iloc[0] == pytest.approx(0.0)
    assert df["profit"].iloc[0] == pytest.approx(0.0)
    assert pd.isna(df["payment_status"].iloc[0])


def test_returned_flags() -> None:
    df = calc_oz_economics(
        make_oz_orders(
            oz_status="delivered",
            fulfillment_status="Возврат",
            return_docs=1,
            report_sell_price=0.0,
            report_market_services=120.0,
            revenue_after_commission=-120.0,
        )
    )
    assert df["is_returned"].iloc[0] == True  # noqa: E712
    assert df["is_delivered"].iloc[0] == False  # noqa: E712


def test_cancelled_after_ship_profit_logic() -> None:
    df = calc_oz_economics(
        make_oz_orders(
            oz_status="cancelled",
            fulfillment_status="Отменен",
            cancelled_after_ship=True,
            order_process_fact=300.0,
            logistics_fact=200.0,
            ff_fee=50.0,
            quantity=2,
            report_rows=0,
        )
    )
    # cancelled_after_ship_profit = -logistics - order_process - ff_fee_total
    assert df["profit"].iloc[0] == pytest.approx(-600.0)


def test_reference_fields_exist() -> None:
    df = calc_oz_economics(
        make_oz_orders(
            quantity=2,
            min_price_multiplier=1.7,
            margin_price=3400.0,
            price=3360.0,
            category_fee_fact=330.0,
            acquiring_fee_fact=170.0,
            last_mile=80.0,
            last_mile_fact=75.0,
            order_process_delivery=120.0,
            order_process_delivery_fact=115.0,
        )
    )

    assert df["supplier_price_fact_total"].iloc[0] == pytest.approx(1800.0)
    assert df["profit_fact"].iloc[0] == pytest.approx(df["profit"].iloc[0])
    assert df["category_fee_fact"].iloc[0] == pytest.approx(330.0)
    assert df["order_process_delivery_fact"].iloc[0] == pytest.approx(115.0)


def test_show_all_columns_include_datalens_reference_fields() -> None:
    expected = {
        "category_fee_fact",
        "acquiring_fee_fact",
        "last_mile",
        "last_mile_fact",
        "order_process_delivery",
        "order_process_delivery_fact",
        "min_price_multiplier",
        "margin_price",
        "price",
        "revenue_after_commission",
        "profit_fact",
        "cancel_penalty",
        "late_shipment_penalty",
        "late_recommend_penalty",
    }

    assert expected.issubset(_OZ_ALL_COLUMNS)


def test_show_all_columns_have_unique_display_labels() -> None:
    labels = [_OZ_COLUMN_LABELS.get(col, col) for col in _OZ_ALL_COLUMNS]

    assert len(labels) == len(set(labels))


def test_oz_query_includes_datalens_reference_fields() -> None:
    sql, _ = build_oz_order_items_query()
    sql_text = str(sql)

    expected_aliases = {
        "category_fee_fact",
        "acquiring_fee_fact",
        "last_mile_fact",
        "order_process_delivery",
        "order_process_delivery_fact",
        "min_price_multiplier",
        "margin_price",
        "late_recommend_penalty",
    }

    for alias in expected_aliases:
        assert f"AS {alias}" in sql_text
