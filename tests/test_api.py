"""Контракт HTTP API экономики."""

from __future__ import annotations

import datetime
import importlib
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.api.cache import order_cache
from wolle_economy.api.service import (
    AmbiguousOrderEconomicsError,
    OrderEconomicsNotFoundError,
    get_order_economics,
    serialize_order_row,
)
from wolle_economy.ui.columns import DISPLAY_COLUMNS

app_module = importlib.import_module("wolle_economy.api.app")
client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def clean_global_cache() -> None:
    order_cache.clear()


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "cache": {"ready": False, "orders": 0, "last_refresh": None},
    }


def test_order_economics_success(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {"order_id_str": "12345", "offer_id": "ABC", "profit": 42.5}
    monkeypatch.setattr(app_module, "resolve_marketplace_code", lambda _: "ym")
    monkeypatch.setattr(app_module, "fetch_order_economics", lambda **_: expected)

    response = client.get(
        "/api/v1/order-economics",
        params={"seller_id": 1, "order_id": "12345", "offer_id": "ABC"},
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["x-cache"] == "MISS"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"seller_id": 1, "order_id": "12345"},
        {"seller_id": 0, "order_id": "12345", "offer_id": "ABC"},
        {"seller_id": 1, "order_id": "", "offer_id": "ABC"},
    ],
)
def test_invalid_query_returns_422(params: dict[str, object]) -> None:
    response = client.get("/api/v1/order-economics", params=params)

    assert response.status_code == 422


def test_not_found_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(**_: object) -> dict[str, object]:
        raise OrderEconomicsNotFoundError("Не найдено")

    monkeypatch.setattr(app_module, "resolve_marketplace_code", lambda _: "ym")
    monkeypatch.setattr(app_module, "fetch_order_economics", raise_not_found)
    response = client.get(
        "/api/v1/order-economics",
        params={"seller_id": 1, "order_id": "12345", "offer_id": "ABC"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Не найдено"}


def test_ambiguous_result_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ambiguous(**_: object) -> dict[str, object]:
        raise AmbiguousOrderEconomicsError("Несколько строк")

    monkeypatch.setattr(app_module, "resolve_marketplace_code", lambda _: "ym")
    monkeypatch.setattr(app_module, "fetch_order_economics", raise_ambiguous)
    response = client.get(
        "/api/v1/order-economics",
        params={"seller_id": 1, "order_id": "12345", "offer_id": "ABC"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Несколько строк"}


def test_database_error_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_db_error(**_: object) -> dict[str, object]:
        raise SQLAlchemyError("connection failed")

    monkeypatch.setattr(app_module, "resolve_marketplace_code", lambda _: "ym")
    monkeypatch.setattr(app_module, "fetch_order_economics", raise_db_error)
    response = client.get(
        "/api/v1/order-economics",
        params={"seller_id": 1, "order_id": "12345", "offer_id": "ABC"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "База данных временно недоступна"}


def test_cache_hit_returns_stale_row_then_revalidates(monkeypatch: pytest.MonkeyPatch) -> None:
    order_cache.replace_snapshots(
        {
            "ym": pd.DataFrame(
                [
                    {
                        "seller_id": 1,
                        "order_id_str": "12345",
                        "offer_id": "ABC",
                        "profit": 10.0,
                    }
                ]
            )
        }
    )
    fresh = {"order_id_str": "12345", "offer_id": "ABC", "profit": 20.0}
    monkeypatch.setattr(app_module, "fetch_order_economics", lambda **_: fresh)

    response = client.get(
        "/api/v1/order-economics",
        params={"seller_id": 1, "order_id": "12345", "offer_id": "ABC"},
    )

    assert response.status_code == 200
    assert response.headers["x-cache"] == "HIT"
    assert response.json()["profit"] == 10.0
    assert order_cache.lookup((1, "12345", "ABC")).data == fresh


def test_cached_not_found_is_checked_synchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    key = (1, "12345", "ABC")
    order_cache.store_not_found(key, "ym")
    fresh = {"order_id_str": "12345", "offer_id": "ABC", "profit": 20.0}
    monkeypatch.setattr(app_module, "fetch_order_economics", lambda **_: fresh)

    def unexpected_resolve(_: int) -> str:
        raise AssertionError("Маркетплейс уже известен из отрицательного кэша")

    monkeypatch.setattr(app_module, "resolve_marketplace_code", unexpected_resolve)

    response = client.get(
        "/api/v1/order-economics",
        params={"seller_id": 1, "order_id": "12345", "offer_id": "ABC"},
    )

    assert response.status_code == 200
    assert response.headers["x-cache"] == "MISS"
    assert response.json() == fresh


def test_service_rejects_multiple_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "wolle_economy.api.service.resolve_marketplace_code",
        lambda _: "ym",
    )
    duplicate = pd.DataFrame(
        [
            {"order_id_str": "1", "offer_id": "A"},
            {"order_id_str": "1", "offer_id": "A"},
        ]
    )
    monkeypatch.setattr(
        "wolle_economy.api.service.load_order_economics_data",
        lambda *_args, **_kwargs: duplicate,
    )

    with pytest.raises(AmbiguousOrderEconomicsError):
        get_order_economics(seller_id=1, order_id="1", offer_id="A")


def test_serialize_order_row_uses_ui_columns_and_json_types() -> None:
    row = pd.Series(
        {
            "created_at": pd.Timestamp("2026-07-23T10:15:00+03:00"),
            "shipment_date": datetime.date(2026, 7, 24),
            "order_id_str": "12345",
            "offer_id": "ABC",
            "quantity": np.int64(2),
            "calc_accepting_payment_fee_total": Decimal("0.20"),
            "fact_accepting_payment_fee": np.nan,
            "fact_commission_details_complete": np.bool_(False),
            "profit": Decimal("42.50"),
            "actual_profit": np.nan,
            "internal_only": "hidden",
        }
    )

    result = serialize_order_row(row, "ym")

    assert list(result) == [column for column in DISPLAY_COLUMNS if column in row.index]
    assert result["created_at"] == "2026-07-23T10:15:00+03:00"
    assert result["shipment_date"] == "2026-07-24"
    assert result["quantity"] == 2
    assert result["calc_accepting_payment_fee_total"] == 0.2
    assert result["fact_accepting_payment_fee"] is None
    assert result["fact_commission_details_complete"] is False
    assert result["profit"] == 42.5
    assert result["actual_profit"] is None
    assert "internal_only" not in result
