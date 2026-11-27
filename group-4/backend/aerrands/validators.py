# Common exception for invalid Partner API request data.
# Views can catch this exception and return a consistent validation response.
class RequestValidationError(ValueError):
    def __init__(self, message, code="validation_error",  details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}  # extra info, e.g. {"field": "pickup.lat"}

# Parcel categories currently supported by the Aerrand quote specification.
VALID_PARCEL_SIZES = {"small", "medium", "large", "xl"}

#Delivery stacking: one pickup can have atmost 5 drop offs stops.
MAX_STOPS = 5

AERRAND_ALLOWED_TAGS = {
    "Marketplace",
    "Food",
    "Electronics",
    "Documents",
    "Clothing",
    "Groceries",
    "Furniture",
    "Gifts",
    "Medical",
    "Fragile",
}


def validate_stop_count(stops):
    """Reject requests exceeding the maximum number of delivery stops."""

    if len(stops) > MAX_STOPS:
        raise RequestValidationError(
            f"stops must not contain more than {MAX_STOPS} stops.",
            code="too_many_stops",
        )

import math


def validate_location(location, field_name, coordinates_as_strings=False):
    """Validate pickup or stop coordinates and address information."""

    if not isinstance(location, dict):
        raise RequestValidationError(
            f"{field_name} must be an object."
        )

    has_coordinates = "lat" in location and "lng" in location

    # NEW: create-delivery requests send coordinates as strings. Convert them
    # to numbers here so the existing range / finite / (0, 0) checks below are
    # reused unchanged.
    if coordinates_as_strings:
        if not has_coordinates:
            raise RequestValidationError(
                f"{field_name} lat and lng are required.",
                details={"field": field_name},
            )

        if not isinstance(location["lat"], str) or not isinstance(location["lng"], str):
            raise RequestValidationError(
                f"{field_name} lat and lng must be decimal strings.",
                details={"field": field_name},
            )

        try:
            # Work on a copy so the caller's request data is not modified.
            location = {
                **location,
                "lat": float(location["lat"]),
                "lng": float(location["lng"]),
            }
        except ValueError:
            raise RequestValidationError(
                f"{field_name} lat and lng must be numeric.",
                details={"field": field_name},
            )

    address = location.get("address")
    has_address = isinstance(address, str) and bool(address.strip())

    if not has_coordinates and not has_address:
        raise RequestValidationError(
            f"{field_name} must contain either lat/lng or address."
        )

    if has_coordinates:
        lat = location["lat"]
        lng = location["lng"]

        # Reject booleans and non-finite values even though Python treats
        # booleans as integers.
        for coordinate, value in [("lat", lat), ("lng", lng)]:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise RequestValidationError(
                    f"{field_name} {coordinate} must be a finite number."
                )

        if not -90 <= lat <= 90:
            raise RequestValidationError(
                f"{field_name} latitude must be between -90 and 90."
            )

        if not -180 <= lng <= 180:
            raise RequestValidationError(
                f"{field_name} longitude must be between -180 and 180."
            )
        if lat == 0 and lng ==0:
            raise RequestValidationError(
                f"{field_name} coordinates cannot be (0, 0)."
            )

    if "address" in location and not has_address:
        raise RequestValidationError(
            f"{field_name} address must be a non-empty string."
        )

def validate_parcels(parcels, stop_number, allow_zero=False):
    """
    Validate parcel quantities for an individual delivery stop.
    """
    if not isinstance(parcels, dict) or not parcels:
        raise RequestValidationError(
            f"Stop {stop_number} must contain parcels."
        )

    total = 0
    for size, quantity in parcels.items():

        # Reject parcel categories not defined by the current API specification.
        if size not in VALID_PARCEL_SIZES:
            raise RequestValidationError(
                f"Unsupported parcel size: {size}."
            )

        # bool is explicitly rejected because bool is a subclass of int in Python.
        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity < (0 if allow_zero else 1)
        ):
            raise RequestValidationError(
                f"Parcel quantity for {size} must be a "
                f"{'non-negative' if allow_zero else 'positive'} integer."
            )
        total += quantity

    if total == 0:
        raise RequestValidationError(
            f"Stop {stop_number} must contain at least one parcel."
        )


