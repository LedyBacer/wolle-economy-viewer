"""Тесты реестра маркетплейсов и маршрутизации публичных wrapper-функций."""

import pandas as pd

import wolle_economy.domain.loader as loader


def test_marketplace_specs_have_required_fields() -> None:
    specs = loader.get_marketplace_specs()
    assert {s.code for s in specs} == {"ym", "mm", "sm", "wb", "oz"}

    for spec in specs:
        assert spec.title
        assert spec.order_key
        assert isinstance(spec.ui_profile, dict)
        assert callable(spec.load_orders)
        assert callable(spec.load_sellers)
        assert callable(spec.load_date_range)


def test_load_orders_wrapper_routes_to_ym_impl(monkeypatch) -> None:
    expected = pd.DataFrame([{"source": "ym"}])
    monkeypatch.setattr(loader, "_load_ym_orders_impl", lambda **_: expected)
    loader.load_orders.clear()

    got = loader.load_orders()
    assert got.equals(expected)


def test_load_mm_orders_wrapper_routes_to_mm_impl(monkeypatch) -> None:
    expected = pd.DataFrame([{"source": "mm"}])
    monkeypatch.setattr(loader, "_load_mm_orders_impl", lambda **_: expected)
    loader.load_mm_orders.clear()

    got = loader.load_mm_orders()
    assert got.equals(expected)


def test_load_sm_orders_wrapper_routes_to_sm_impl(monkeypatch) -> None:
    expected = pd.DataFrame([{"source": "sm"}])
    monkeypatch.setattr(loader, "_load_sm_orders_impl", lambda **_: expected)
    loader.load_sm_orders.clear()

    got = loader.load_sm_orders()
    assert got.equals(expected)


def test_load_wb_orders_wrapper_routes_to_wb_impl(monkeypatch) -> None:
    expected = pd.DataFrame([{"source": "wb"}])
    monkeypatch.setattr(loader, "_load_wb_orders_impl", lambda **_: expected)
    loader.load_wb_orders.clear()

    got = loader.load_wb_orders()
    assert got.equals(expected)


def test_load_oz_orders_wrapper_routes_to_oz_impl(monkeypatch) -> None:
    expected = pd.DataFrame([{"source": "oz"}])
    monkeypatch.setattr(loader, "_load_oz_orders_impl", lambda **_: expected)
    loader.load_oz_orders.clear()

    got = loader.load_oz_orders()
    assert got.equals(expected)


def test_oz_aliases_resolve_to_oz_marketplace() -> None:
    assert loader.get_marketplace_spec("oz").code == "oz"
    assert loader.get_marketplace_spec("ozon").code == "oz"
    assert loader.get_marketplace_spec("озон").code == "oz"
