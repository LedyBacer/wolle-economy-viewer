"""
Тесты модуля economics.py.

Покрывают:
- все подфункции _compute_*
- calc_economics (интеграционный тест)
- edge case: multi-item заказ (quantity, повторяющийся sell_price)
- edge case: отменён до отгрузки, возврат, невыплаченный заказ
- edge case: NaN sell_price → fallback расчёт
- edge case: market_services > sell_price → expected_payout clipped to 0
- промо-скидки
- временны́е лаги
"""

import math

import pandas as pd
import pytest
from conftest import make_orders

from wolle_economy.domain.economics import (
    _compute_actual_profit,
    _compute_base_totals,
    _compute_flags_and_lags,
    _compute_payouts,
    _compute_profits,
    calc_economics,
    merge_with_payments,
)

# ===========================================================================
# _compute_base_totals
# ===========================================================================


class TestComputeBaseTotals:
    def test_single_item(self, delivered_order):
        df = delivered_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_base_totals(df, q)

        assert result["base_price_total"].iloc[0] == 1000.0
        assert result["ff_fee_total"].iloc[0] == 100.0
        assert result["socket_adapter_total"].iloc[0] == 0.0
        assert result["min_sell_price_total"].iloc[0] == 900.0

    def test_quantity_multiplier(self, quantity_2_order):
        df = quantity_2_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_base_totals(df, q)

        assert result["base_price_total"].iloc[0] == 2000.0
        assert result["ff_fee_total"].iloc[0] == 200.0
        assert result["min_sell_price_total"].iloc[0] == 1800.0

    def test_our_margin_calculation(self, delivered_order):
        """our_margin = base_price_total * margin_percent / 100"""
        df = delivered_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_base_totals(df, q)

        expected_margin = 1000.0 * 10.0 / 100  # = 100.0
        assert result["our_margin"].iloc[0] == pytest.approx(expected_margin)

    def test_price_with_margin(self, delivered_order):
        """price_with_margin = base_price_total * (1 + margin_percent / 100)"""
        df = delivered_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_base_totals(df, q)

        expected = 1000.0 * (1 + 10.0 / 100)  # = 1100.0
        assert result["price_with_margin"].iloc[0] == pytest.approx(expected)

    def test_nan_margin_treated_as_zero(self):
        df = make_orders(margin_percent=None)
        q = df["quantity"].fillna(1)
        result = _compute_base_totals(df, q)

        assert result["our_margin"].iloc[0] == 0.0
        assert result["price_with_margin"].iloc[0] == pytest.approx(1000.0)

    def test_socket_adapter_multiplied(self):
        df = make_orders(socket_adapter_fee=50.0, quantity=3)
        q = df["quantity"].fillna(1)
        result = _compute_base_totals(df, q)

        assert result["socket_adapter_total"].iloc[0] == 150.0


# ===========================================================================
# _compute_payouts
# ===========================================================================


class TestComputePayouts:
    def test_sell_price_from_margin_report(self, delivered_order):
        """sell_price берётся из margin_report, не пересчитывается."""
        df = delivered_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        assert result["sell_price"].iloc[0] == 1500.0

    def test_sell_price_fallback_when_nan(self, nan_sell_price_order):
        """Если sell_price = NaN — считаем как (buyer_price + subsidy) * quantity."""
        df = nan_sell_price_order.copy()
        q = df["quantity"].fillna(1)
        # buyer_price=1500, subsidy=0, quantity=1 → 1500.0
        result = _compute_payouts(df, q)

        assert result["sell_price"].iloc[0] == pytest.approx(1500.0)

    def test_sell_price_fallback_with_subsidy(self):
        df = make_orders(sell_price=None, buyer_price=1200.0, subsidy=300.0, quantity=2)
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        # (1200 + 300) * 2 = 3000
        assert result["sell_price"].iloc[0] == pytest.approx(3000.0)

    def test_expected_payout_normal(self, delivered_order):
        """expected_payout = sell_price - market_services."""
        df = delivered_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        # 1500 - 280 = 1220
        assert result["expected_payout"].iloc[0] == pytest.approx(1220.0)

    def test_expected_payout_clipped_to_zero(self, high_market_services_order):
        """Если market_services > sell_price — expected_payout не уходит в минус."""
        df = high_market_services_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        assert result["expected_payout"].iloc[0] == 0.0

    def test_calc_commissions_sum(self, delivered_order):
        """calc_commissions = category + transfer + delivery."""
        df = delivered_order.copy()
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        # 150 + 50 + 80 = 280
        assert result["calc_commissions"].iloc[0] == pytest.approx(280.0)

    def test_bonus_points_from_tr_bonuses(self):
        df = make_orders(tr_bonuses=75.0)
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        assert result["bonus_points"].iloc[0] == 75.0

    def test_promo_discounts_default_to_zero(self, delivered_order):
        """Если promo_discounts отсутствует в колонках — ставится 0."""
        df = delivered_order.copy().drop(columns=["promo_discounts"])
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        assert result["promo_discounts"].iloc[0] == 0.0

    def test_fact_commissions_default_to_zero(self, delivered_order):
        df = delivered_order.copy().drop(columns=["fact_commissions"])
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        assert result["fact_commissions"].iloc[0] == 0.0

    def test_promo_discounts_nan_filled(self):
        df = make_orders(promo_discounts=None)
        q = df["quantity"].fillna(1)
        result = _compute_payouts(df, q)

        assert result["promo_discounts"].iloc[0] == 0.0


