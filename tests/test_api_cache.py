"""Поведение in-memory stale-while-revalidate кэша."""

from __future__ import annotations

import pandas as pd
import pytest

from wolle_economy.api.cache import CacheStatus, OrderEconomicsCache


def _snapshot(profit: float = 10.0) -> dict[str, pd.DataFrame]:
    return {
        "ym": pd.DataFrame(
            [
                {
                    "seller_id": 1,
                    "order_id_str": "12345",
                    "offer_id": "ABC",
                    "profit": profit,
                }
            ]
        )
    }


def test_snapshot_lookup_and_stats() -> None:
    cache = OrderEconomicsCache()
    cache.replace_snapshots(_snapshot())

    result = cache.lookup((1, "12345", "ABC"))

    assert result.status == CacheStatus.HIT
    assert result.marketplace_code == "ym"
    assert result.data == {
        "order_id_str": "12345",
        "offer_id": "ABC",
        "profit": 10.0,
    }
    assert cache.stats()["ready"] is True
    assert cache.stats()["orders"] == 1
    assert cache.stats()["last_refresh"] is not None


def test_point_override_wins_over_snapshot() -> None:
    cache = OrderEconomicsCache()
    cache.replace_snapshots(_snapshot())
    cache.store_hit(
        (1, "12345", "ABC"),
        "ym",
        {"order_id_str": "12345", "offer_id": "ABC", "profit": 20.0},
    )

    result = cache.lookup((1, "12345", "ABC"))

    assert result.status == CacheStatus.HIT
    assert result.data is not None
    assert result.data["profit"] == 20.0


def test_duplicate_composite_key_is_ambiguous() -> None:
    cache = OrderEconomicsCache()
    duplicate = pd.concat([_snapshot()["ym"], _snapshot()["ym"]], ignore_index=True)
    cache.replace_snapshots({"ym": duplicate})

    result = cache.lookup((1, "12345", "ABC"))

    assert result.status == CacheStatus.AMBIGUOUS
    assert cache.stats()["orders"] == 1


def test_failed_snapshot_build_keeps_previous_data() -> None:
    cache = OrderEconomicsCache()
    cache.replace_snapshots(_snapshot())

    with pytest.raises(ValueError):
        cache.replace_snapshots({"ym": pd.DataFrame([{"seller_id": 1}])})

    result = cache.lookup((1, "12345", "ABC"))
    assert result.status == CacheStatus.HIT


def test_only_one_revalidation_per_key() -> None:
    cache = OrderEconomicsCache()
    key = (1, "12345", "ABC")

    assert cache.claim_revalidation(key) is True
    assert cache.claim_revalidation(key) is False

    cache.finish_revalidation(key)
    assert cache.claim_revalidation(key) is True
