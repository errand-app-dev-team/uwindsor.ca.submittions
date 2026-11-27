
"""Aerrand service functions and integration boundaries for the Partner API."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from aerrands.models import ApiQuote
from aerrands.services.quote_service import (
    QuoteAccessError as ServiceQuoteAccessError,
    QuoteContext,
    QuoteExpiredError as ServiceQuoteExpiredError,
    QuoteNotFoundError as ServiceQuoteNotFoundError,
    get_quote,
    generate_inputs_hash

)

from aerrands.services.aerrand_adapter import (
    BookingRequest,
    PartnerIdentity,
    AerrandAdapterUnavailable,
    AerrandAdapterOutcomeUnknown,
    AerrandAdapterNotFound,
    AerrandAdapterConflict,
    get_aerrand_adapter,
)

from .payment_state import validate_payment_result, PaymentStateError

class AerrandServiceError(Exception):
    """Base exception for Aerrand service errors."""
    pass


class QuoteNotFoundError(AerrandServiceError):
    """Raised when a referenced quote does not exist."""
    pass


class QuoteAccessError(AerrandServiceError):
    """Raised when a quote is unavailable to the API context."""
    pass


class QuoteExpiredError(AerrandServiceError):
    """Raised when a referenced quote has expired."""
    pass


class AerrandIntegrationUnavailableError(AerrandServiceError):
    pass


class AerrandOutcomeUnknownError(AerrandServiceError):
    pass


class AerrandNotFoundError(AerrandServiceError):
    pass


class AerrandConflictError(AerrandServiceError):
    pass


class AerrandValidationError(AerrandServiceError):
    pass


@dataclass
class AerrandContext:
    """Authenticated business and API-key context."""

    business_owner_id: str
    api_key_id: str
    environment: str


def validate_aerrand_context(context: AerrandContext):
    """Validate the required authentication context."""
    if not context.business_owner_id:
        raise AerrandServiceError("business_owner_id is required.")

    if not context.api_key_id:
        raise AerrandServiceError("api_key_id is required.")

    if not context.environment:
        raise AerrandServiceError("environment is required.")


def validate_aerrand_id(aerrand_id: str):
    """Validate an Aerrand identifier."""
    if not isinstance(aerrand_id, str) or not aerrand_id.strip():
        raise AerrandValidationError("A valid Aerrand ID is required.")


def get_quote_for_aerrand(quote_id: str, context: AerrandContext) -> ApiQuote:
    """Retrieve a valid quote for the authenticated Aerrand context."""
    quote_context = QuoteContext(
        business_owner_id=context.business_owner_id,
        api_key_id=context.api_key_id,
        environment=context.environment,
    )

    try:
        return get_quote(quote_id, quote_context)
    except ServiceQuoteNotFoundError as error:
        raise QuoteNotFoundError(str(error)) from error
    except ServiceQuoteAccessError as error:
        raise QuoteAccessError(str(error)) from error
    except ServiceQuoteExpiredError as error:
        raise QuoteExpiredError(str(error)) from error


def get_partner_identity(context: AerrandContext) -> PartnerIdentity:
    """Convert the authenticated API context into the adapter's identity."""
    validate_aerrand_context(context)

    return PartnerIdentity(
        business_owner_id=context.business_owner_id,
        api_key_id=context.api_key_id,
        environment=context.environment,
    )


def call_aerrand_adapter(operation, *args, **kwargs):
    """Convert integration errors into the Partner API's service exceptions."""
    try:
        return operation(*args, **kwargs)

    except AerrandAdapterUnavailable as error:
        raise AerrandIntegrationUnavailableError(str(error)) from error

    except AerrandAdapterOutcomeUnknown as error:
        raise AerrandOutcomeUnknownError(str(error)) from error

    except AerrandAdapterNotFound as error:
        raise AerrandNotFoundError(str(error)) from error

    except AerrandAdapterConflict as error:
        raise AerrandConflictError(str(error)) from error


def build_booking_request(validated_data: dict[str, Any]) -> BookingRequest:
    """Normalize single-stop and multi-stop requests for the Aerrand adapter."""

    # The adapter uses a list of drop-offs for both delivery formats.
    if "dropoffs" in validated_data:
        dropoffs = validated_data["dropoffs"]
    else:
        dropoff = dict(validated_data["dropoff"])

        # Include the single delivery's parcel in the quoted stop inputs.
        parcel = validated_data.get("parcel")
        if parcel is not None:
            dropoff["parcels"] = {
                parcel["size"]: parcel["quantity"]
            }

        dropoffs = [dropoff]

    return BookingRequest(
        quote_id=validated_data["quote_id"],
        pickup=validated_data["pickup"],
        dropoffs=dropoffs,
        vehicle_type=validated_data["vehicle_type"],
        scheduled_at=validated_data.get("scheduled_at"),
        payment=validated_data.get("payment"),
        external_reference=validated_data.get("reference"),
        metadata=validated_data.get("metadata", {}),
        max_total=validated_data.get("max_total"),
    )