# ===========================================================================
# _compute_profits
# ===========================================================================


class TestComputeProfits:
    def _setup(self, df: pd.DataFrame):
        df = df.copy()
        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        df["our_costs"] = our_costs
        return df, our_costs

    def test_expected_profit(self, delivered_order):
        """expected_profit = expected_payout - our_costs"""
        df, our_costs = self._setup(delivered_order)
        result = _compute_profits(df, our_costs)

        # expected_payout=1220, our_costs=1100 (1000+100+0)
        assert result["expected_profit"].iloc[0] == pytest.approx(120.0)

    def test_profit_no_promo(self, delivered_order):
        """profit_no_promo = expected_payout - our_costs (прomo не учитывается)."""
        df, our_costs = self._setup(delivered_order)
        result = _compute_profits(df, our_costs)

        assert result["profit_no_promo"].iloc[0] == pytest.approx(120.0)

    def test_profit_with_promo_discounts(self, promo_order):
        """profit = expected_payout + promo_discounts - our_costs."""
        df, our_costs = self._setup(promo_order)
        result = _compute_profits(df, our_costs)

        # expected_payout=1220, promo=-200, our_costs=1100 → 1220-200-1100 = -80
        assert result["profit"].iloc[0] == pytest.approx(-80.0)
        # profit_no_promo игнорирует promo → 120
        assert result["profit_no_promo"].iloc[0] == pytest.approx(120.0)

    def test_income_after_fees_promo(self, promo_order):
        """income_after_fees_promo = expected_payout + promo_discounts."""
        df, our_costs = self._setup(promo_order)
        result = _compute_profits(df, our_costs)

        # 1220 + (-200) = 1020
        assert result["income_after_fees_promo"].iloc[0] == pytest.approx(1020.0)

    def test_income_after_fees_no_promo(self, delivered_order):
        """income_after_fees = expected_payout (без promo)."""
        df, our_costs = self._setup(delivered_order)
        result = _compute_profits(df, our_costs)

        assert result["income_after_fees"].iloc[0] == pytest.approx(1220.0)

    def test_diff_from_min_price(self, delivered_order):
        """diff_from_min_price = sell_price - min_sell_price_total."""
        df, our_costs = self._setup(delivered_order)
        result = _compute_profits(df, our_costs)

        # 1500 - 900 = 600
        assert result["diff_from_min_price"].iloc[0] == pytest.approx(600.0)

    def test_profit_zero_when_breakeven(self):
        """Если sell_price - market_services == our_costs → profit = 0."""
        # our_costs = 1100, expected_payout должен тоже быть 1100
        df = make_orders(sell_price=1100.0 + 280.0, market_services=280.0, promo_discounts=0.0)
        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        result = _compute_profits(df, our_costs)

        assert result["profit"].iloc[0] == pytest.approx(0.0)


# ===========================================================================
# _compute_actual_profit
# ===========================================================================


