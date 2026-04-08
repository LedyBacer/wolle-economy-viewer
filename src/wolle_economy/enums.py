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