def normalize_booking_quote_inputs(booking: BookingRequest) -> dict[str, Any]:
    """Extract the routing and parcel inputs used to generate the original quote."""

    def normalize_location(location):
        # Booking contacts and labels do not affect the quoted route.
        normalized = {}

        for field in ("lat", "lng", "address"):
            if field in location:
                value = location[field]

                # Booking coordinates are decimal strings; quotes use numbers.
                if field in ("lat", "lng"):
                    value = float(value)

                normalized[field] = value

        return normalized

    pickup = normalize_location(booking.pickup)
    stops = []

    for dropoff in booking.dropoffs:
        stop = normalize_location(dropoff)

        # Preserve parcel quantities because they affect the quoted price.
        if "parcels" in dropoff:
            stop["parcels"] = dropoff["parcels"]

        stops.append(stop)

    return {
        "pickup": pickup,
        "stops": stops,
    }

def verify_booking_quote(booking: BookingRequest, quote: ApiQuote):
    """Verify the booking matches the original quote before creating a delivery."""

    # Check that the number of delivery stops matches the quote.
    if len(booking.dropoffs) != len(quote.inputs["stops"]):
        raise AerrandValidationError(
            "Delivery stop count does not match the quoted route."
        )

    # Check the maximum amount the partner is willing to pay.
    if booking.max_total is not None:
        try:
            maximum = Decimal(booking.max_total)
            total = Decimal(quote.total)

        except (InvalidOperation, ValueError, TypeError) as error:
            raise AerrandValidationError(
                "max_total must be a valid decimal amount."
            ) from error

        if not maximum.is_finite() or maximum < 0:
            raise AerrandValidationError(
                "max_total must be a non-negative finite amount."
            )

        if total > maximum:
            raise AerrandValidationError(
                "The quoted total exceeds max_total."
            )

    # Compare the booking's route and parcels against the stored quote.
    try:
        booking_inputs = normalize_booking_quote_inputs(booking)

        quoted_inputs = {
            "pickup": {
                field: value
                for field, value in quote.inputs["pickup"].items()
                if field in ("lat", "lng", "address")
            },
            "stops": [
                {
                    field: value
                    for field, value in stop.items()
                    if field in ("lat", "lng", "address", "parcels")
                }
                for stop in quote.inputs["stops"]
            ],
        }

        booking_hash = generate_inputs_hash(booking_inputs)
        quoted_hash = generate_inputs_hash(quoted_inputs)

    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise AerrandValidationError(
            "Unable to verify the booking against its original quote."
        ) from error

    if booking_hash != quoted_hash:
        raise AerrandValidationError(
            "Booking pickup, destinations, or parcels do not match the original quote."
        )

    return True



def create_aerrand(validated_data: dict[str, Any], context: AerrandContext):
    validate_aerrand_context(context)

    quote = get_quote_for_aerrand(validated_data["quote_id"], context)

    # Prepare the delivery request for the existing Aerrand platform.
    booking = build_booking_request(validated_data)

    # Verify the stored quote before allowing booking creation.
    verify_booking_quote(booking, quote)

    # Order, Delivery, and payment processing require the existing Aerrand platform.
    adapter = get_aerrand_adapter()

    result = call_aerrand_adapter(
        adapter.create_booking,
        booking,
        quote,
        get_partner_identity(context),
    )

    # Validate the response returned by Aerrand.
    if not isinstance(result, dict):
        raise AerrandOutcomeUnknownError(
            "Aerrand returned an invalid booking response."
        )

    payment = result.get("payment")

    # Validate payment details when the platform includes them.
    if payment is not None:
        try:
            payment_result = validate_payment_result(payment)
        except PaymentStateError as error:
            raise AerrandOutcomeUnknownError(str(error)) from error

        # A delivery must not be reported as dispatchable without confirmed payment.
        if payment_result.status != "paid" and result.get("status") in {
            "pending",
            "broadcasted",
            "accepted",
            "arrived",
            "picked_up",
            "in_transit",
            "arrived_dropoff",
            "delivered",
        }:
            raise AerrandOutcomeUnknownError(
                "Aerrand returned an inconsistent delivery payment state."
            )

    return result


def list_aerrands(context: AerrandContext, cursor: str | None = None, limit: int = 20):
    validate_aerrand_context(context)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.list_bookings,
        get_partner_identity(context),
        cursor=cursor,
        limit=limit,
    )


def get_aerrand(aerrand_id: str, context: AerrandContext):
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.get_booking,
        aerrand_id,
        get_partner_identity(context),
    )


def get_aerrand_tracking(aerrand_id: str, context: AerrandContext):
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.get_tracking,
        aerrand_id,
        get_partner_identity(context),
    )


def get_aerrand_proof(aerrand_id: str, context: AerrandContext):
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.get_proof,
        aerrand_id,
        get_partner_identity(context),
    )


