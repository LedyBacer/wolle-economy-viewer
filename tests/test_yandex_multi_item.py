import pytest

from wolle_economy.domain.economics import calc_economics,aggregate_yandex_orders
from conftest import make_multi_item_order


def test_multi_item_order_preserves_gross_and_costs_once():
    source = make_multi_item_order(promo_discounts=-120,boost_wallet_spend=-30)
    rows = calc_economics(source)
    assert rows.sell_price.sum() == source.sell_price.iloc[0]
    assert rows.market_services.sum() == source.market_services.iloc[0]
    assert rows.promo_discounts.sum() == -120
    assert rows.boost_wallet_spend.sum() == -30
    expected = source.sell_price.iloc[0]-source.market_services.iloc[0]-150-rows.our_costs.sum()
    assert rows.profit.sum() == pytest.approx(expected)
    order = aggregate_yandex_orders(rows).iloc[0]
    assert order.profit == pytest.approx(expected)
    assert order.our_costs == rows.our_costs.sum()
    assert order.margin_fact_on_cost_pct == pytest.approx(round(expected/rows.effective_purchase_total.sum()*100,2))


def test_wallet_sku_amounts_are_not_redistributed():
    source = make_multi_item_order(promo_discounts=-120,wallet_promo_available=True)
    source["wallet_promo_discounts"] = [-20,-100]
    rows = calc_economics(source)
    assert rows.promo_discounts.tolist() == [-20,-100]


def test_report_fee_breakdown_is_allocated_consistently():
    source = make_multi_item_order(market_services=300,report_service_details={"placement":250,"transfer":50})
    rows = calc_economics(source)
    assert rows.fact_category_fee.sum() == pytest.approx(250)
    assert rows.fact_transfer_fee.sum() == pytest.approx(50)
    assert rows.fact_commissions.sum() == pytest.approx(300)


def test_five_real_multi_item_orders_reconcile_without_duplicate_revenue():
    import json
    import pandas as pd
    from pathlib import Path
    rows = pd.DataFrame(json.loads((Path(__file__).parent/'fixtures/yandex_multi_source_20261007.json').read_text()))
    expected = {62527350787:4363.71,62358261187:-5.55,62061729729:152.108896,62003818947:195.74314,61985005186:9152.77}
    result = aggregate_yandex_orders(calc_economics(rows))
    assert len(result) == 5
    for _,row in result.iterrows():
        assert row.profit == pytest.approx(expected[row.order_id],abs=.00001)


def _complete_shipping_snapshot():
    return {
        'calculation_version':'yandex-v2-full-fees',
        'source':{'purchase_price_rub':'1000'},
        'margin':{'markup_percent':'20'},
        'prices':{'target_price':'3000','minimum_allowed_price':'3000'},
        'decision':{'metadata':{'cross_border_fixed_per_order':'193'}},
        'components':[{'code':code,'amount':amount} for code,amount in
                      [('margin','200'),('cross_border','879'),('category_commission','600'),
                       ('transfer_commission','69'),('accepting_payment','.12'),('ff','50')]],
    }


def test_quantity_does_not_multiply_per_order_and_per_sku_fixed_fees():
    from conftest import make_orders
    source = make_orders(quantity=3,pricing_snapshot=_complete_shipping_snapshot())
    row = calc_economics(source).iloc[0]
    # Весовая часть 686 за штуку; оформление 193 один раз на заказ.
    assert row.calc_delivery_fee_total == 686*3+193
    assert row.calc_accepting_payment_fee_total == pytest.approx(.12)
    assert row.expected_profit == pytest.approx((3000-1000-879-600-69-.12-50)*3+193*2+.12*2)


def test_multiple_skus_share_one_shipping_fixed_fee():
    source = make_multi_item_order(pricing_snapshot=_complete_shipping_snapshot())
    rows = calc_economics(source)
    assert rows.calc_delivery_fee_total.sum() == pytest.approx(686*3+193)
    assert rows.calc_accepting_payment_fee_total.sum() == pytest.approx(.24)
    source['offer_id'] = 'SAME-SKU'
    rows = calc_economics(source)
    assert rows.calc_accepting_payment_fee_total.sum() == pytest.approx(.12)
