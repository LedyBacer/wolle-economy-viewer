from decimal import Decimal
import pandas as pd
import pytest
from conftest import make_orders
from wolle_economy.domain.economics import calc_economics
from wolle_economy.domain.carrier_expenses import apply_carrier_expenses

def test_63838736834_local_correction_keeps_plan():
    source=make_orders(base_price=400,supplier_price_fact=400,ff_fee=50,custom_delivery_fee=410,
                       sell_price=1408,market_services=492.66,fact_commissions=492.66)
    before=calc_economics(source)
    after=apply_carrier_expenses(before,[dict(item_id=1,effective_legacy_unit_rub=0,correction_reason='confirmed_ru_source')])
    assert before.profit.iloc[0]==pytest.approx(55.34)
    assert after.profit.iloc[0]==pytest.approx(465.34)
    assert after.custom_delivery_fee_total.iloc[0]==410
    assert after.effective_custom_delivery_fee_total.iloc[0]==0
    assert after.expected_profit.iloc[0]==before.expected_profit.iloc[0]
    pd.testing.assert_frame_equal(before,calc_economics(source))

def test_invoice_is_not_multiplied_by_order_quantity():
    before=calc_economics(make_orders(quantity=2,base_price=400,ff_fee=50,custom_delivery_fee=0))
    after=apply_carrier_expenses(before,[dict(item_id=1,carrier_fact_amount_rub=264)])
    assert after.profit.iloc[0]==pytest.approx(before.profit.iloc[0]-264)

def test_refunded_goods_do_not_cancel_paid_carrier_invoice():
    before=calc_economics(make_orders(fulfillment_status='Возврат оформлен',quantity=2,
        tr_delivered_quantity=0,returned_sell_price=1500,custom_delivery_fee=0))
    after=apply_carrier_expenses(before,[dict(item_id=1,carrier_fact_amount_rub=264)])
    assert after.profit.iloc[0]==pytest.approx(before.profit.iloc[0]-264)

def test_legacy_partial_return_without_evidence_unchanged():
    before=calc_economics(make_orders(quantity=2,custom_delivery_fee=410,
        fulfillment_status='Частично возвращён',tr_delivered_quantity=1,returned_sell_price=100))
    after=apply_carrier_expenses(before,[])
    assert after.profit.iloc[0]==pytest.approx(before.profit.iloc[0])

def test_invoice_refund_retains_negative_net_expense():
    before=calc_economics(make_orders(custom_delivery_fee=0))
    after=apply_carrier_expenses(before,[dict(item_id=1,carrier_fact_amount_rub=-10)])
    assert after.profit.iloc[0]==pytest.approx(before.profit.iloc[0]+10)

def test_marketplace_and_direct_charges_require_reconciliation():
    before=calc_economics(make_orders(custom_delivery_fee=0))
    before['report_service_details']=[{'cross_border_delivery':'264'}]
    after=apply_carrier_expenses(before,[dict(item_id=1,carrier_fact_amount_rub=264)])
    assert after.carrier_reconciliation_required.iloc[0]
    assert after.economics_is_estimated.iloc[0]
    resolved=apply_carrier_expenses(before,[dict(item_id=1,carrier_fact_amount_rub=0,reconciliation_resolved=True)])
    assert not resolved.carrier_reconciliation_required.iloc[0]
    assert resolved.profit.iloc[0]==pytest.approx(before.profit.iloc[0])

def test_incomplete_report_not_final_profit():
    result=calc_economics(make_orders(supplier_price_fact=1000,market_services=.12,fact_commissions=.12,
        fulfillment_status='Передан в доставку',payment_status='Будет переведён'))
    assert result.economics_is_estimated.iloc[0]

def test_partial_invoice_keeps_estimate_for_unpaid_parcel():
    before=calc_economics(make_orders(quantity=2,custom_delivery_fee=0))
    before['pricing_snapshot']=[{'components':[{'code':'carrier_delivery','amount':'264'}]}]
    ev=dict(item_id=1,carrier_fact_amount_rub=250,carrier_known_amount_rub=250,carrier_known_quantity=1,carrier_fact_quantity=1,carrier_has_unpaid_parcel=False)
    after=apply_carrier_expenses(before,[ev])
    assert after.carrier_delivery_effective_total.iloc[0]==514
    assert after.carrier_expenses_estimated.iloc[0]

def test_known_consolidated_parcel_plan_replaces_two_unit_estimates():
    before=calc_economics(make_orders(quantity=2,custom_delivery_fee=0))
    before['pricing_snapshot']=[{'components':[{'code':'carrier_delivery','amount':'264'}]}]
    ev=dict(item_id=1,carrier_known_amount_rub=348,carrier_known_quantity=2,carrier_fact_quantity=0,carrier_has_unpaid_parcel=True)
    after=apply_carrier_expenses(before,[ev])
    assert after.carrier_delivery_plan_total.iloc[0]==528
    assert after.carrier_delivery_effective_total.iloc[0]==348

def test_cancelled_before_shipping_has_no_estimated_carrier_expense():
    before=calc_economics(make_orders(fulfillment_status='Отменён',custom_delivery_fee=0))
    before['pricing_snapshot']=[{'components':[{'code':'carrier_delivery','amount':'264'}]}]
    after=apply_carrier_expenses(before,[])
    assert after.carrier_delivery_effective_total.iloc[0]==0
    assert after.profit.iloc[0]==before.profit.iloc[0]
    paid=apply_carrier_expenses(before,[dict(item_id=1,carrier_fact_amount_rub=264)])
    assert paid.profit.iloc[0]==pytest.approx(before.profit.iloc[0]-264)


@pytest.mark.parametrize('prior,incomplete', [(True,False),(False,True)])
def test_mm_preserves_incomplete_economics(prior,incomplete):
    from wolle_economy.domain.carrier_expenses import apply_mm_carrier_expenses
    frame=pd.DataFrame([dict(item_id=1,quantity=1,our_costs=400,profit=100,
        profit_no_promo=100,margin_fact_rub=100,actual_profit=0,
        economics_is_estimated=prior,uses_fact_purchase_price=True,
        payment_status='Будет переведён',sell_price=500,effective_purchase_total=400,
        pricing_snapshot={'components':[], 'decision':{'metadata':{'carrier_delivery':{'incomplete':incomplete}}}})])
    result=apply_mm_carrier_expenses(frame,[])
    assert result.economics_is_estimated.iloc[0]
