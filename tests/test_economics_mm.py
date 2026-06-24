"""
Тесты формул юнит-экономики МегаМаркет.
Все DataFrame синтетические — БД не используется.
"""

import pandas as pd
import pytest

from wolle_economy.db.queries import (
    build_mm_dbs_order_items_query,
    build_mm_poizon_order_items_query,
)
from wolle_economy.domain.economics_mm import calc_mm_economics
from wolle_economy.enums import (
    MM_FULFILLMENT_STATUS_CANCELLED,
    MM_FULFILLMENT_STATUS_DELIVERED,
    MM_FULFILLMENT_STATUS_NOT_DELIVERED,
    MM_FULFILLMENT_STATUS_RETURNED,
)
from wolle_economy.ui.columns import MM_DISPLAY_COLUMNS
from wolle_economy.ui.components.orders.table_mm import _MM_MAIN_COLUMNS

# ---------------------------------------------------------------------------
# Базовый шаблон строки MM-заказа
# ---------------------------------------------------------------------------
_MM_BASE_ROW: dict = {
    "mm_order_id": 5001,
    "order_id": "5001",
    "item_id": 101,
    "created_at": "2024-06-01T10:00:00+00:00",
    "delivered_at": "2024-06-05T14:00:00+00:00",
    "seller_id": 8,
    "seller_name": "TestMM",
    "offer_id": "MM-OFFER-1",
    "product_name": "Тестовый товар ММ",
    "quantity": 1,
    "base_price": 1000.0,
    "price": 2000.0,
    "final_price": 1800.0,
    "margin_pct_raw": 30.0,
    "min_sell_price": 1500.0,
    "cdek_status": "DELIVERED",
    "item_status": "delivered",
    "fulfillment_status": MM_FULFILLMENT_STATUS_DELIVERED,
    "payment_status": "Переведён",
    "incentive_amount": 200.0,  # price(2000) - final_price(1800)
    "market_services": 300.0,
    "promo_discounts": 0.0,
    "bonus_from_mm": 0.0,
    "delivery_cost": 0.0,
    "cdek_delivery_cost": 0.0,
    "return_delivery_cost": 0.0,
    "supplier_price_fact": 0.0,
    "ff_fee": 50.0,
    "socket_adapter_fee": 0.0,
    "fr_net_payout": 0.0,
    "channel": "dbs",
}


def make_mm_orders(**overrides) -> pd.DataFrame:
    row = {**_MM_BASE_ROW, **overrides}
    return pd.DataFrame([row])


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestMMDelivered:
    """Доставленный заказ — базовый сценарий."""

    def test_profit(self):
        df = calc_mm_economics(make_mm_orders())
        # sell_price = price(2000) + delivery(0) = 2000
        # incentive = price(2000) - final_price(1800) = 200, VAT 20% → 40
        # expected_payout = 2000 - 300 - 40 = 1660
        # our_costs = base_price(1000) + packaging(50)
        # profit = 1660 - 1050 = 610
        assert df["profit"].iloc[0] == pytest.approx(610.0)

    def test_expected_payout(self):
        df = calc_mm_economics(make_mm_orders())
        # sell_price(2000) - market_services(300) - vat_on_incentive(40) = 1660
        assert df["expected_payout"].iloc[0] == pytest.approx(1660.0)

    def test_our_costs(self):
        df = calc_mm_economics(make_mm_orders())
        assert df["our_costs"].iloc[0] == pytest.approx(1050.0)

    def test_packaging_and_adapter_are_included(self):
        df = calc_mm_economics(make_mm_orders(ff_fee=60.0, socket_adapter_fee=25.0))

        assert df["ff_fee_total"].iloc[0] == pytest.approx(60.0)
        assert df["socket_adapter_total"].iloc[0] == pytest.approx(25.0)
        assert df["our_costs"].iloc[0] == pytest.approx(1085.0)
        assert df["profit"].iloc[0] == pytest.approx(575.0)

    def test_is_delivered(self):
        df = calc_mm_economics(make_mm_orders())
        assert df["is_delivered"].iloc[0]
        assert not df["is_cancelled_any"].iloc[0]

    def test_margin_pct(self):
        df = calc_mm_economics(make_mm_orders())
        # margin_pct = profit(610) / sell_price(2000) * 100 = 30.5%
        assert df["margin_pct"].iloc[0] == pytest.approx(30.5)

    def test_take_rate(self):
        df = calc_mm_economics(make_mm_orders())
        # take_rate = market_services(300) / sell_price(2000) * 100 = 15%
        assert df["take_rate_pct"].iloc[0] == pytest.approx(15.0)

    def test_payout_if_paid_uses_financial_report(self):
        # fr_net_payout=1500 → payout_if_paid = 1500 (из фин. отчёта, не expected)
        df = calc_mm_economics(make_mm_orders(fr_net_payout=1500.0))
        assert df["payout_if_paid"].iloc[0] == pytest.approx(1500.0)

    def test_payout_if_paid_zero_when_no_report(self):
        # fr_net_payout=0 → payout_if_paid = 0
        df = calc_mm_economics(make_mm_orders(fr_net_payout=0.0))
        assert df["payout_if_paid"].iloc[0] == pytest.approx(0.0)


