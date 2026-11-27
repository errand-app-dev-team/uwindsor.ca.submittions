
"""Integration interface for Aerrand's routing and pricing engine."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string


class PricingAdapterError(Exception):
    """Base exception for pricing integration errors."""


class PricingAdapterUnavailable(PricingAdapterError):
    """The production pricing integration is not configured."""


class PricingAdapterInvalidResult(PricingAdapterError):
    """The pricing engine returned an invalid calculation."""


class PricingAdapter(ABC):
    """Contract for calculating server-trusted delivery prices."""

    @abstractmethod
    def calculate_quote(
        self,
        validated_data: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        """Return route distance, price breakdown, total and resolved stops."""


class UnconfiguredPricingAdapter(PricingAdapter):
    """Reject live pricing until the Aerrand pricing engine is connected."""

    def calculate_quote(self, validated_data, context):
        raise PricingAdapterUnavailable(
            "Aerrand routing and pricing integration is not configured."
        )


def get_pricing_adapter() -> PricingAdapter:
    """Load the configured Aerrand pricing integration."""

    adapter_path = getattr(settings, "AERRAND_PRICING_ADAPTER_CLASS", None)

    if not adapter_path:
        return UnconfiguredPricingAdapter()

    adapter_class = import_string(adapter_path)
    adapter = adapter_class()

    if not isinstance(adapter, PricingAdapter):
        raise TypeError(
            "AERRAND_PRICING_ADAPTER_CLASS must implement PricingAdapter."
        )

    return adapter


def validate_pricing_result(result: Any) -> dict[str, Any]:
    """Validate pricing output before saving a binding quote."""

    if not isinstance(result, dict):
        raise PricingAdapterInvalidResult(
            "Pricing calculation must return an object."
        )

    required_fields = {
        "route_km",
        "breakdown",
        "total",
        "resolved_stops",
    }

    if not required_fields.issubset(result):
        raise PricingAdapterInvalidResult(
            "Pricing calculation is missing required fields."
        )

    try:
        route_km = Decimal(str(result["route_km"]))
        total = Decimal(str(result["total"]))
    except (ValueError, TypeError, ArithmeticError) as error:
        raise PricingAdapterInvalidResult(
            "Pricing calculation contains invalid numeric values."
        ) from error

    if not route_km.is_finite() or route_km < 0:
        raise PricingAdapterInvalidResult(
            "Route distance must be non-negative."
        )

    if not total.is_finite() or total < 0:
        raise PricingAdapterInvalidResult(
            "Quote total must be non-negative."
        )

    if total.as_tuple().exponent < -2:
        raise PricingAdapterInvalidResult(
            "Quote total cannot exceed two decimal places."
        )

    breakdown = result["breakdown"]
    resolved_stops = result["resolved_stops"]

    if not isinstance(breakdown, dict):
        raise PricingAdapterInvalidResult(
            "Price breakdown must be an object."
        )

    if not isinstance(resolved_stops, list):
        raise PricingAdapterInvalidResult(
            "Resolved stops must be a list."
        )

    return {
        "route_km": route_km,
        "breakdown": breakdown,
        "total": total,
        "resolved_stops": resolved_stops,
    }
