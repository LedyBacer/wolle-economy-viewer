"""In-memory stale-while-revalidate кэш строк экономики."""

from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd

from wolle_economy.api.service import serialize_order_row

logger = logging.getLogger(__name__)

OrderKey = tuple[int, str, str]


class CacheStatus(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class CacheLookup:
    status: CacheStatus
    marketplace_code: str | None = None
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class _RowPointer:
    marketplace_code: str
    position: int


class OrderEconomicsCache:
    """Потокобезопасный снимок всех заказов с точечными обновлениями."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots: dict[str, pd.DataFrame] = {}
        self._index: dict[OrderKey, _RowPointer] = {}
        self._ambiguous: dict[OrderKey, str] = {}
        self._overrides: dict[OrderKey, CacheLookup] = {}
        self._revalidating: set[OrderKey] = set()
        self._ready = False
        self._last_refresh: datetime.datetime | None = None

    def clear(self) -> None:
        """Очищает состояние. Используется при тестировании."""
        with self._lock:
            self._snapshots = {}
            self._index = {}
            self._ambiguous = {}
            self._overrides = {}
            self._revalidating = set()
            self._ready = False
            self._last_refresh = None

    def replace_snapshots(self, snapshots: dict[str, pd.DataFrame]) -> None:
        """Строит новый индекс и атомарно заменяет полный снимок."""
        index: dict[OrderKey, _RowPointer] = {}
        ambiguous: dict[OrderKey, str] = {}

        for marketplace_code, frame in snapshots.items():
            required = {"seller_id", "order_id_str", "offer_id"}
            if frame.empty:
                continue
            missing = required.difference(frame.columns)
            if missing:
                raise ValueError(
                    f"Снимок {marketplace_code} не содержит колонки: {sorted(missing)}"
                )

            key_columns = frame[["seller_id", "order_id_str", "offer_id"]]
            for position, row in enumerate(key_columns.itertuples(index=False, name=None)):
                seller_id, order_id, offer_id = row
                if pd.isna(seller_id) or pd.isna(order_id) or pd.isna(offer_id):
                    continue
                key = (int(seller_id), str(order_id), str(offer_id))
                if key in ambiguous:
                    continue
                if key in index:
                    index.pop(key)
                    ambiguous[key] = marketplace_code
                else:
                    index[key] = _RowPointer(marketplace_code, position)

        with self._lock:
            self._snapshots = snapshots
            self._index = index
            self._ambiguous = ambiguous
            self._overrides = {}
            self._ready = True
            self._last_refresh = datetime.datetime.now(datetime.UTC)

    def lookup(self, key: OrderKey) -> CacheLookup:
        """Ищет строку в точечных обновлениях, затем в полном снимке."""
        with self._lock:
            override = self._overrides.get(key)
            if override is not None:
                if override.data is None:
                    return override
                return CacheLookup(
                    status=override.status,
                    marketplace_code=override.marketplace_code,
                    data=dict(override.data),
                )

            ambiguous_code = self._ambiguous.get(key)
            if ambiguous_code is not None:
                return CacheLookup(CacheStatus.AMBIGUOUS, ambiguous_code)

            pointer = self._index.get(key)
            if pointer is None:
                return CacheLookup(CacheStatus.MISS)

            frame = self._snapshots[pointer.marketplace_code]
            row = frame.iloc[pointer.position].copy()

        return CacheLookup(
            status=CacheStatus.HIT,
            marketplace_code=pointer.marketplace_code,
            data=serialize_order_row(row, pointer.marketplace_code),
        )

    def store_hit(
        self,
        key: OrderKey,
        marketplace_code: str,
        data: dict[str, Any],
    ) -> None:
        with self._lock:
            self._overrides[key] = CacheLookup(
                CacheStatus.HIT,
                marketplace_code,
                dict(data),
            )

    def store_not_found(self, key: OrderKey, marketplace_code: str) -> None:
        with self._lock:
            self._overrides[key] = CacheLookup(
                CacheStatus.NOT_FOUND,
                marketplace_code,
            )

    def store_ambiguous(self, key: OrderKey, marketplace_code: str) -> None:
        with self._lock:
            self._overrides[key] = CacheLookup(
                CacheStatus.AMBIGUOUS,
                marketplace_code,
            )

    def claim_revalidation(self, key: OrderKey) -> bool:
        """Разрешает только одну одновременную ревалидацию составного ключа."""
        with self._lock:
            if key in self._revalidating:
                return False
            self._revalidating.add(key)
            return True

    def finish_revalidation(self, key: OrderKey) -> None:
        with self._lock:
            self._revalidating.discard(key)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ready": self._ready,
                "orders": len(self._index) + len(self._ambiguous),
                "last_refresh": (
                    self._last_refresh.isoformat() if self._last_refresh is not None else None
                ),
            }


order_cache = OrderEconomicsCache()


def refresh_all_orders() -> bool:
    """Загружает все площадки и атомарно публикует новый снимок."""
    import streamlit

    _ = streamlit
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
    from wolle_economy.domain.loader import load_all_order_economics_data

    snapshots: dict[str, pd.DataFrame] = {}
    try:
        for marketplace_code in ("ym", "mm", "sm", "wb", "oz"):
            snapshots[marketplace_code] = load_all_order_economics_data(marketplace_code)
        order_cache.replace_snapshots(snapshots)
    except Exception:
        logger.exception("Не удалось обновить полный кэш экономики")
        return False

    stats = order_cache.stats()
    logger.info(
        "Полный кэш экономики обновлён: строк=%d",
        stats["orders"],
    )
    return True