class TestMMCancelled:
    """Заказ отменён до отгрузки — расходы не понесены."""

    def test_profit_zero(self):
        df = calc_mm_economics(make_mm_orders(
            fulfillment_status=MM_FULFILLMENT_STATUS_CANCELLED,
            cdek_status="CANCELLED",
            payment_status=None,
            market_services=0.0,
            delivered_at=None,
        ))
        # sell_price = 0 (not delivered), our_costs = 0 (cancelled)
        assert df["profit"].iloc[0] == pytest.approx(0.0)
        assert df["our_costs"].iloc[0] == pytest.approx(0.0)

    def test_flags(self):
        df = calc_mm_economics(make_mm_orders(
            fulfillment_status=MM_FULFILLMENT_STATUS_CANCELLED,
            cdek_status="CANCELLED",
        ))
        assert df["is_cancelled_before"].iloc[0]
        assert not df["is_delivered"].iloc[0]


class TestMMNotDelivered:
    """Не доставлен (возврат отправителю) — расходы на доставку понесены."""

    def test_profit_is_negative_return_cost(self):
        df = calc_mm_economics(make_mm_orders(
            fulfillment_status=MM_FULFILLMENT_STATUS_NOT_DELIVERED,
            cdek_status="NOT_DELIVERED",
            payment_status=None,
            market_services=0.0,
            return_delivery_cost=350.0,
            delivered_at=None,
        ))
        # sell_price = 0, our_costs = return_delivery_cost(350) + packaging(50)
        assert df["profit"].iloc[0] == pytest.approx(-400.0)
        assert df["our_costs"].iloc[0] == pytest.approx(400.0)

    def test_flags(self):
        df = calc_mm_economics(make_mm_orders(
            fulfillment_status=MM_FULFILLMENT_STATUS_NOT_DELIVERED,
            cdek_status="NOT_DELIVERED",
        ))
        assert df["is_returned"].iloc[0]
        assert not df["is_delivered"].iloc[0]


class TestMMReturned:
    """Возврат покупателем — товар вернулся."""

    def test_profit(self):
        df = calc_mm_economics(make_mm_orders(
            fulfillment_status=MM_FULFILLMENT_STATUS_RETURNED,
            cdek_status="RETURNED_TO_RECIPIENT_CITY_WAREHOUSE",
            payment_status=None,
            return_delivery_cost=400.0,
            delivered_at=None,
        ))
        # sell_price = 0, our_costs = return_delivery_cost(400) + packaging(50)
        assert df["profit"].iloc[0] == pytest.approx(-450.0)


