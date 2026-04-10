"""
Общие фикстуры для тестов.
Все DataFrame синтетические — БД не используется.
"""

import pandas as pd
import pytest

from wolle_economy.enums import FulfillmentStatus, PaymentStatus, RETURNED_STATUSES

# ---------------------------------------------------------------------------
# Базовый шаблон строки заказа
# Содержит все колонки, которые приходят из ORDER_ITEMS_SQL + PAYMENT_AGGREGATES_SQL
# после merge_with_payments().
# ---------------------------------------------------------------------------
_BASE_ROW: dict = {
    # Идентификаторы
    "ya_order_id": 1001,
    "order_id": 9001,
    "item_id": 1,
    # Товар
    "quantity": 1,
    "offer_id": "OFFER-1",
    "product_name": "Тестовый товар",
    "supplier_name": "ООО Тест",
    # Цены из ya_order_items
    "base_price": 1000.0,
    # Фактическая закупочная цена (из order_to_supplier).
    # None → fallback на base_price в _compute_base_totals.
    "supplier_price_fact": None,
    "ff_fee": 100.0,
    "socket_adapter_fee": 0.0,
    "min_sell_price": 900.0,
    "margin_percent": 10.0,
    "buyer_price": 1500.0,
    "subsidy": 0.0,
    # Расчётные комиссии
    "calc_category_fee": 150.0,
    "calc_transfer_fee": 50.0,
    "calc_delivery_fee": 80.0,
    # Из ya_order_margin_report
    "sell_price": 1500.0,
    "market_services": 280.0,
    "payment_status": PaymentStatus.TRANSFERRED,
    "fulfillment_status": FulfillmentStatus.DELIVERED,
    # Из ya_order_transactions_report
    "tr_bonuses": 0.0,
    "tr_customer_payment_date": "2024-01-15T10:00:00+00:00",
    # Из PAYMENT_AGGREGATES_SQL
    "last_payment_date": "2024-01-15T12:00:00+00:00",
    "promo_discounts": 0.0,
    "fact_commissions": 280.0,
    # Временны́е метки заказа
    "created_at": "2024-01-10T08:00:00+00:00",
    "shipment_date": "2024-01-12T10:00:00+00:00",
    # Штрафы (могут отсутствовать — доступны через df.get)
    "seller_cancel_penalty": 0.0,
    "late_ship_penalty": 0.0,
    # UI-поле
    "seller_name": "TestShop",
    # Локация магазина: 'CN' → доставка из Китая добавляется в our_costs;
    # 'RU' → доставка уже включена в market_services, не дублируем.
    "seller_location": "RU",
    "custom_delivery_fee": 0.0,
}


def make_orders(**overrides) -> pd.DataFrame:
    """
    Создаёт DataFrame из одной строки заказа.
    Все колонки берутся из _BASE_ROW; переданные kwargs перекрывают значения.
    """
    row = {**_BASE_ROW, **overrides}
    return pd.DataFrame([row])


def make_multi_item_order(**overrides) -> pd.DataFrame:
    """
    Создаёт DataFrame с двумя позициями одного заказа (ya_order_id одинаковый).
    sell_price и market_services одинаковы в обеих строках (как в реальных данных
    при JOIN с ya_order_margin_report).
    """
    row1 = {**_BASE_ROW, "item_id": 1, "offer_id": "OFFER-1", **overrides}
    row2 = {
        **_BASE_ROW,
        "item_id": 2,
        "offer_id": "OFFER-2",
        "base_price": 500.0,
        "ff_fee": 50.0,
        "quantity": 2,
        **overrides,
    }
    return pd.DataFrame([row1, row2])


# ---------------------------------------------------------------------------
# pytest-фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def delivered_order() -> pd.DataFrame:
    """Простой доставленный заказ, выплата получена."""
    return make_orders()


@pytest.fixture
def cancelled_before_ship_order() -> pd.DataFrame:
    """Заказ, отменённый до отгрузки."""
    return make_orders(
        fulfillment_status=FulfillmentStatus.CANCELLED_BEFORE_PROCESSING,
        payment_status="",
        sell_price=1500.0,
        market_services=0.0,
        last_payment_date=None,
        tr_customer_payment_date=None,
        seller_cancel_penalty=50.0,
    )