def cancel_aerrand(aerrand_id: str, context: AerrandContext):
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.cancel_booking,
        aerrand_id,
        get_partner_identity(context),
    )



def update_aerrand_dropoff(
    aerrand_id: str,
    stop_id: str,
    changes: dict[str, Any],
    context: AerrandContext,
):
    """Forward drop-off updates for a specific delivery stop to Aerrand."""
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    if not isinstance(stop_id, str) or not stop_id.strip():
        raise AerrandValidationError("A valid stop ID is required.")

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.update_dropoff,
        aerrand_id,
        stop_id,
        changes,
        get_partner_identity(context),
    )

def update_aerrand_pickup(
    aerrand_id: str,
    changes: dict[str, Any],
    context: AerrandContext,
):
    """Forward validated pickup changes to the Aerrand integration."""
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.update_pickup,
        aerrand_id,
        changes,
        get_partner_identity(context),
    )

def get_public_aerrand_tracking(aerrand_id: str):
    """Retrieve the public-safe tracking data for an errand."""
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    result = call_aerrand_adapter(
        adapter.get_public_tracking,
        aerrand_id,
    )

    # Only expose fields documented for public customer tracking.
    data = result.get("data", {})

    if not isinstance(data, dict):
        raise AerrandServiceError(
            "Invalid public tracking response."
        )

    allowed_fields = {
        "errand_id",
        "status",
        "pickup",
        "dropoff",
        "driver",
        "driver_lat",
        "driver_lng",
        "timeline",
        "created_at",
    }

    public_data = {
        key: value
        for key, value in data.items()
        if key in allowed_fields
    }

    # Public responses must not include contact or payment details.
    for location_field in ("pickup", "dropoff"):
        location = public_data.get(location_field)

        if isinstance(location, dict):
            public_data[location_field] = {
                key: location[key]
                for key in ("label", "lat", "lng")
                if key in location
            }

    driver = public_data.get("driver")
    if isinstance(driver, dict):
        public_data["driver"] = {
            key: driver[key]
            for key in (
                "name",
                "image",
                "vehicle_model",
                "vehicle_type",
                "plate_number",
            )
            if key in driver
        }

    timeline = public_data.get("timeline")
    if isinstance(timeline, list):
        public_data["timeline"] = [
            {
                key: event[key]
                for key in ("at", "state")
                if key in event
            }
            for event in timeline
            if isinstance(event, dict)
        ]

    return {
        "success": True,
        "data": public_data,
    }

def generate_item_checklist(
    validated_data: dict[str, Any],
    context: AerrandContext,
):
    """Generate item checks or return empty suggestions when AI is unavailable."""
    validate_aerrand_context(context)

    empty_result = {
        "checklist": [],
        "suggested_size": None,
        "suggested_tags": [],
    }

    adapter = get_aerrand_adapter()

    try:
        result = call_aerrand_adapter(
            adapter.generate_checklist,
            validated_data,
            get_partner_identity(context),
        )
    except AerrandIntegrationUnavailableError:
        return empty_result

    if not isinstance(result, dict):
        raise AerrandServiceError("Invalid checklist response.")

    checklist = result.get("checklist")
    suggested_size = result.get("suggested_size")
    suggested_tags = result.get("suggested_tags")

    if (
        not isinstance(checklist, list)
        or len(checklist) > 5
        or any(
            not isinstance(item, str) or len(item) > 80
            for item in checklist
        )
    ):
        raise AerrandServiceError("Invalid checklist suggestions.")

    if suggested_size not in (None, "small", "medium", "large", "xlarge"):
        raise AerrandServiceError("Invalid suggested size.")

    if (
        not isinstance(suggested_tags, list)
        or not 1 <= len(suggested_tags) <= 3
        and suggested_tags != []
        or any(not isinstance(tag, str) for tag in suggested_tags)
    ):
        raise AerrandServiceError("Invalid suggested tags.")

    return {
        "checklist": checklist,
        "suggested_size": suggested_size,
        "suggested_tags": suggested_tags,
    }

def attach_aerrand_checklist(
    aerrand_id: str,
    validated_data: dict[str, Any],
    context: AerrandContext,
):
    """Attach condition checks to an existing errand."""
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.attach_checklist,
        aerrand_id,
        validated_data["checklists"],
        get_partner_identity(context),
    )

def attach_aerrand_tags(
    aerrand_id: str,
    validated_data: dict[str, Any],
    context: AerrandContext,
):
    """Attach validated category tags to an existing errand."""
    validate_aerrand_context(context)
    validate_aerrand_id(aerrand_id)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.attach_tags,
        aerrand_id,
        validated_data["tags"],
        get_partner_identity(context),
    )

def get_service_areas(context: AerrandContext) -> dict:
    """Retrieve Aerrand's current service coverage."""
    validate_aerrand_context(context)

    adapter = get_aerrand_adapter()

    return call_aerrand_adapter(
        adapter.get_service_areas,
        get_partner_identity(context),
    )