class TestComputeActualProfit:
    def _setup(self, df: pd.DataFrame):
        df = df.copy()
        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        df["our_costs"] = our_costs
        df = _compute_profits(df, our_costs)
        return df, our_costs

    def test_payout_if_paid_when_transferred(self, delivered_order):
        """Если payment_status = TRANSFERRED → payout_if_paid = expected_payout."""
        df, our_costs = self._setup(delivered_order)
        result = _compute_actual_profit(df, our_costs)

        assert result["payout_if_paid"].iloc[0] == pytest.approx(1220.0)

    def test_payout_if_paid_zero_when_unpaid(self, unpaid_order):
        """Если выплата ещё не получена → payout_if_paid = 0."""
        df, our_costs = self._setup(unpaid_order)
        result = _compute_actual_profit(df, our_costs)

        assert result["payout_if_paid"].iloc[0] == 0.0

    def test_last_payment_date_from_tr_date(self, delivered_order):
        """tr_customer_payment_date приоритетнее last_payment_date."""
        df = delivered_order.copy()
        df["tr_customer_payment_date"] = "2024-02-01T00:00:00+00:00"
        df["last_payment_date"] = "2024-01-01T00:00:00+00:00"

        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        df = _compute_profits(df, our_costs)
        result = _compute_actual_profit(df, our_costs)

        assert result["last_payment_date"].iloc[0].month == 2  # февраль (tr_date)

    def test_last_payment_date_fallback_to_pay_date(self):
        """Если tr_customer_payment_date = NaN → используется last_payment_date."""
        df = make_orders(
            tr_customer_payment_date=None,
            last_payment_date="2024-03-05T00:00:00+00:00",
        )
        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        df = _compute_profits(df, our_costs)
        result = _compute_actual_profit(df, our_costs)

        assert result["last_payment_date"].iloc[0].month == 3  # март

    def test_actual_profit_delivered_and_paid(self, delivered_order):
        """actual_profit = expected_payout - our_costs для оплаченного заказа."""
        df, our_costs = self._setup(delivered_order)
        result = _compute_actual_profit(df, our_costs)

        # 1220 - 1100 = 120
        assert result["actual_profit"].iloc[0] == pytest.approx(120.0)

    def test_actual_profit_zero_when_not_paid(self, unpaid_order):
        """Если нет данных о выплате → actual_profit = 0."""
        df, our_costs = self._setup(unpaid_order)
        result = _compute_actual_profit(df, our_costs)

        assert result["actual_profit"].iloc[0] == 0.0

    def test_actual_profit_cancelled_before_ship(self, cancelled_before_ship_order):
        """
        Отменён до отгрузки: расходы не понесены.
        actual_profit = expected_payout - seller_cancel_penalty - late_ship_penalty.
        """
        df, our_costs = self._setup(cancelled_before_ship_order)
        # Добавляем дату, чтобы has_payment = True (иначе actual_profit = 0)
        df["last_payment_date"] = pd.to_datetime("2024-01-20T00:00:00+00:00", utc=True)

        result = _compute_actual_profit(df, our_costs)

        # expected_payout = 1500 - 0 = 1500 (market_services=0 для отменённых до отгрузки)
        # actual = 1500 - 50 (penalty) - 0 = 1450
        assert result["actual_profit"].iloc[0] == pytest.approx(1450.0)

    def test_profit_vs_expected(self, delivered_order):
        """profit_vs_expected = actual_profit - expected_profit."""
        df, our_costs = self._setup(delivered_order)
        result = _compute_actual_profit(df, our_costs)

        # actual=120, expected=120 → diff=0
        assert result["profit_vs_expected"].iloc[0] == pytest.approx(0.0)


# ===========================================================================
# _compute_flags_and_lags
# ===========================================================================


