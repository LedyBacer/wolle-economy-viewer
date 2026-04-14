"""
Статусы заказов Яндекс Маркет.
Используются в economics.py для классификации заказов по исходу.
"""

from enum import StrEnum


class FulfillmentStatus(StrEnum):
    """Статусы выполнения заказа из ya_order_margin_report / ya_orders.status."""

    # --- Финальные положительные ---
    DELIVERED = "Доставлен"

    # --- Отменены до отгрузки (расходы не понесены) ---
    CANCELLED_BEFORE_PROCESSING = "Заказ отменен до обработки"
    CANCELLED_DURING_PROCESSING = "Отменен при обработке"
    CANCELLED = "Отменён"

    # --- Возвраты / невыкупы (расходы понесены, товар вернулся) ---
    BUYOUT_REFUSED = "Невыкуп принят на складе"
    FULL_RETURN = "Полный возврат принят на складе"
    PARTIAL_BUYOUT_REFUSED = "Частичный невыкуп принят на складе"
    CANCELLED_AT_DELIVERY = "Отменен при доставке"
    # Частичный возврат: часть штук доставлена, часть возвращена
    # Определяется на основе ya_order_transactions_report (несколько строк на позицию)
    PARTIALLY_RETURNED = "Частично возвращён"

    # --- В процессе ---
    IN_DELIVERY = "В доставке"
    IN_PROCESSING = "В обработке"
    PICKUP = "Самовывоз"


class PaymentStatus(StrEnum):
    """Статусы выплаты из ya_order_margin_report."""

    TRANSFERRED = "Переведён"
    WITHHELD = "Удержан из платежей покупателей"


# Статусы, при которых заказ отменён до отгрузки (расходы не понесены)
CANCELLED_BEFORE_SHIP: frozenset[str] = frozenset(
    {
        FulfillmentStatus.CANCELLED_BEFORE_PROCESSING,
        FulfillmentStatus.CANCELLED_DURING_PROCESSING,
        FulfillmentStatus.CANCELLED,
    }
)

# Статусы возврата/невыкупа (расходы понесены, товар вернулся)
RETURNED_STATUSES: frozenset[str] = frozenset(
    {
        FulfillmentStatus.BUYOUT_REFUSED,
        FulfillmentStatus.FULL_RETURN,
        FulfillmentStatus.PARTIAL_BUYOUT_REFUSED,
        FulfillmentStatus.CANCELLED_AT_DELIVERY,
        FulfillmentStatus.PARTIALLY_RETURNED,
    }
)

# Все статусы, при которых заказ не приносит дохода
CANCELLED_STATUSES: frozenset[str] = CANCELLED_BEFORE_SHIP | RETURNED_STATUSES

# Статусы, при которых выплата получена
PAID_STATUSES: frozenset[str] = frozenset(
    {
        PaymentStatus.TRANSFERRED,
        PaymentStatus.WITHHELD,
    }
)


# ────────────────────────────────────────────────────────────────────────────
# МегаМаркет (mm_cdek_orders.status + mm_dbs_order_item.status)
# ────────────────────────────────────────────────────────────────────────────


class MMCdekStatus(StrEnum):
    """Статусы СДЭК-доставки из mm_cdek_orders.status."""

    # Финальный положительный
    DELIVERED = "DELIVERED"

    # Не доставлен (возврат отправителю)
    NOT_DELIVERED = "NOT_DELIVERED"

    # Отменён / удалён
    REMOVED = "REMOVED"
    DELETED = "DELETED"
    CANCELLED = "CANCELLED"

    # В пути / обработке
    CREATED = "CREATED"
    TAKEN_BY_COURIER = "TAKEN_BY_COURIER"
    ACCEPTED_AT_TRANSIT_WAREHOUSE = "ACCEPTED_AT_TRANSIT_WAREHOUSE"
    SENT_TO_TRANSIT_CITY = "SENT_TO_TRANSIT_CITY"
    ACCEPTED_AT_PICK_UP_POINT = "ACCEPTED_AT_PICK_UP_POINT"
    SENT_TO_RECIPIENT_CITY = "SENT_TO_RECIPIENT_CITY"
    READY_FOR_SHIPMENT_IN_TRANSIT_CITY = "READY_FOR_SHIPMENT_IN_TRANSIT_CITY"
    TAKEN_BY_TRANSPORTER_FROM_SENDER_CITY = "TAKEN_BY_TRANSPORTER_FROM_SENDER_CITY"
    TAKEN_BY_TRANSPORTER_FROM_TRANSIT_CITY = "TAKEN_BY_TRANSPORTER_FROM_TRANSIT_CITY"
    ACCEPTED_AT_RECIPIENT_CITY_WAREHOUSE = "ACCEPTED_AT_RECIPIENT_CITY_WAREHOUSE"
    CUSTOMS_COMPLETE = "CUSTOMS_COMPLETE"

    # Возврат
    RETURNED_TO_RECIPIENT_CITY_WAREHOUSE = "RETURNED_TO_RECIPIENT_CITY_WAREHOUSE"


