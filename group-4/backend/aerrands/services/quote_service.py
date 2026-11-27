"""
Service functions for creating and retrieving Aerrand API quotes.

HTTP-specific work belongs in views.py, while quote processing and
integration with the existing Aerrand platform belong in this module.
"""

from dataclasses import dataclass
from typing import Any
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from decimal import Decimal
from aerrands.models import ApiQuote
import hashlib
import json
import uuid
from aerrands.services.demo_quote_service import calculate_demo_quote
from .pricing_adapter import PricingAdapterError, get_pricing_adapter, validate_pricing_result


class QuoteServiceError(Exception):
    """Base exception for errors that occur while processing a quote."""
    pass

class QuoteInputError(QuoteServiceError):
    """Raised when quote input cannot be processed."""
    pass

class QuoteIntegrationUnavailableError(QuoteServiceError):
    """
    Raised when quote processing requires functionality from the existing
    Aerrand platform that has not yet been connected to this API project.
    """
    pass


@dataclass
class QuoteContext:
    """
    Identity information supplied by the API authentication layer.

    The authentication/security implementation belongs to the corresponding
    security component. The quote service only consumes the resulting context.
    """

    business_owner_id: str
    api_key_id: str
    environment: str


def generate_inputs_hash(validated_data: dict[str, Any]) -> str:
    """Generate a consistent SHA-256 hash for quote pickup and stops."""

    # Only routing inputs affect quote identity; unrelated request fields are excluded.
    quote_inputs = {
        "pickup": validated_data["pickup"],
        "stops": validated_data["stops"],
    }

    canonical_json = json.dumps(
        quote_inputs,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    return hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()

def generate_quote_id() -> str:
    """Generate a unique identifier for an API quote."""
    return f"qt_{uuid.uuid4()}"

def calculate_quote_expiration():
    """Calculate quote expiration using the configured TTL."""

    ttl_seconds = getattr(settings, "QUOTE_TTL_SECONDS", 300)

    return timezone.now() + timedelta(seconds=ttl_seconds)


def create_quote(validated_data: dict[str, Any], context: QuoteContext):
    """Create a delivery quote using the configured pricing service."""

    if not context.business_owner_id:
        raise QuoteServiceError("business_owner_id is required.")

    if not context.api_key_id:
        raise QuoteServiceError("api_key_id is required.")

    if context.environment not in {"test", "live"}:
        raise QuoteServiceError("A valid API environment is required.")

    # Test pricing is available only when explicitly enabled in development.
    demo_enabled = (
        settings.DEBUG
        and getattr(settings, "ENABLE_DEMO_QUOTES", False) is True
        and context.environment == "test"
    )

    if demo_enabled:
        try:
            calculation = calculate_demo_quote(validated_data)
        except (ValueError, KeyError, TypeError) as error:
            raise QuoteInputError(str(error)) from error
    else:
        try:
            adapter = get_pricing_adapter()
            calculation = adapter.calculate_quote(validated_data, context)
            calculation = validate_pricing_result(calculation)
        except PricingAdapterError as error:
            raise QuoteIntegrationUnavailableError(str(error)) from error

    return save_quote(
        validated_data=validated_data,
        context=context,
        route_km=calculation["route_km"],
        breakdown=calculation["breakdown"],
        total=calculation["total"],
        resolved_stops=calculation["resolved_stops"],
    )




class QuoteNotFoundError(QuoteServiceError):
    """Raised when the requested API quote does not exist."""
    pass


class QuoteAccessError(QuoteServiceError):
    """Raised when a quote does not belong to the authenticated API context."""
    pass


class QuoteExpiredError(QuoteServiceError):
    """Raised when a quote has passed its expiration time."""
    pass

def get_quote(quote_id: str, context: QuoteContext):
    """
    Retrieve an existing ApiQuote for the authenticated Partner API context.

    A quote can be returned only when:
    1. It exists.
    2. It belongs to the authenticated business owner.
    3. It was created using the same API key and environment.
    4. It has not expired.

    MongoDB TTL eventually removes expired documents, but expiration is also
    checked here so an expired quote cannot be returned while awaiting cleanup.
    """

    from aerrands.models import ApiQuote

    # Retrieve the API-owned quote from the shared MongoDB database.
    try:
        quote = ApiQuote.objects.get(pk=quote_id)
    except ApiQuote.DoesNotExist as error:
        raise QuoteNotFoundError(
            f"Quote '{quote_id}' was not found."
        ) from error

    # Prevent one authenticated API context from accessing a quote generated
    # for another business, API key, or environment.
    if (
        quote.business_owner_id != context.business_owner_id
        or quote.api_key_id != context.api_key_id
        or quote.environment != context.environment
    ):
        raise QuoteAccessError(
            "The requested quote is not available for this API context."
        )

    # Enforce expiration immediately instead of relying only on MongoDB's
    # asynchronous TTL cleanup process.
    if quote.expires_at <= timezone.now():
        raise QuoteExpiredError(
            "The requested quote has expired."
        )

    return quote

def save_quote(
    validated_data: dict[str, Any],
    context: QuoteContext,
    route_km: Decimal,
    breakdown: dict[str, Any],
    total: Decimal,
    resolved_stops: list[dict[str, Any]],
) -> ApiQuote:
    """Persist a calculated delivery quote in MongoDB."""

    if not all([
        context.business_owner_id,
        context.api_key_id,
        context.environment,
    ]):
        raise QuoteServiceError(
            "Authenticated API context is required."
        )

    if not isinstance(route_km, Decimal) or not route_km.is_finite() or route_km < 0:
        raise QuoteServiceError("route_km must be a non-negative Decimal.")

    if not isinstance(total, Decimal) or not total.is_finite() or total < 0:
        raise QuoteServiceError("total must be a non-negative Decimal.")

    if not isinstance(breakdown, dict):
        raise QuoteServiceError("breakdown must be an object.")

    if not isinstance(resolved_stops, list):
        raise QuoteServiceError("resolved_stops must be a list.")

    # Pricing and routing values must come from the existing Aerrand services.
    return ApiQuote.objects.create(
        id=generate_quote_id(),
        business_owner_id=context.business_owner_id,
        api_key_id=context.api_key_id,
        environment=context.environment,
        inputs_hash=generate_inputs_hash(validated_data),
        inputs=validated_data,
        route_km=route_km,
        breakdown=breakdown,
        total=str(total),
        resolved_stops=resolved_stops,
        expires_at=calculate_quote_expiration(),
    )