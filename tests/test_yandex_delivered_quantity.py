"""Регрессия: одна строка отчёта может покрывать несколько доставленных штук."""
import pytest
from conftest import make_orders, make_partial_return_order
from wolle_economy.domain.economics import calc_economics


@pytest.mark.parametrize('reported_quantity', [1, 2, None])
@pytest.mark.parametrize('supplier_price_fact', [2384.0, None])
def test_fully_delivered_62989944387_expenses_both_units(
    reported_quantity, supplier_price_fact,
):
    df = make_orders(
        quantity=2, base_price=2384.0, supplier_price_fact=supplier_price_fact,
        ff_fee=50.0, custom_delivery_fee=420.0,
        sell_price=9982.0, market_services=758.76, fact_commissions=758.76,
        promo_discounts=-2925.01, tr_delivered_quantity=reported_quantity,
        order_status='Доставлен покупателю', returned_sell_price=0.0,
        customer_refund=0.0,
    )
    result = calc_economics(df).iloc[0]
    assert result['base_purchase_expensed'] == pytest.approx(4768.0)
    assert result['our_costs'] == pytest.approx(5708.0)
    assert result['profit'] == pytest.approx(590.23)
    assert result['actual_profit'] == pytest.approx(590.23)


@pytest.mark.parametrize('fulfillment_status', ['Частично возвращён', 'Доставлен'])
def test_return_evidence_preserves_partial_quantity(fulfillment_status):
    df = make_partial_return_order()
    df['fulfillment_status'] = fulfillment_status
    df['order_status'] = 'Частично возвращён'
    result = calc_economics(df).iloc[0]
    assert result['base_purchase_expensed'] == pytest.approx(df['base_price'].iloc[0])
