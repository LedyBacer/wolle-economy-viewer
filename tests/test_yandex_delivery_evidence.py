"""Независимая сверка фактических списаний с кандидатами тарифов UNI."""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

ROWS = json.loads((Path(__file__).parent / "fixtures/yandex_crossborder_20260930.json").read_text())


def matches(fee, fixed, rate, step):
    fee, fixed, rate, step = map(lambda value: Decimal(str(value)), (fee, fixed, rate, step))
    weight = ((fee - fixed) / rate / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    return abs(fixed + rate * weight - fee) < Decimal(".01")


@pytest.mark.parametrize("row", ROWS, ids=lambda row: str(row["order_id"]))
def test_actual_charge_matches_uni_express_gram_grid(row):
    assert matches(row["cross_border_fee"], 193, 686, ".001")


def test_other_tariffs_do_not_explain_the_sample():
    for fixed, rate, step in [(193,444,".001"), (193,895,".001"), (234,1515,".1")]:
        assert sum(matches(row["cross_border_fee"], fixed, rate, step) for row in ROWS) < len(ROWS) / 10


def test_current_feed_weight_is_not_the_billed_weight():
    comparable = [row for row in ROWS if row["feed_weight"] and row["quantity"] == 1]
    exact = sum((Decimal(193) + Decimal(686) * Decimal(row["feed_weight"])).quantize(Decimal(".01"))
                == Decimal(row["cross_border_fee"]) for row in comparable)
    assert exact == 1