@pytest.fixture
def returned_order() -> pd.DataFrame:
    """Заказ с полным возвратом."""
    return make_orders(
        fulfillment_status=FulfillmentStatus.FULL_RETURN,
        payment_status=PaymentStatus.WITHHELD,
    )


@pytest.fixture
def unpaid_order() -> pd.DataFrame:
    """Заказ доставлен, но выплата ещё не получена."""
    return make_orders(
        payment_status="",
        last_payment_date=None,
        tr_customer_payment_date=None,
    )


@pytest.fixture
def promo_order() -> pd.DataFrame:
    """Заказ с промо-скидкой (наши расходы на промо)."""
    return make_orders(promo_discounts=-200.0)


@pytest.fixture
def multi_item_order() -> pd.DataFrame:
    """Заказ с двумя позициями (sell_price общий на весь заказ)."""
    return make_multi_item_order()


@pytest.fixture
def high_market_services_order() -> pd.DataFrame:
    """Заказ, где комиссия ЯМ превышает sell_price (edge case: expected_payout = 0)."""
    return make_orders(sell_price=100.0, market_services=200.0)


@pytest.fixture
def nan_sell_price_order() -> pd.DataFrame:
    """Заказ без данных из margin_report — sell_price рассчитывается как fallback."""
    return make_orders(sell_price=None, market_services=None)


@pytest.fixture
def fact_purchase_order() -> pd.DataFrame:
    """Заказ с фактической закупочной ценой ниже плановой (800 vs 1000)."""
    return make_orders(supplier_price_fact=800.0)


@pytest.fixture
def fact_purchase_zero_order() -> pd.DataFrame:
    """Фактическая закупочная цена = 0 → fallback на base_price."""
    return make_orders(supplier_price_fact=0.0)


@pytest.fixture
def quantity_2_order() -> pd.DataFrame:
    """Заказ с количеством = 2 (base_price_total должен удвоиться)."""
    return make_orders(quantity=2)


def make_partial_return_order(**overrides) -> pd.DataFrame:
    """
    Создаёт DataFrame с частичным возвратом: quantity=2, доставлена 1 шт, возвращена 1 шт.

    Значения отражают результат агрегирующего подзапроса tr в ORDER_ITEMS_SQL:
    - tr_bonuses            = сумма bonuses всех транзакций (возврат даёт 0)
    - customer_refund       = сумма customer_refund_amount (только у возвратной строки)
    - returned_sell_price   = sell_price возвратной транзакции (buyer_price + subsidy за 1 шт)
    - tr_delivered_quantity = количество не-возвратных транзакций = 1
    - sell_price            = из margin_report за обе штуки (до корректировки в economics.py)

    Числа:
        sell_price (total)  = 3000  (1500 за шт × 2)
        market_services     = 300
        returned_sell_price = 1500  (за возвращённую штуку)
        → sell_price после корректировки = 1500
        → expected_payout  = 1500 - 300 = 1200
        → our_costs        = (base_price=1000 + ff_fee=100) × delivered_qty=1 = 1100
        → profit           = 1200 - 1100 = 100
    """
    row = {
        **_BASE_ROW,
        "quantity": 2,
        "sell_price": 3000.0,       # за обе штуки из margin_report
        "market_services": 300.0,
        "fulfillment_status": FulfillmentStatus.PARTIALLY_RETURNED,
        "payment_status": PaymentStatus.TRANSFERRED,
        "tr_bonuses": 200.0,        # только из строки доставки (возврат даёт 0)
        "customer_refund": -1500.0, # только buyer_price возвращённой штуки
        "returned_sell_price": 1500.0,  # buyer_price + subsidy возвращённой штуки
        "tr_delivered_quantity": 1,
        "tr_customer_payment_date": "2024-01-15T10:00:00+00:00",
        "refund_payment_date": "2024-01-17T10:00:00+00:00",
        **overrides,
    }
    return pd.DataFrame([row])


@pytest.fixture
def partial_return_order() -> pd.DataFrame:
    """Заказ с частичным возвратом: quantity=2, доставлена 1 шт, возвращена 1 шт."""
    return make_partial_return_order()