def validate_quote_request(data):
    """
    Validate the request body for POST /v1/quotes.

    Required structure:
        pickup
        stops[]
            location information
            parcels
    """
    if not isinstance(data, dict):
        raise RequestValidationError(
            "Request body must be a JSON object."
        )

    # Pickup and at least one delivery stop are required to calculate a quote.
    if "pickup" not in data:
        raise RequestValidationError("pickup is required.")

    if "stops" not in data:
        raise RequestValidationError("stops is required.")

    validate_location(data["pickup"], "pickup")

    stops = data["stops"]

    # A delivery quote must contain at least one destination.
    if not isinstance(stops, list) or not stops:
        raise RequestValidationError(
            "stops must be a non-empty list."
        )

    validate_stop_count(stops)

    # Validate every delivery destination independently.
    for index, stop in enumerate(stops, start=1):
        validate_location(stop, f"stop {index}")

        if "parcels" not in stop:
            raise RequestValidationError(
                f"Stop {index} must contain parcels."
            )

        validate_parcels(stop["parcels"], index)

    # Returning the validated data allows the service layer to process it next.
    return data

# Payment modes supported by the create-aerrand request specification.
VALID_PAYMENT_MODES = {"wallet", "checkout"}

# Constants for the documented create-delivery contact.
MAX_TEXT_LENGTH = 255
PICKUP_PREFERENCES = {"pickup"}
DROPOFF_PREFERENCES = {"leave_at_door", "meet_at_door", "meet_at_curb"}

def validate_contact(contact, field_name, allowed_preferences=None):
    """
    Validate contact information used for pickup contacts and recipients.

    Contact objects may contain a name and phone number. When provided,
    the object itself must have the expected structure.

    When allowed_preferences is given, the contact must follow the documented
    create-delivery shape: name, phone_number and preference are required;
    instructions and email are optional text.
    """
    if not isinstance(contact, dict):
        raise RequestValidationError(
            f"{field_name} must be an object."
        )

    if "name" in contact and not isinstance(contact["name"], str):
        raise RequestValidationError(
            f"{field_name} name must be a string."
        )

    if "phone" in contact and not isinstance(contact["phone"], str):
        raise RequestValidationError(
            f"{field_name} phone must be a string."
        )
    if allowed_preferences is None:
        return

        #Documented create-delivery contact.
    for key in ("name", "phone_number"):
        value = contact.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RequestValidationError(
                f"{field_name} {key} is required and must be a non-empty string.",
                details={"field": f"{field_name}.{key}"},
            )

    for key in ("instructions", "email"):
        if key in contact and not isinstance(contact[key], str):
            raise RequestValidationError(
                f"{field_name} {key} must be a string.",
                details={"field": f"{field_name}.{key}"},
            )

    for key in ("name", "phone_number", "instructions", "email"):
        if len(contact.get(key, "")) > MAX_TEXT_LENGTH:
            raise RequestValidationError(
                f"{field_name} {key} must be at most {MAX_TEXT_LENGTH} characters.",
                details={"field": f"{field_name}.{key}"},
            )

    if contact.get("preference") not in allowed_preferences:
        allowed = ", ".join(sorted(allowed_preferences))
        raise RequestValidationError(
            f"{field_name} preference must be one of: {allowed}.",
            details={"field": f"{field_name}.preference"},
        )

def validate_aerrand_request(data):
    """
    Validate the request body for POST /v1/aerrands.

    The endpoint creates an Aerrand using a previously generated quote.
    This function validates only request structure and basic field types.
    Business rules such as quote ownership, quote expiration, pricing,
    payment, and delivery creation belong in the service layer.
    """

    if not isinstance(data, dict):
        raise RequestValidationError(
            "Request body must be a JSON object."
        )

    # A create request must reference a quote generated previously.
    quote_id = data.get("quote_id")

    if not isinstance(quote_id, str) or not quote_id.strip():
        raise RequestValidationError(
            "quote_id is required and must be a non-empty string."
        )

    # Pickup information is required for delivery creation.
    if "pickup" not in data:
        raise RequestValidationError("pickup is required.")

    pickup = data["pickup"]

    validate_location(pickup, "pickup")

    # Validate pickup contact information when supplied.
    if "contact" in pickup:
        validate_contact(
            pickup["contact"],
            "pickup contact",
        )

    # At least one delivery destination is required.
    stops = data.get("stops")

    if not isinstance(stops, list) or not stops:
        raise RequestValidationError(
            "stops must be a non-empty list."
        )

    validate_stop_count(stops)

    for index, stop in enumerate(stops, start=1):
        if not isinstance(stop, dict):
            raise RequestValidationError(
                f"Stop {index} must be an object."
            )

        # Each stop must identify its destination.
        validate_location(stop, f"stop {index}")

        # Each stop in the supplied create-aerrand structure contains
        # parcel information describing what will be delivered.
        if "parcels" not in stop:
            raise RequestValidationError(
                f"Stop {index} must contain parcels."
            )

        validate_parcels(
            stop["parcels"],
            index,
        )

        # Recipient details are validated when supplied.
        if "recipient" in stop:
            validate_contact(
                stop["recipient"],
                f"stop {index} recipient",
            )

        # Per-stop external references are optional, but must be strings.
        if (
            "external_reference" in stop
            and not isinstance(stop["external_reference"], str)
        ):
            raise RequestValidationError(
                f"Stop {index} external_reference must be a string."
            )

    # The top-level external reference is optional.
    if (
        "external_reference" in data
        and not isinstance(data["external_reference"], str)
    ):
        raise RequestValidationError(
            "external_reference must be a string."
        )

    # Partner-defined metadata must be represented as a JSON object.
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise RequestValidationError(
            "metadata must be an object."
        )

    # max_total is optional. The specification represents monetary
    # amounts as decimal strings, for example "45.00".
    if "max_total" in data and not isinstance(data["max_total"], str):
        raise RequestValidationError(
            "max_total must be a string."
        )

    # Validate the payment object when the partner provides one.
    if "payment" in data:
        payment = data["payment"]

        if not isinstance(payment, dict):
            raise RequestValidationError(
                "payment must be an object."
            )

        mode = payment.get("mode")

        if mode not in VALID_PAYMENT_MODES:
            raise RequestValidationError(
                "payment mode must be either wallet or checkout."
            )

    return data