class TestComputeFlagsAndLags:
    def _full_setup(self, df: pd.DataFrame):
        df = df.copy()
        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        df["our_costs"] = our_costs
        df = _compute_profits(df, our_costs)
        df = _compute_actual_profit(df, our_costs)
        return df

    def test_is_delivered(self, delivered_order):
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        assert result["is_delivered"].iloc[0] == True  # noqa: E712
        assert result["is_cancelled_any"].iloc[0] == False  # noqa: E712

    def test_is_cancelled_before(self, cancelled_before_ship_order):
        df = self._full_setup(cancelled_before_ship_order)
        result = _compute_flags_and_lags(df)

        assert result["is_cancelled_before"].iloc[0] == True  # noqa: E712
        assert result["is_cancelled_any"].iloc[0] == True  # noqa: E712
        assert result["is_delivered"].iloc[0] == False  # noqa: E712

    def test_is_returned(self, returned_order):
        df = self._full_setup(returned_order)
        result = _compute_flags_and_lags(df)

        assert result["is_returned"].iloc[0] == True  # noqa: E712
        assert result["is_cancelled_any"].iloc[0] == True  # noqa: E712
        assert result["is_cancelled_before"].iloc[0] == False  # noqa: E712

    def test_is_loss(self, promo_order):
        """Заказ с промо-убытком → is_loss = True."""
        df = self._full_setup(promo_order)
        result = _compute_flags_and_lags(df)

        assert result["is_loss"].iloc[0] == True  # noqa: E712

    def test_is_not_loss_for_profitable_order(self, delivered_order):
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        assert result["is_loss"].iloc[0] == False  # noqa: E712

    def test_take_rate_pct(self, delivered_order):
        """take_rate_pct = market_services / sell_price * 100."""
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        # 280 / 1500 * 100 ≈ 18.67
        assert result["take_rate_pct"].iloc[0] == pytest.approx(18.67, abs=0.01)

    def test_margin_pct(self, delivered_order):
        """margin_pct = profit / sell_price * 100."""
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        # profit=120, sell_price=1500 → 8.0%
        assert result["margin_pct"].iloc[0] == pytest.approx(8.0, abs=0.01)

    def test_ship_lag_days(self, delivered_order):
        """ship_lag_days = (shipment_date - created_at) / 86400."""
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        # created: 2024-01-10 08:00, shipped: 2024-01-12 10:00 → 2д 2ч = 2.0833 дней
        assert result["ship_lag_days"].iloc[0] == pytest.approx(2.0833, abs=0.01)

    def test_pay_lag_days(self, delivered_order):
        """pay_lag_days = (last_payment_date - created_at) / 86400.
        tr_customer_payment_date (10:00) имеет приоритет над last_payment_date (12:00).
        """
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        # created: 2024-01-10 08:00, tr_payment: 2024-01-15 10:00 → 5д 2ч = 5.0833 дней
        assert result["pay_lag_days"].iloc[0] == pytest.approx(5.0833, abs=0.01)

    def test_order_id_str(self, delivered_order):
        df = self._full_setup(delivered_order)
        result = _compute_flags_and_lags(df)

        assert result["order_id_str"].iloc[0] == "9001"

    def test_take_rate_nan_when_sell_price_zero(self):
        """Если sell_price = 0 → take_rate_pct = NaN (не ZeroDivisionError)."""
        df = make_orders(sell_price=0.0, market_services=0.0)
        q = df["quantity"].fillna(1)
        df = _compute_base_totals(df, q)
        df = _compute_payouts(df, q)
        our_costs = df["base_price_total"] + df["ff_fee_total"] + df["socket_adapter_total"]
        df = _compute_profits(df, our_costs)
        df = _compute_actual_profit(df, our_costs)
        result = _compute_flags_and_lags(df)

        assert math.isnan(result["take_rate_pct"].iloc[0])


# ===========================================================================
# calc_economics — интеграционные тесты
# ===========================================================================


