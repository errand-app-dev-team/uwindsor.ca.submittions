
"""Validate payment state before a delivery becomes dispatchable."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class PaymentStateError(ValueError):
    pass


@dataclass(frozen=True)
class PaymentResult:
    status: str
    method: str
    reference: str | None = None


def validate_payment_amount(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PaymentStateError("Invalid payment amount.") from error

    if not value.is_finite() or value <= 0:
        raise PaymentStateError("Payment amount must be positive.")

    if value.as_tuple().exponent < -2:
        raise PaymentStateError("Payment amount cannot exceed two decimal places.")

    return value


def validate_payment_result(result):
    if not isinstance(result, dict):
        raise PaymentStateError("Invalid payment result.")

    status = result.get("status")
    method = result.get("method")
    reference = result.get("reference")

    if status not in {"unpaid", "pending", "paid", "failed"}:
        raise PaymentStateError("Unknown payment status.")

    if not isinstance(method, str) or not method.strip():
        raise PaymentStateError("Payment method is required.")

    if reference is not None and (
        not isinstance(reference, str) or not reference.strip()
    ):
        raise PaymentStateError("Invalid payment reference.")

    if status == "paid" and not reference:
        raise PaymentStateError(
            "A confirmed payment reference is required."
        )

    return PaymentResult(
        status=status,
        method=method,
        reference=reference,
    )


def can_dispatch(payment_status):
    """Only confirmed payments may proceed to dispatch."""
    return payment_status == "paid"
