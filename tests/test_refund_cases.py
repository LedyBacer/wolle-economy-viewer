from decimal import Decimal
import pandas as pd
import pytest
from wolle_economy.domain.economics import apply_refund_cases


def row(profit=800, purchase=1000):
    return pd.DataFrame(
        [
            {
                "seller_id": 1,
                "order_id_str": "order",
                "offer_id": "offer",
                "quantity": 1,
                "profit": profit,
                "actual_profit": profit,
                "profit_no_promo": profit,
                "effective_purchase_total": 1000,
                "base_purchase_expensed": purchase,
                "is_returned": False,
            }
        ]
    )


def item(stage):
    return {
        "seller_id": 1,
        "order_number": "order",
        "offer_id": "offer",
        "requires_return": True,
        "stage": stage,
        "purchase_cost": 1000,
        "procurement_cost": 1000,
    }


def operation(amount=300, method="external", state="posted"):
    return {
        "id": "op",
        "case_id": "case",
        "split_order_id": 1,
        "seller_id": 1,
        "order_number": "order",
        "offer_id": "offer",
        "allocated_amount": amount,
        "amount": amount,
        "rub_amount": amount,
        "currency": "RUB",
        "payer": "company",
        "state": state,
        "method": method,
    }


@pytest.mark.parametrize(
    "stage,refund,delivery,expected",
    [
        ("stocked", 2000, 0, -200),
        ("stocked", 2000, 100, -300),
        ("defective", 2000, 0, -1200),
        ("defective", 2000, 100, -1300),
    ],
)
def test_control_examples(stage, refund, delivery, expected):
    ops = [operation(refund)]
    if delivery:
        op = operation(delivery)
        op["id"] = "delivery"
        ops.append(op)
    result = apply_refund_cases(row(), [item(stage)], ops, []).iloc[0]
    assert result["profit"] == expected


def test_compensation_without_goods_does_not_recover_inventory():
    result = apply_refund_cases(row(), [], [operation()], []).iloc[0]
    assert result["profit"] == 500
    assert result["inventory_recovery_amount"] == 0


def test_unknown_marketplace_coverage_is_not_zero_profit():
    result = apply_refund_cases(row(), [], [operation(method="marketplace")], []).iloc[
        0
    ]
    assert pd.isna(result["profit"])
    assert result["after_sales_state"] == "needs_reconciliation"


def test_report_refund_is_not_subtracted_twice_and_changes_need_review():
    match = {
        "operation_id": "op",
        "amount": 300,
        "source_snapshot": {"fingerprint": "same"},
        "current_fingerprint": "same",
        "current_coverage": "included",
        "current_amount": 300,
    }
    assert (
        apply_refund_cases(
            row(500), [], [operation(method="marketplace")], [match]
        ).iloc[0]["profit"]
        == 500
    )
    match["current_fingerprint"] = "changed"
    assert pd.isna(
        apply_refund_cases(
            row(500), [], [operation(method="marketplace")], [match]
        ).iloc[0]["profit"]
    )


def test_native_removed_purchase_is_expensed_for_defect_only_once():
    assert (
        apply_refund_cases(row(-200, 0), [item("defective")], [], []).iloc[0]["profit"]
        == -1200
    )
    assert (
        apply_refund_cases(row(-1200, 1000), [item("defective")], [], []).iloc[0][
            "profit"
        ]
        == -1200
    )


def test_plan_is_separate_from_actual_and_customer_pays_no_cost():
    result = apply_refund_cases(row(), [], [operation(state="planned")], []).iloc[0]
    assert result["profit"] == 800 and result["projected_profit"] == 500
    op = operation()
    op["payer"] = "customer"
    assert apply_refund_cases(row(), [], [op], []).iloc[0]["profit"] == 800


def test_missing_procurement_and_partial_ambiguous_native_cost_fail_closed():
    it = item("stocked")
    it["purchase_cost"] = None
    it["procurement_cost"] = None
    f = row()
    f["effective_purchase_total"] = None
    assert pd.isna(apply_refund_cases(f, [it], [], []).iloc[0]["profit"])
    f = row(purchase=500)
    f["quantity"] = 2
    assert pd.isna(apply_refund_cases(f, [item("stocked")], [], []).iloc[0]["profit"])


def test_zero_filled_native_cost_does_not_become_known_procurement():
    it = item("stocked")
    it["purchase_cost"] = None
    it["procurement_cost"] = None
    frame = row(purchase=0)
    frame["effective_purchase_total"] = 0
    assert pd.isna(apply_refund_cases(frame, [it], [], []).iloc[0]["profit"])
    it["purchase_cost"] = 0
    assert apply_refund_cases(frame, [it], [], []).iloc[0]["profit"] == 800