def validate_pagination_limit(value):
    """Validate the requested number of records per page."""
    if value is None:
        return 20

    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise RequestValidationError(
            "limit must be a valid integer."
        )

    if isinstance(value, bool) or str(limit) != str(value):
        raise RequestValidationError(
            "limit must be a valid integer."
        )

    if not 1 <= limit <= 100:
        raise RequestValidationError(
            "limit must be between 1 and 100."
        )

    return limit

def validate_pagination_cursor(value):
    """Validate the optional opaque pagination cursor."""
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(
            "cursor must be a non-empty string."
        )

    return value

from datetime import datetime, timezone


class DeliveryValidationError(ValueError):
    """Raised when a delivery creation request contains invalid data."""


def validate_delivery_creation(data):
    """Validate the required fields for creating a delivery."""

    if not isinstance(data, dict):
        raise DeliveryValidationError("Request body must be a JSON object.")

    # Validate the quote reference.
    quote_id = data.get("quote_id")
    if not isinstance(quote_id, str) or not quote_id.strip():
        raise DeliveryValidationError("quote_id is required.")

    # Validate the requested vehicle.
    vehicle_type = data.get("vehicle_type")
    if not isinstance(vehicle_type, str) or not vehicle_type.strip():
        raise DeliveryValidationError("vehicle_type is required.")

    # A delivery must have a pickup location.
    pickup = data.get("pickup")
    if not isinstance(pickup, dict):
        raise DeliveryValidationError("pickup must be an object.")

    # Single-stop and multi-stop deliveries use different fields.
    has_dropoff = "dropoff" in data
    has_dropoffs = "dropoffs" in data

    if has_dropoff == has_dropoffs:
        raise DeliveryValidationError(
            "Provide either dropoff or dropoffs, but not both."
        )

    if has_dropoff:
        if not isinstance(data["dropoff"], dict):
            raise DeliveryValidationError("dropoff must be an object.")

        parcel = data.get("parcel")
        if not isinstance(parcel, dict):
            raise DeliveryValidationError("parcel must be an object.")

    if has_dropoffs:
        dropoffs = data["dropoffs"]

        if not isinstance(dropoffs, list) or not 1 <= len(dropoffs) <= 5:
            raise DeliveryValidationError(
                "dropoffs must contain between 1 and 5 stops."
            )

        if not all(isinstance(stop, dict) for stop in dropoffs):
            raise DeliveryValidationError(
                "Each dropoff must be an object."
            )

    # Scheduling is optional, but the timestamp must be valid if provided.
    scheduled_at = data.get("scheduled_at")

    if scheduled_at is not None:
        if not isinstance(scheduled_at, str):
            raise DeliveryValidationError(
                "scheduled_at must be an ISO 8601 timestamp."
            )

        try:
            scheduled_time = datetime.fromisoformat(
                scheduled_at.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise DeliveryValidationError(
                "scheduled_at must be a valid ISO 8601 timestamp."
            ) from error

        if scheduled_time.tzinfo is None:
            raise DeliveryValidationError(
                "scheduled_at must include a timezone."
            )

    return data

# ----------------------------------------------------------------------
# NEW: detailed checks for the documented create-delivery request shape.
# Kept separate from validate_delivery_creation (which checks the top level)
# because it checks what is INSIDE pickup / dropoff / dropoffs.
# ----------------------------------------------------------------------
def validate_delivery_location(location, field_name, allowed_preferences,
                               stop_number=None):
    """
    Validate one pickup, dropoff, or dropoffs[] entry of a create request.

    Reuses validate_location (coordinates), validate_contact (contact) and
    validate_parcels (parcels). stop_number is given only for entries of
    dropoffs[], which must also contain parcels.
    """
    if not isinstance(location, dict):
        raise RequestValidationError(
            f"{field_name} must be an object.",
            details={"field": field_name},
        )

    label = location.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_TEXT_LENGTH:
        raise RequestValidationError(
            f"{field_name} label is required (text, at most {MAX_TEXT_LENGTH} characters).",
            details={"field": f"{field_name}.label"},
        )

    validate_location(location, field_name, coordinates_as_strings=True)

    if "contact" not in location:
        raise RequestValidationError(
            f"{field_name} contact is required.",
            details={"field": f"{field_name}.contact"},
        )

    validate_contact(
        location["contact"],
        f"{field_name} contact",
        allowed_preferences,
    )

    if "reference" in location and not isinstance(location["reference"], str):
        raise RequestValidationError(
            f"{field_name} reference must be a string.",
            details={"field": f"{field_name}.reference"},
        )

    # Only entries of dropoffs[] carry their own parcels.
    if stop_number is not None:
        if "parcels" not in location:
            raise RequestValidationError(
                f"Stop {stop_number} must contain parcels."
            )

        validate_parcels(location["parcels"], stop_number, allow_zero=True)


def validate_delivery_details(data):
    """
    Check the pickup and drop-off(s) of a create-delivery request.

    Call this AFTER validate_delivery_creation, which already guarantees that
    pickup is an object, exactly one of dropoff / dropoffs is present, and
    dropoffs holds 1 to MAX_STOPS objects. Those checks are not repeated here.
    """
    validate_delivery_location(data["pickup"], "pickup", PICKUP_PREFERENCES)

    if "dropoff" in data:
        validate_delivery_location(data["dropoff"], "dropoff", DROPOFF_PREFERENCES)
    else:
        for index, stop in enumerate(data["dropoffs"], start=1):
            validate_delivery_location(
                stop,
                f"dropoffs[{index}]",
                DROPOFF_PREFERENCES,
                stop_number=index,
            )

    return data

# Fields that partners can update after creating a delivery.
ALLOWED_DROPOFF_UPDATE_FIELDS = {"contact", "instructions", "reference"}

def validate_dropoff_update(data):
    """Validate permitted changes to an existing delivery drop-off."""

    if not isinstance(data, dict) or not data:
        raise RequestValidationError(
            "Drop-off update must be a non-empty JSON object."
        )

    # Reject changes to pricing, parcels, or delivery destinations.
    unsupported_fields = set(data) - ALLOWED_DROPOFF_UPDATE_FIELDS

    if unsupported_fields:
        raise RequestValidationError(
            f"Unsupported drop-off update fields: {', '.join(sorted(unsupported_fields))}."
        )

    if "contact" in data:
        contact = data["contact"]

        if not isinstance(contact, dict) or not contact:
            raise RequestValidationError(
                "contact must be a non-empty object."
            )

        allowed_contact_fields = {
            "name",
            "phone_number",
            "email",
            "instructions",
            "preference",
        }

        unsupported_contact_fields = set(contact) - allowed_contact_fields

        if unsupported_contact_fields:
            raise RequestValidationError(
                "Unsupported contact fields: "
                + ", ".join(sorted(unsupported_contact_fields))
                + "."
            )

        # Only supplied contact fields are validated for partial updates.
        for field in ("name", "phone_number", "email", "instructions"):
            if field in contact:
                value = contact[field]

                if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
                    raise RequestValidationError(
                        f"contact {field} must be a string of at most "
                        f"{MAX_TEXT_LENGTH} characters."
                    )

                if field in {"name", "phone_number"} and not value.strip():
                    raise RequestValidationError(
                        f"contact {field} cannot be empty."
                    )

        if (
            "preference" in contact
            and contact["preference"] not in DROPOFF_PREFERENCES
        ):
            raise RequestValidationError(
                "contact preference must be one of: "
                + ", ".join(sorted(DROPOFF_PREFERENCES))
                + "."
            )

    for field in ("instructions", "reference"):
        if field in data:
            value = data[field]

            if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
                raise RequestValidationError(
                    f"{field} must be a string of at most "
                    f"{MAX_TEXT_LENGTH} characters."
                )

    return data

def validate_pickup_update(data):
    """Validate changes to an errand's pickup instructions."""
    if not isinstance(data, dict) or not data:
        raise RequestValidationError(
            "Pickup update must be a non-empty JSON object."
        )

    allowed_fields = {
        "name",
        "phone_number",
        "instructions",
        "preference",
        "email",
    }

    unknown_fields = set(data) - allowed_fields
    if unknown_fields:
        raise RequestValidationError(
            f"Unsupported pickup fields: {', '.join(sorted(unknown_fields))}"
        )

    for field, value in data.items():
        if not isinstance(value, str) or not value.strip():
            raise RequestValidationError(
                f"{field} must be a non-empty string."
            )

        if len(value) > 255:
            raise RequestValidationError(
                f"{field} must not exceed 255 characters."
            )

    if "preference" in data and data["preference"] != "pickup":
        raise RequestValidationError(
            "Pickup preference must be 'pickup'."
        )

    return data

from decimal import Decimal, InvalidOperation


def validate_checklist_generate(data):
    """Validate the item details used for checklist suggestions."""
    if not isinstance(data, dict):
        raise RequestValidationError("A JSON object is required.")

    allowed = {"description", "quantity", "size", "price"}
    unknown = set(data) - allowed

    if unknown:
        raise RequestValidationError(
            f"Unsupported fields: {', '.join(sorted(unknown))}"
        )

    description = data.get("description")

    if not isinstance(description, str) or not description.strip():
        raise RequestValidationError("description is required.")

    validated = {"description": description.strip()}

    if "quantity" in data:
        quantity = data["quantity"]
        if type(quantity) is not int or quantity < 1:
            raise RequestValidationError(
                "quantity must be a positive integer."
            )
        validated["quantity"] = quantity

    if "size" in data:
        if data["size"] not in ("small", "medium", "large", "xlarge"):
            raise RequestValidationError("Invalid checklist size.")
        validated["size"] = data["size"]

    if "price" in data:
        value = data["price"]

        if isinstance(value, bool) or not isinstance(
            value, (int, float)
        ):
            raise RequestValidationError("price must be a number.")

        try:
            price = Decimal(str(value))
        except InvalidOperation:
            raise RequestValidationError("Invalid price.")

        if not price.is_finite() or price < 0:
            raise RequestValidationError(
                "price must be a non-negative number."
            )

        validated["price"] = value

    return validated

def validate_attach_checklist(data):
    """Validate checklist items for an existing errand."""
    if not isinstance(data, dict):
        raise RequestValidationError("A JSON object is required.")

    if set(data) != {"checklists"}:
        raise RequestValidationError(
            "Request must contain only the checklists field."
        )

    items = data["checklists"]

    if not isinstance(items, list) or not items:
        raise RequestValidationError(
            "checklists must be a non-empty list."
        )

    if len(items) > 5:
        raise RequestValidationError(
            "A maximum of five checklist items is allowed."
        )

    unique_items = []
    seen = set()

    for item in items:
        if not isinstance(item, str):
            raise RequestValidationError(
                "Each checklist item must be a string."
            )

        item = item.strip()

        if not item or len(item) > 80:
            raise RequestValidationError(
                "Checklist items must contain 1 to 80 characters."
            )

        if item not in seen:
            unique_items.append(item)
            seen.add(item)

    return {"checklists": unique_items}

def validate_attach_tags(data):
    """Validate and deduplicate delivery tags."""
    if not isinstance(data, dict):
        raise RequestValidationError("A JSON object is required.")

    if set(data) != {"tags"}:
        raise RequestValidationError(
            "Request must contain only the tags field."
        )

    tags = data["tags"]

    if not isinstance(tags, list) or not tags:
        raise RequestValidationError(
            "tags must be a non-empty list."
        )

    unique_tags = []
    seen = set()

    for tag in tags:
        if not isinstance(tag, str):
            raise RequestValidationError(
                "Each tag must be a string."
            )

        tag = tag.strip()

        if tag not in AERRAND_ALLOWED_TAGS:
            raise RequestValidationError(
                f"Unsupported tag: {tag}"
            )

        if tag not in seen:
            unique_tags.append(tag)
            seen.add(tag)

    return {"tags": unique_tags}