class MMItemStatus(StrEnum):
    """Статусы позиции заказа из mm_dbs_order_item.status."""

    CREATED = "created"
    PACKED = "packed"
    DELIVERED = "delivered"
    RETURNED = "returned"
    CANCELLED = "canceled"
    CANCELLED_BY_MM = "canceled_by_mm"
    CANCELLED_DECLINED = "canceled_declined"


class MMPoizonOrderStatus(StrEnum):
    """Статусы Poizon-заказа из mm_dbs_poizon_orders.status."""

    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    WAITING = "WAITING"
    PROCESSED = "PROCESSED"
    PACKED = "PACKED"


# ── Группировки статусов ММ ──────────────────────────────────────────────────

# СДЭК: финально доставлен покупателю
MM_DELIVERED_STATUSES: frozenset[str] = frozenset({MMCdekStatus.DELIVERED})

# СДЭК: отменён до или во время доставки (расходы понесены частично)
MM_CANCELLED_STATUSES: frozenset[str] = frozenset(
    {
        MMCdekStatus.REMOVED,
        MMCdekStatus.DELETED,
        MMCdekStatus.CANCELLED,
        MMCdekStatus.NOT_DELIVERED,
    }
)

# СДЭК: возвращён покупателем
MM_RETURNED_STATUSES: frozenset[str] = frozenset(
    {MMCdekStatus.RETURNED_TO_RECIPIENT_CITY_WAREHOUSE}
)

# СДЭК: в процессе (не финальный статус)
MM_IN_TRANSIT_STATUSES: frozenset[str] = frozenset(
    {
        MMCdekStatus.CREATED,
        MMCdekStatus.TAKEN_BY_COURIER,
        MMCdekStatus.ACCEPTED_AT_TRANSIT_WAREHOUSE,
        MMCdekStatus.SENT_TO_TRANSIT_CITY,
        MMCdekStatus.ACCEPTED_AT_PICK_UP_POINT,
        MMCdekStatus.SENT_TO_RECIPIENT_CITY,
        MMCdekStatus.READY_FOR_SHIPMENT_IN_TRANSIT_CITY,
        MMCdekStatus.TAKEN_BY_TRANSPORTER_FROM_SENDER_CITY,
        MMCdekStatus.TAKEN_BY_TRANSPORTER_FROM_TRANSIT_CITY,
        MMCdekStatus.ACCEPTED_AT_RECIPIENT_CITY_WAREHOUSE,
        MMCdekStatus.CUSTOMS_COMPLETE,
    }
)

# Poizon: финально доставлен
MM_POIZON_DELIVERED_STATUSES: frozenset[str] = frozenset({MMPoizonOrderStatus.COMPLETED})

# Poizon: отменён
MM_POIZON_CANCELLED_STATUSES: frozenset[str] = frozenset({MMPoizonOrderStatus.CANCELED})

# ── Русские строки статусов (для отображения в UI) ───────────────────────────
MM_FULFILLMENT_STATUS_DELIVERED = "Доставлен"
MM_FULFILLMENT_STATUS_CANCELLED = "Отменён"
MM_FULFILLMENT_STATUS_NOT_DELIVERED = "Не доставлен"
MM_FULFILLMENT_STATUS_RETURNED = "Возврат"
MM_FULFILLMENT_STATUS_IN_TRANSIT = "В доставке"
MM_FULFILLMENT_STATUS_UNKNOWN = "Неизвестно"
