"""FastAPI-приложение для доступа к экономике заказов."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError

from wolle_economy.api.cache import (
    CacheStatus,
    OrderKey,
    order_cache,
    refresh_all_orders,
)
from wolle_economy.api.service import (
    AmbiguousOrderEconomicsError,
    OrderEconomicsNotFoundError,
    SellerNotFoundError,
    UnsupportedMarketplaceError,
    fetch_order_economics,
    resolve_marketplace_code,
)
from wolle_economy.config import get_settings
from wolle_economy.logging_setup import setup_logging

# API переиспользует loader со Streamlit-декораторами без Streamlit runtime.
logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)

setup_logging()
logger = logging.getLogger(__name__)


async def _cache_refresh_loop(interval_seconds: int) -> None:
    """Обновляет полный снимок сразу после старта и затем раз в TTL."""
    while True:
        refreshed = await asyncio.to_thread(refresh_all_orders)
        retry_seconds = interval_seconds if refreshed else min(interval_seconds, 60)
        await asyncio.sleep(retry_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Запускает и корректно останавливает почасовое обновление кэша."""
    refresh_task = asyncio.create_task(
        _cache_refresh_loop(max(1, get_settings().cache_ttl)),
        name="order-economics-cache-refresh",
    )
    try:
        yield
    finally:
        refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task


app = FastAPI(
    title="Wolle Economy API",
    version="1.0.0",
    description="API рассчитанной экономики заказов маркетплейсов.",
    lifespan=lifespan,
)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, Any]:
    """Проверка доступности HTTP-процесса без обращения к БД."""
    return {"status": "ok", "cache": order_cache.stats()}


def _revalidate_order(
    key: OrderKey,
    marketplace_code: str,
) -> None:
    """После ответа проверяет точечную строку и обновляет override кэша."""
    seller_id, order_id, offer_id = key
    try:
        data = fetch_order_economics(
            marketplace_code=marketplace_code,
            seller_id=seller_id,
            order_id=order_id,
            offer_id=offer_id,
        )
        order_cache.store_hit(key, marketplace_code, data)
    except OrderEconomicsNotFoundError:
        order_cache.store_not_found(key, marketplace_code)
    except AmbiguousOrderEconomicsError:
        order_cache.store_ambiguous(key, marketplace_code)
    except Exception:
        logger.exception(
            "Не удалось ревалидировать строку экономики: seller_id=%d",
            seller_id,
        )
    finally:
        order_cache.finish_revalidation(key)


@app.get(
    "/api/v1/order-economics",
    response_model=dict[str, Any],
    summary="Получить строку экономики позиции заказа",
    responses={
        404: {"description": "Магазин или позиция заказа не найдены"},
        409: {"description": "По составному ключу найдено несколько строк"},
        503: {"description": "База данных временно недоступна"},
    },
)
def read_order_economics(
    background_tasks: BackgroundTasks,
    response: Response,
    seller_id: Annotated[int, Query(gt=0, description="ID из platform_sellers")],
    order_id: Annotated[str, Query(min_length=1, description="Внешний номер заказа")],
    offer_id: Annotated[str, Query(min_length=1, description="Точный Offer ID")],
) -> dict[str, Any]:
    """Возвращает все колонки строки из режима «Показать все колонки»."""
    key: OrderKey = (seller_id, order_id, offer_id)
    cached = order_cache.lookup(key)

    if cached.status == CacheStatus.HIT:
        response.headers["X-Cache"] = "HIT"
        if (
            cached.marketplace_code is not None
            and order_cache.claim_revalidation(key)
        ):
            background_tasks.add_task(
                _revalidate_order,
                key,
                cached.marketplace_code,
            )
        return cached.data or {}

    if cached.status == CacheStatus.AMBIGUOUS:
        raise HTTPException(
            status_code=409,
            detail="По указанным seller_id, order_id и offer_id найдено несколько строк",
        )

    response.headers["X-Cache"] = "MISS"
    marketplace_code = cached.marketplace_code
    try:
        if marketplace_code is None:
            marketplace_code = resolve_marketplace_code(seller_id)
        data = fetch_order_economics(
            marketplace_code=marketplace_code,
            seller_id=seller_id,
            order_id=order_id,
            offer_id=offer_id,
        )
        order_cache.store_hit(key, marketplace_code, data)
        return data
    except (SellerNotFoundError, UnsupportedMarketplaceError, OrderEconomicsNotFoundError) as exc:
        if marketplace_code is not None and isinstance(exc, OrderEconomicsNotFoundError):
            order_cache.store_not_found(key, marketplace_code)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AmbiguousOrderEconomicsError as exc:
        if marketplace_code is not None:
            order_cache.store_ambiguous(key, marketplace_code)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Ошибка БД при получении строки экономики")
        raise HTTPException(status_code=503, detail="База данных временно недоступна") from exc