class TestMMSupplierPriceFact:
    """Фактическая закупочная цена."""

    def test_fact_price_used(self):
        df = calc_mm_economics(make_mm_orders(supplier_price_fact=800.0))
        # effective_purchase = 800 (not 1000)
        assert df["effective_purchase_total"].iloc[0] == pytest.approx(800.0)
        assert df["uses_fact_purchase_price"].iloc[0]
        # profit = expected_payout(1660) - purchase(800) - packaging(50) = 810
        assert df["profit"].iloc[0] == pytest.approx(810.0)

    def test_fact_price_zero_fallback(self):
        df = calc_mm_economics(make_mm_orders(supplier_price_fact=0.0))
        assert df["effective_purchase_total"].iloc[0] == pytest.approx(1000.0)
        assert not df["uses_fact_purchase_price"].iloc[0]


class TestMMPromo:
    """Промо-расходы."""

    def test_promo_reduces_profit(self):
        df = calc_mm_economics(make_mm_orders(promo_discounts=-150.0))
        # profit = expected_payout(1660) + promo(-150) - our_costs(1050) = 460
        assert df["profit"].iloc[0] == pytest.approx(460.0)
        # profit_no_promo = 1660 - 1050 = 610
        assert df["profit_no_promo"].iloc[0] == pytest.approx(610.0)


class TestMMQuantity:
    """Количество > 1."""

    def test_quantity_2(self):
        df = calc_mm_economics(make_mm_orders(quantity=2))
        # base_price_total = 1000 * 2 = 2000
        assert df["base_price_total"].iloc[0] == pytest.approx(2000.0)
        # effective_purchase_total = 2000 (fallback)
        assert df["effective_purchase_total"].iloc[0] == pytest.approx(2000.0)
        # our_costs = purchase(2000) + packaging(50 × 2)
        assert df["our_costs"].iloc[0] == pytest.approx(2100.0)

    def test_quantity_2_with_fact_price(self):
        df = calc_mm_economics(make_mm_orders(quantity=2, supplier_price_fact=800.0))
        assert df["effective_purchase_total"].iloc[0] == pytest.approx(1600.0)


class TestMMPoizon:
    """Poizon-канал."""

    def test_poizon_delivered(self):
        df = calc_mm_economics(make_mm_orders(
            channel="poizon",
            cdek_status="COMPLETED",
            supplier_price_fact=0.0,
        ))
        assert df["channel"].iloc[0] == "poizon"
        # profit = expected_payout(1660) - purchase(1000) - packaging(50) = 610
        assert df["profit"].iloc[0] == pytest.approx(610.0)


class TestMMEmpty:
    """Пустой DataFrame."""

    def test_empty_returns_empty(self):
        empty = pd.DataFrame()
        result = calc_mm_economics(empty)
        assert result.empty


class TestMMYaOrderIdAlias:
    """ya_order_id алиас для совместимости."""

    def test_alias_exists(self):
        df = calc_mm_economics(make_mm_orders())
        assert "ya_order_id" in df.columns
        assert df["ya_order_id"].iloc[0] == df["mm_order_id"].iloc[0]


@pytest.mark.parametrize(
    "query_builder",
    [build_mm_dbs_order_items_query, build_mm_poizon_order_items_query],
)
def test_mm_queries_load_packaging_and_adapter(query_builder) -> None:
    sql, _ = query_builder()
    query = str(sql)

    assert "COALESCE(i.markup_ff_fees_amount, 50) AS ff_fee" in query
    assert "COALESCE(i.markup_socket_adapter_fee_amount, 0) AS socket_adapter_fee" in query


def test_packaging_and_adapter_are_in_default_table_and_export() -> None:
    for column in ("ff_fee_total", "socket_adapter_total"):
        assert column in MM_DISPLAY_COLUMNS
        assert column in _MM_MAIN_COLUMNS
