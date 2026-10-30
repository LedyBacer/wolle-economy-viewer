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
    CacheLookup,
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
    serialize_order_row,
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
    if get_settings().refund_cases_enabled:
        from sqlalchemy import text
        from wolle_economy.db.engine import get_engine
        from wolle_economy.db.queries import AFTER_SALES_ORDER_SQL

        with get_engine().connect() as conn:
            managed = conn.execute(
                text(AFTER_SALES_ORDER_SQL),
                {"seller_id": seller_id, "order_number": order_id},
            ).first()
        if managed:
            cached = CacheLookup(CacheStatus.MISS, cached.marketplace_code)

    if cached.status == CacheStatus.HIT:
        response.headers["X-Cache"] = "HIT"
        if cached.marketplace_code is not None and order_cache.claim_revalidation(key):
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
    except (
        SellerNotFoundError,
        UnsupportedMarketplaceError,
        OrderEconomicsNotFoundError,
    ) as exc:
        if marketplace_code is not None and isinstance(
            exc, OrderEconomicsNotFoundError
        ):
            order_cache.store_not_found(key, marketplace_code)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AmbiguousOrderEconomicsError as exc:
        if marketplace_code is not None:
            order_cache.store_ambiguous(key, marketplace_code)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Ошибка БД при получении строки экономики")
        raise HTTPException(
            status_code=503, detail="База данных временно недоступна"
        ) from exc


