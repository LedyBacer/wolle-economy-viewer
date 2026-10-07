import json
from pathlib import Path

import pandas as pd
import pytest

from wolle_economy.domain.economics import calc_economics


ROWS = json.loads((Path(__file__).parent / "fixtures/yandex_orders_20260930.json").read_text())
EXPECTED_PROFITS = {
    61616926403: -10.76329, 60262088066: 4736.71, 60753056642: 126.578,
    60653273408: -78.73, 61393666626: 94.62, 61725442371: 73.16,
    62028170690: -63.53, 62137243906: -39.83,
}


@pytest.mark.parametrize("row", ROWS, ids=lambda row: str(row["order_id"]))
def test_historical_profit_and_plan_are_reconciled(row):
    result = calc_economics(pd.DataFrame([row])).iloc[0]
    assert result.profit == pytest.approx(EXPECTED_PROFITS[row["order_id"]], abs=.00001)
    assert result.expected_profit == pytest.approx(row["base_price"] * row["quantity"] * row["margin_percent"] / 100)
    assert result.cash_payout + result.wallet_balance_change - result.our_costs == pytest.approx(result.profit)
    assert result.full_market_services == pytest.approx(result.sell_price - result.income_after_fees_promo)
    assert not result.plan_snapshot_complete


def test_flashlight_cash_and_points_are_distinct():
    row = next(row for row in ROWS if row["order_id"] == 61616926403)
    result = calc_economics(pd.DataFrame([row])).iloc[0]
    assert result.cash_payout == pytest.approx(1570.08)
    assert result.wallet_balance_change == pytest.approx(-307.17)
    assert result.full_market_services == pytest.approx(879.09)
    assert result.margin_fact_on_cost_pct == pytest.approx(-1.32)


def test_new_publication_snapshot_replaces_notification_recalculation():
    row = dict(ROWS[0])
    row["pricing_snapshot"] = {
        "calculation_version": "yandex-v2-full-fees", "source":{"purchase_price_rub":"830.1024"},
        "margin":{"markup_percent":"8"}, "prices":{"target_price":"2292","minimum_allowed_price":"2292"},
        "components":[{"code":code,"amount":amount} for code,amount in
            [("margin","66.408192"),("ff","50"),("custom_delivery","410"),("category_commission","687.6"),
             ("transfer_commission","52.72"),("delivery","114.6"),("middle_mile","80"),("accepting_payment",".12"),("boost","0")]],
    }
    result = calc_economics(pd.DataFrame([row])).iloc[0]
    assert result.plan_snapshot_complete
    assert result.base_price == pytest.approx(830.1024)
    assert result.calc_delivery_fee_total == pytest.approx(194.6)
    assert result.expected_profit == pytest.approx(66.8576)
    assert result.custom_delivery_fee_total == 410


def test_incomplete_snapshot_does_not_crash_or_replace_historical_plan():
    row = dict(ROWS[0], pricing_snapshot={"calculation_version":"yandex-v2-full-fees"})
    result = calc_economics(pd.DataFrame([row])).iloc[0]
    assert not result.plan_snapshot_complete
    assert result.expected_profit == pytest.approx(row["base_price"] * row["margin_percent"] / 100)


def test_dashboard_decomposition_includes_boost_wallet_and_cash_is_separate():
    from wolle_economy.domain.kpis import compute_kpis
    rows = calc_economics(pd.DataFrame(ROWS))
    metrics = compute_kpis(rows)
    assert metrics.revenue-metrics.commissions-metrics.our_costs+metrics.promo+metrics.boost_wallet_spend == pytest.approx(metrics.profit)
    assert metrics.boost_wallet_spend == -182.95
    assert metrics.cash_payout == pytest.approx(rows.cash_payout.sum())
    assert metrics.cash_payout != metrics.payout