def test_plan_fallback_is_explicit_and_original_sales_plan_is_preserved():
    it = item("stocked")
    it["purchase_cost"] = None
    it["procurement_cost"] = None
    frame = row()
    frame["expected_profit"] = 800
    result = apply_refund_cases(frame, [it], [operation()], []).iloc[0]
    assert result["after_sales_cost_estimated"]
    assert result["expected_profit"] == 800


def test_foreign_currency_without_saved_conversion_has_no_exact_profit():
    op = operation()
    op["currency"] = "USD"
    op["rub_amount"] = None
    assert pd.isna(apply_refund_cases(row(), [], [op], []).iloc[0]["profit"])


def test_compensation_retains_purchase_even_if_native_refund_removed_it():
    it = item("not_required")
    it["requires_return"] = False
    it["split_order_id"] = 1
    other = {**it, "case_id": "second"}
    result = apply_refund_cases(
        row(profit=1800, purchase=0), [it, other], [operation()], []
    ).iloc[0]
    assert result["profit"] == 500
    assert result["inventory_profit_adjustment"] == -1000
    assert result["inventory_recovery_amount"] == 0


def test_physical_result_wins_when_other_compensation_case_has_same_unit():
    physical = {**item("stocked"), "split_order_id": 1}
    compensation = {
        **item("not_required"),
        "split_order_id": 1,
        "requires_return": False,
    }
    result = apply_refund_cases(
        row(), [physical, compensation], [operation()], []
    ).iloc[0]
    assert result["profit"] == 1500
    assert result["inventory_recovery_amount"] == 1000


def test_mixed_parcel_and_shipping_are_counted_once_for_multiple_units():
    frame = row(profit=1600, purchase=2000)
    frame["quantity"] = 2
    frame["effective_purchase_total"] = 2000
    good = {**item("stocked"), "split_order_id": 1}
    defect = {**item("defective"), "split_order_id": 2}
    ops = []
    for unit in (1, 2):
        ops.append(
            {**operation(4000), "split_order_id": unit, "allocated_amount": 2000}
        )
        ops.append(
            {
                **operation(100),
                "id": "shipping",
                "split_order_id": unit,
                "allocated_amount": 50,
            }
        )
    result = apply_refund_cases(frame, [good, defect], ops, []).iloc[0]
    assert result["profit"] == -1500
    assert result["after_sales_expense"] == 4100
    assert result["inventory_recovery_amount"] == 1000
    assert result["inventory_loss_amount"] == 1000


def test_conflicting_frozen_costs_for_same_unit_require_review():
    first = {**item("not_required"), "split_order_id": 1, "requires_return": False}
    changed = {**first, "purchase_cost": 1100}
    result = apply_refund_cases(row(), [first, changed], [operation()], []).iloc[0]
    assert pd.isna(result["profit"])


def test_replacement_cost_and_supplier_reimbursement_have_opposite_effect():
    cost = operation(amount="1000")
    cost["kind"] = "replacement_cost"
    assert apply_refund_cases(row(), [], [cost], []).iloc[0]["profit"] == -200
    reimbursement = operation(amount="200")
    reimbursement["kind"] = "supplier_reimbursement"
    assert apply_refund_cases(row(), [], [reimbursement], []).iloc[0]["profit"] == 1000
    reimbursement["state"] = "planned"
    result = apply_refund_cases(row(), [], [reimbursement], []).iloc[0]
    assert result["profit"] == 800 and result["projected_profit"] == 1000


def test_commission_covered_by_report_is_not_added_twice():
    incoming = operation(amount="300", method="marketplace")
    incoming["kind"] = "commission_refund"
    match = {
        "operation_id": incoming["id"],
        "amount": "300",
        "source_snapshot": {"fingerprint": "a"},
        "current_fingerprint": "a",
        "current_coverage": "included",
        "current_amount": "300",
    }
    assert (
        apply_refund_cases(row(profit=1100), [], [incoming], [match]).iloc[0]["profit"]
        == 1100
    )
    assert pd.isna(apply_refund_cases(row(), [], [incoming], []).iloc[0]["profit"])


def test_commission_external_transfer_does_not_prove_native_report_coverage():
    incoming = operation(amount="300")
    incoming["kind"] = "commission_refund"
    assert pd.isna(apply_refund_cases(row(), [], [incoming], []).iloc[0]["profit"])


def test_unknown_cost_of_replacement_never_becomes_zero_expense():
    returned = item("not_required")
    returned["replacement_cost_unknown"] = True
    assert pd.isna(apply_refund_cases(row(), [returned], [], []).iloc[0]["profit"])


def test_receipts_are_displayed_separately_from_gross_expenses():
    incoming = operation(amount="300")
    incoming["kind"] = "supplier_reimbursement"
    r = apply_refund_cases(row(), [], [incoming], []).iloc[0]
    assert r["after_sales_gross_expense"] == 0 and r["after_sales_reimbursement"] == 300
    assert r["after_sales_expense"] == -300 and r["profit"] == 1100