@app.get("/api/v1/refund-case-economics")
def refund_case_economics(case_id: str, preview: bool = False):
    """Расходы доступны и без платформенной экономики; неизвестная прибыль не равна нулю."""
    from uuid import UUID
    from decimal import Decimal
    from sqlalchemy import text
    from wolle_economy.db.engine import get_engine
    from wolle_economy.db.queries import AFTER_SALES_CASE_SQL, after_sales_context
    from wolle_economy.domain.loader import load_order_economics_data
    from wolle_economy.domain.economics import apply_refund_cases
    import pandas as pd

    if not get_settings().refund_cases_enabled:
        raise HTTPException(404, "Контур возвратов отключён")
    try:
        UUID(case_id)
    except ValueError:
        raise HTTPException(422, "Некорректный ID")
    with get_engine().connect() as conn:
        case = (
            conn.execute(text(AFTER_SALES_CASE_SQL), {"case_id": case_id})
            .mappings()
            .first()
        )
        if case is None:
            raise HTTPException(404, "Обращение не найдено")
        items, operations, matches = after_sales_context(
            conn, case["seller_id"], case["order_number"], case_id if preview else None
        )
    full_context = (items, operations, matches)
    operations = [o for o in operations if str(o["case_id"]) == case_id]
    case_items = [i for i in items if str(i["case_id"]) == case_id]
    receipt_kinds = {
        "supplier_reimbursement",
        "carrier_reimbursement",
        "commission_refund",
    }
    total = sum(
        (
            Decimal(str(o["allocated_amount"]))
            for o in operations
            if o["state"] == "posted"
            and o["kind"] not in receipt_kinds
            and o["payer"] == "company"
            and (o["currency"] == "RUB" or o.get("rub_amount") is not None)
        ),
        Decimal(0),
    )
    planned = sum(
        (
            Decimal(str(o["allocated_amount"]))
            for o in operations
            if o["state"] == "planned"
            and o["kind"] not in receipt_kinds
            and o["payer"] == "company"
            and (o["currency"] == "RUB" or o.get("rub_amount") is not None)
        ),
        Decimal(0),
    )
    from datetime import datetime, timezone

    result = {
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "calculation_version": "refund-cases-v2",
        "economics_revision": case["revision"],
        "case_id": case_id,
        "posted_expense": str(total),
        "planned_expense": str(planned),
        "profit": None,
        "state": "unavailable",
        "message": None,
        "items": [],
    }
    result["posted_reimbursement"] = str(
        sum(
            (
                Decimal(str(o["allocated_amount"]))
                for o in operations
                if o["kind"] in receipt_kinds
                and o["state"] == "posted"
                and o["payer"] == "company"
                and (o["currency"] == "RUB" or o.get("rub_amount") is not None)
            ),
            Decimal(0),
        )
    )
    result["planned_reimbursement"] = str(
        sum(
            (
                Decimal(str(o["allocated_amount"]))
                for o in operations
                if o["kind"] in receipt_kinds
                and o["state"] == "planned"
                and o["payer"] == "company"
                and (o["currency"] == "RUB" or o.get("rub_amount") is not None)
            ),
            Decimal(0),
        )
    )
    result["expenses_by_kind"] = {
        kind: str(
            sum(
                (
                    Decimal(str(o["allocated_amount"]))
                    for o in operations
                    if o["state"] == "posted"
                    and o["payer"] == "company"
                    and o["kind"] == kind
                    and (o["currency"] == "RUB" or o.get("rub_amount") is not None)
                ),
                Decimal(0),
            )
        )
        for kind in (
            "customer_refund",
            "customer_compensation",
            "return_delivery",
            "other_expense",
            "replacement_cost",
            "supplier_reimbursement",
            "carrier_reimbursement",
            "commission_refund",
        )
    }
    result["foreign_operations"] = [
        {"id": str(o["id"]), "amount": str(o["amount"]), "currency": o["currency"]}
        for o in {
            str(x["id"]): x
            for x in operations
            if x["currency"] != "RUB" and x.get("rub_amount") is None
        }.values()
    ]
    result["goods"] = [
        {
            "split_order_id": i["split_order_id"],
            "stage": i["stage"],
            "purchase_cost": (
                str(
                    i["purchase_cost"]
                    if i["purchase_cost"] is not None
                    else i["procurement_cost"]
                )
                if (i["purchase_cost"] is not None or i["procurement_cost"] is not None)
                else None
            ),
            "cost_source": (
                i["cost_source"]
                if i["purchase_cost"] is not None
                else (
                    f"order_to_supplier:{i['procurement_id']}"
                    if i["procurement_cost"] is not None
                    else "unknown"
                )
            ),
        }
        for i in case_items
    ]
    if case["seller_id"] is None or not case["order_number"]:
        result["message"] = "Сначала привяжите исходный заказ"
        return result
    try:
        code = resolve_marketplace_code(case["seller_id"])
        rows = load_order_economics_data(
            code,
            seller_id=case["seller_id"],
            order_id=case["order_number"],
            offer_id=None,
            include_after_sales=False,
        )
        rows = apply_refund_cases(rows, *full_context)
    except UnsupportedMarketplaceError:
        result["message"] = "Полная экономика этой площадки пока недоступна"
        return result
    with get_engine().connect() as conn:
        latest = (
            conn.execute(text(AFTER_SALES_CASE_SQL), {"case_id": case_id})
            .mappings()
            .first()
        )
        refreshed = after_sales_context(
            conn, case["seller_id"], case["order_number"], case_id if preview else None
        )
    fingerprints = lambda context: {
        str(m["id"]): m.get("current_fingerprint") for m in context[2]
    }
    if latest["revision"] != case["revision"] or fingerprints(
        refreshed
    ) != fingerprints(full_context):
        result["state"] = "unavailable"
        result["message"] = "Данные изменились во время расчёта; обновите карточку"
        return result
    result["items"] = [serialize_order_row(row, code) for _, row in rows.iterrows()]
    if rows.empty:
        result["message"] = "Базовая экономика заказа не найдена"
        return result
    if any(
        x.get("after_sales_state") == "needs_reconciliation" for x in result["items"]
    ):
        result["state"] = "needs_reconciliation"
        result["message"] = "Необходимо сверить выплаты и стоимость товара"
        return result
    # Yandex order-wide amounts are allocated by the native loader before this point.
    profit = pd.to_numeric(rows["profit"], errors="coerce")
    if profit.notna().all():
        result["profit"] = str(round(float(profit.sum()), 2))
        result["state"] = (
            "provisional"
            if any(x.get("after_sales_state") == "provisional" for x in result["items"])
            else "complete"
        )
    return result
