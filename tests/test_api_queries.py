"""Точечные SQL-фильтры API экономики."""

from __future__ import annotations

import pytest

from wolle_economy.db.queries import (
    build_mm_dbs_order_items_query,
    build_mm_poizon_order_items_query,
    build_order_items_query,
    build_oz_order_items_query,
    build_payment_aggregates_query,
    build_sm_order_items_query,
    build_supplier_price_fact_query,
    build_wb_order_items_query,
)


@pytest.mark.parametrize(
    ("builder", "order_expr", "offer_expr"),
    [
        (build_order_items_query, "o.order_id", "i.offer_id"),
        (build_mm_dbs_order_items_query, "o.shipment_id", "i.offer_id"),
        (build_mm_poizon_order_items_query, "o.shipment_id", "i.offer_id"),
        (build_sm_order_items_query, "sm.order_id", "sm.offer_id"),
        (build_wb_order_items_query, "o.order_id", "o.offer_id"),
        (build_oz_order_items_query, "o.order_id", "o.offer_id"),
    ],
)
def test_order_query_has_exact_composite_filters(builder, order_expr: str, offer_expr: str) -> None:
    sql, params = builder((6,), None, None, "ORDER-1", "OFFER-1")
    query = str(sql)

    assert "seller_ids" in query
    assert f"CAST({order_expr} AS TEXT) = :order_id" in query
    assert f"CAST({offer_expr} AS TEXT) = :offer_id" in query
    assert params == {
        "seller_ids": [6],
        "order_id": "ORDER-1",
        "offer_id": "OFFER-1",
    }


def test_yandex_related_queries_are_limited_to_requested_order() -> None:
    payments_sql, payments_params = build_payment_aggregates_query((1,), None, None, "12345")
    supplier_sql, supplier_params = build_supplier_price_fact_query(
        (1,), None, None, "12345", "ABC"
    )

    assert "CAST(o2.order_id AS TEXT) = :order_id" in str(payments_sql)
    assert payments_params == {"seller_ids": [1], "order_id": "12345"}
    assert "CAST(o.order_id AS TEXT) = :order_id" in str(supplier_sql)
    assert "CAST(yai.offer_id AS TEXT) = :offer_id" in str(supplier_sql)
    assert supplier_params == {
        "seller_ids": [1],
        "order_id": "12345",
        "offer_id": "ABC",
    }


def test_yandex_order_query_selects_fixed_fee_snapshots() -> None:
    sql, _ = build_order_items_query((1,), None, None, "12345", "ABC")
    query = str(sql)

    assert "markup_yandex_accepting_payments_fee_amount" in query
    assert "AS calc_accepting_payment_fee" in query
    assert "markup_yandex_order_processing_fee_amount" in query
    assert "AS calc_order_processing_fee" in query
    assert "AS order_items_count" in query


def test_payment_query_classifies_fact_commission_details() -> None:
    sql, _ = build_payment_aggregates_query((1,), None, None, "12345")
    query = str(sql)

    assert "'Размещение товарных предложений'" in query
    assert "'Перевод платежа'" in query
    assert "'Приём платежа'" in query
    assert "'Начисления за доставку'" in query
    assert "AS fact_unclassified_fees" in query
    assert "AS fact_commission_details_complete" in query