class TestCalcEconomicsIntegration:
    def test_returns_copy_not_mutate_original(self, delivered_order):
        original = delivered_order.copy()
        calc_economics(delivered_order)

        pd.testing.assert_frame_equal(delivered_order, original)

    def test_all_expected_columns_present(self, delivered_order):
        result = calc_economics(delivered_order)

        expected_columns = [
            "base_price_total",
            "ff_fee_total",
            "socket_adapter_total",
            "our_costs",
            "sell_price",
            "expected_payout",
            "calc_commissions",
            "bonus_points",
            "promo_discounts",
            "expected_profit",
            "profit",
            "profit_no_promo",
            "income_after_fees",
            "income_after_fees_promo",
            "diff_from_min_price",
            "payout_if_paid",
            "actual_profit",
            "profit_vs_expected",
            "is_delivered",
            "is_cancelled_before",
            "is_returned",
            "is_cancelled_any",
            "is_loss",
            "take_rate_pct",
            "margin_pct",
            "ship_lag_days",
            "pay_lag_days",
            "order_id_str",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Колонка отсутствует: {col}"

    def test_full_pipeline_delivered_order(self, delivered_order):
        result = calc_economics(delivered_order)

        assert result["our_costs"].iloc[0] == pytest.approx(1100.0)
        assert result["expected_payout"].iloc[0] == pytest.approx(1220.0)
        assert result["profit"].iloc[0] == pytest.approx(120.0)
        assert result["actual_profit"].iloc[0] == pytest.approx(120.0)
        assert result["is_delivered"].iloc[0] == True  # noqa: E712
        assert result["is_loss"].iloc[0] == False  # noqa: E712

    def test_full_pipeline_cancelled_before_ship(self, cancelled_before_ship_order):
        result = calc_economics(cancelled_before_ship_order)

        assert result["is_cancelled_before"].iloc[0] == True  # noqa: E712
        assert result["is_delivered"].iloc[0] == False  # noqa: E712
        # actual_profit = 0, т.к. нет даты выплаты
        assert result["actual_profit"].iloc[0] == 0.0

    def test_full_pipeline_returned_order(self, returned_order):
        result = calc_economics(returned_order)

        assert result["is_returned"].iloc[0] == True  # noqa: E712
        assert result["is_cancelled_any"].iloc[0] == True  # noqa: E712
        # Возврат оплачен (WITHHELD) → actual_profit = expected_payout - our_costs
        assert result["actual_profit"].iloc[0] == pytest.approx(120.0)

    def test_full_pipeline_no_nan_in_key_columns(self, delivered_order):
        """Ключевые финансовые колонки не должны содержать NaN."""
        result = calc_economics(delivered_order)

        key_cols = ["profit", "expected_profit", "our_costs", "expected_payout"]
        for col in key_cols:
            assert not result[col].isna().any(), f"NaN в колонке {col}"


# ===========================================================================
# Edge cases: multi-item заказ
# ===========================================================================


class TestMultiItemOrder:
    def test_each_row_calculated_independently(self, multi_item_order):
        """
        sell_price и market_services одинаковы для обеих позиций (из margin_report).
        calc_economics обрабатывает каждую строку независимо.
        Суммирование sell_price по заказу возлагается на caller (orders_dedup).
        """
        result = calc_economics(multi_item_order)

        # Первая позиция: base_price=1000, q=1 → base_price_total=1000
        assert result["base_price_total"].iloc[0] == pytest.approx(1000.0)
        # Вторая позиция: base_price=500, q=2 → base_price_total=1000
        assert result["base_price_total"].iloc[1] == pytest.approx(1000.0)

    def test_sell_price_identical_in_both_rows(self, multi_item_order):
        """sell_price не должен меняться — он общий для заказа."""
        result = calc_economics(multi_item_order)

        assert result["sell_price"].iloc[0] == result["sell_price"].iloc[1]

    def test_quantity_correctly_scales_costs(self, multi_item_order):
        """ff_fee_total для строки с quantity=2 должен быть в два раза больше."""
        result = calc_economics(multi_item_order)

        # Строка 0: ff_fee=100, q=1 → 100
        assert result["ff_fee_total"].iloc[0] == pytest.approx(100.0)
        # Строка 1: ff_fee=50, q=2 → 100
        assert result["ff_fee_total"].iloc[1] == pytest.approx(100.0)


# ===========================================================================
# merge_with_payments
# ===========================================================================


class TestMergeWithPayments:
    def test_merge_on_ya_order_id(self):
        orders = pd.DataFrame(
            {
                "ya_order_id": [1, 2, 3],
                "order_id": [101, 102, 103],
            }
        )
        payments = pd.DataFrame(
            {
                "ya_orders_id": [1, 2],
                "promo_discounts": [-100.0, -50.0],
            }
        )
        result = merge_with_payments(orders, payments)

        assert len(result) == 3
        assert result.loc[result["ya_order_id"] == 1, "promo_discounts"].iloc[0] == -100.0
        # ya_order_id=3 не имеет платежей → NaN
        assert math.isnan(result.loc[result["ya_order_id"] == 3, "promo_discounts"].iloc[0])

    def test_renames_ya_orders_id_column(self):
        orders = pd.DataFrame({"ya_order_id": [1]})
        payments = pd.DataFrame({"ya_orders_id": [1], "fact_commissions": [100.0]})
        result = merge_with_payments(orders, payments)

        assert "ya_order_id" in result.columns
        assert "ya_orders_id" not in result.columns
