"""Тесты формул и нормализации юнит-экономики Wildberries."""

import pandas as pd
import pytest

from wolle_economy.domain.economics_wb import calc_wb_economics

_WB_BASE_ROW: dict = {
    "wb_order_id": 9001,
    "item_id": 9001,
    "order_id": "WB-9001",
    "created_at": "2026-04-15T10:00:00+00:00",
    "shipment_date": "2026-04-16T06:00:00+00:00",
    "wb_status": "sold",
    "seller_id": 11,
    "seller_name": "WolleTrade WB",
    "seller_location": "RU",
    "offer_id": "WB-OFFER-1",
    "product_name": "Тестовый товар WB",
    "supplier_name": "WB Supplier",
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
    "report_compensation": 0.0,
    "report_rows": 2,
    "return_docs": 0,
}


def make_wb_orders(**overrides) -> pd.DataFrame:
    return pd.DataFrame([{**_WB_BASE_ROW, **overrides}])


def test_mapping_and_aliases() -> None:
    df = calc_wb_economics(make_wb_orders())
    assert df["ya_order_id"].iloc[0] == df["wb_order_id"].iloc[0]
    assert df["channel"].iloc[0] == "wildberries"


def test_fact_purchase_price_used() -> None:
    df = calc_wb_economics(make_wb_orders(supplier_price_fact=800.0, quantity=2))
    assert df["effective_purchase_total"].iloc[0] == pytest.approx(1600.0)
    assert df["uses_fact_purchase_price"].iloc[0] == True  # noqa: E712


def test_delivered_profit_and_payout() -> None:
    df = calc_wb_economics(make_wb_orders())
    # income_after_fees = 1680 - 300 = 1380
    # our_costs = 900 + 50 + 20 = 970
    # profit = 410
    assert df["income_after_fees"].iloc[0] == pytest.approx(1380.0)
    assert df["our_costs"].iloc[0] == pytest.approx(970.0)
    assert df["profit"].iloc[0] == pytest.approx(410.0)
    assert df["payment_status"].iloc[0] == "Переведён"


def test_cancelled_before_flags_and_zero_finance() -> None:
    df = calc_wb_economics(make_wb_orders(wb_status="declined_by_client", report_rows=0))
    assert df["is_cancelled_before"].iloc[0] == True  # noqa: E712
    assert df["is_returned"].iloc[0] == False  # noqa: E712
    assert df["sell_price"].iloc[0] == pytest.approx(0.0)
    assert df["profit"].iloc[0] == pytest.approx(0.0)
    assert pd.isna(df["payment_status"].iloc[0])


def test_returned_status_uses_income_after_fees() -> None:
    df = calc_wb_economics(
        make_wb_orders(
            wb_status="canceled_by_client",
            report_sell_price=0.0,
            report_market_services=120.0,
            report_compensation=15.0,
            return_docs=1,
        )
    )
    assert df["is_returned"].iloc[0] == True  # noqa: E712
    # DataLens reference: canceled/returned statuses use income after WB fees.
    assert df["profit_no_promo"].iloc[0] == pytest.approx(-120.0)
