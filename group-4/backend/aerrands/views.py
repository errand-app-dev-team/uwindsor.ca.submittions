"""HTTP views for the Aerrand Partner API."""

from aerrands.models import ApiBookingHistory
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from .services.quote_service import (
    QuoteAccessError as QuoteRetrievalAccessError,
    QuoteContext,
    QuoteExpiredError as QuoteRetrievalExpiredError,
    QuoteIntegrationUnavailableError,
    QuoteNotFoundError as QuoteRetrievalNotFoundError,
    QuoteServiceError,
    QuoteInputError,
    create_quote as create_quote_service,
    get_quote as get_quote_service,
)

from .services.aerrand_service import (
    AerrandContext,
    AerrandIntegrationUnavailableError,
    AerrandServiceError,
    AerrandValidationError,
    QuoteAccessError,
    QuoteExpiredError,
    QuoteNotFoundError,
    cancel_aerrand as cancel_aerrand_service,
    create_aerrand as create_aerrand_service,
    get_aerrand as get_aerrand_service,
    get_aerrand_proof as get_aerrand_proof_service,
    get_aerrand_tracking as get_aerrand_tracking_service,
    list_aerrands as list_aerrands_service,
    update_aerrand_dropoff as update_aerrand_dropoff_service,
    update_aerrand_pickup as update_aerrand_pickup_service,
    get_public_aerrand_tracking as get_public_aerrand_tracking_service, generate_item_checklist,
    attach_aerrand_checklist as attach_aerrand_checklist_service,
    attach_aerrand_tags as attach_aerrand_tags_service,
    get_service_areas as get_service_areas_service,
)

from developer.services.daily_quota import (
    DailyCreationQuotaExceeded,
    release_daily_creation,
    reserve_daily_creation,
)
from developer.services.idempotency_service import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    claim_idempotency_key,
    complete_idempotency_record,
    release_idempotency_record,
)

from .validators import (
    RequestValidationError,
    validate_aerrand_request,
    validate_quote_request,
    validate_pagination_limit,
    validate_pagination_cursor,
    DeliveryValidationError,
    validate_delivery_creation,
    validate_delivery_details, validate_dropoff_update, validate_pickup_update, validate_checklist_generate,
    validate_attach_checklist, validate_attach_tags,
)


def error_response(code, message, status):
    """Return a consistent API error response."""
    return JsonResponse(
        {
            "error": code,
            "message": str(message),
        },
        status=status,
    )


def parse_json_body(request):
    """Parse the request body and return data or a JSON error response."""
    try:
        return json.loads(request.body), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, error_response(
            "invalid_json",
            "Request body must contain valid JSON.",
            400,
        )


def get_authenticated_context(request, context_class):
    """Build a service context from authenticated request attributes."""
    business_owner_id = getattr(request, "business_owner_id", None)
    api_key_id = getattr(request, "api_key_id", None)
    environment = getattr(request, "api_environment", None)

    if not all([business_owner_id, api_key_id, environment]):
        return None

    return context_class(
        business_owner_id=business_owner_id,
        api_key_id=api_key_id,
        environment=environment,
    )


def authentication_error():
    """Return an error when the authentication context is unavailable."""
    return error_response(
        "authentication_context_unavailable",
        "Authenticated API context is not available for this request.",
        503,
    )


def aerrand_service_error(error):
    """Convert known Aerrand service exceptions into HTTP responses."""
    if isinstance(error, AerrandIntegrationUnavailableError):
        return error_response(
            "aerrand_service_unavailable",
            error,
            503,
        )

    return error_response(
        "aerrand_processing_error",
        error,
        500,
    )


def quote_lookup_error(error):
    """Convert quote lookup exceptions into HTTP responses."""
    if isinstance(error, (QuoteRetrievalNotFoundError, QuoteRetrievalAccessError)):
        return error_response(
            "quote_not_found",
            "Quote not found.",
            404,
        )

    if isinstance(error, QuoteRetrievalExpiredError):
        return error_response(
            "quote_expired",
            error,
            400,
        )

    return error_response(
        "quote_processing_error",
        error,
        500,
    )


def aerrand_quote_error(error):
    """Convert quote errors raised during Aerrand creation."""
    if isinstance(error, (QuoteNotFoundError, QuoteAccessError)):
        return error_response(
            "quote_not_found",
            "Quote not found.",
            404,
        )

    if isinstance(error, QuoteExpiredError):
        return error_response(
            "quote_expired",
            error,
            400,
        )

    return aerrand_service_error(error)



def serialize_quote(quote):
    """Convert a stored quote into its API response representation."""
    return {
        "id": quote.id,
        "object": "quote",
        "expires_at": quote.expires_at.isoformat(),
        "route_km": str(quote.route_km),
        "total": quote.total,
        "breakdown": quote.breakdown,
        "resolved_stops": quote.resolved_stops,
    }


@csrf_exempt
@require_POST
def create_quote(request):
    """Handle POST /v1/quotes."""
    data, error = parse_json_body(request)
    if error is not None:
        return error

    try:
        validated_data = validate_quote_request(data)
    except RequestValidationError as error:
        return error_response(error.code, error, 400)

    context = get_authenticated_context(request, QuoteContext)
    if context is None:
        return authentication_error()

    try:
        quote = create_quote_service(validated_data, context)
    except QuoteIntegrationUnavailableError as error:
        return error_response("quote_service_unavailable", error, 503)
    except QuoteInputError as error:
        # Return a client error when the pricing service cannot process the input.
        return error_response("validation_error", error, 400)
    except QuoteServiceError as error:
        return error_response("quote_processing_error", error, 500)

    return JsonResponse(serialize_quote(quote), status=200)


@csrf_exempt
@require_GET
def retrieve_quote(request, quote_id):
    """Handle GET /v1/quotes/{quote_id}."""
    context = get_authenticated_context(request, QuoteContext)
    if context is None:
        return authentication_error()

    try:
        quote = get_quote_service(quote_id, context)
    except (
        QuoteRetrievalNotFoundError,
        QuoteRetrievalAccessError,
        QuoteRetrievalExpiredError,
    ) as error:
        return quote_lookup_error(error)

    return JsonResponse(serialize_quote(quote), status=200)


@csrf_exempt
@require_POST
def create_aerrand(request):
    """Handle POST /v1/errands."""

    data, error = parse_json_body(request)
    if error is not None:
        return error

    # Validate the delivery request and its pickup/drop-off details.
    try:
        validated_data = validate_delivery_creation(data)
        validate_delivery_details(validated_data)

    except (RequestValidationError, DeliveryValidationError) as error:
        return error_response(
            "invalid_delivery_request",
            error,
            400,
        )

    # Retrieve the authenticated business and API-key context.
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    # Require an idempotency key to prevent duplicate bookings.
    idempotency_key = request.headers.get("Idempotency-Key")

    if not idempotency_key or not idempotency_key.strip():
        return error_response(
            "missing_idempotency_key",
            "Idempotency-Key header is required.",
            400,
        )

    if len(idempotency_key) > 64:
        return error_response(
            "invalid_idempotency_key",
            "Idempotency-Key must not exceed 64 characters.",
            400,
        )

    # Claim the key before attempting delivery creation.
    try:
        record, replay = claim_idempotency_key(
            business_owner_id=context.business_owner_id,
            key=idempotency_key,
            method=request.method,
            path=request.path,
            data=data,
        )

    except IdempotencyConflictError as error:
        return error_response(
            "idempotency_conflict",
            error,
            409,
        )

    except IdempotencyInProgressError as error:
        return error_response(
            "idempotency_in_progress",
            error,
            409,
        )

    # Return the original response for a completed request.
    if replay:
        response = JsonResponse(
            record.response_body,
            status=record.response_status,
        )
        response["Idempotency-Replayed"] = "true"
        return response

    # Reserve a daily creation slot before attempting the booking.
    try:
        usage_id = reserve_daily_creation(context.business_owner_id)
    except DailyCreationQuotaExceeded as error:
        # No booking was attempted. Allow retry after the quota resets.
        release_idempotency_record(record)
        response = error_response("daily_quota_exceeded", error, 429)
        response["Retry-After"] = str(error.retry_after)
        return response

    # Create the delivery through the Aerrand service layer.
    try:
        aerrand = create_aerrand_service(
            validated_data,
            context,
        )

    except (QuoteNotFoundError, QuoteAccessError, QuoteExpiredError) as error:
        release_daily_creation(usage_id)
        response = aerrand_quote_error(error)

    except (AerrandIntegrationUnavailableError, AerrandValidationError) as error:
        release_daily_creation(usage_id)
        # Preserve the idempotency claim when the service is unavailable.
        return aerrand_service_error(error)

    except AerrandServiceError as error:
        response = aerrand_service_error(error)

    except Exception:
        # Preserve the claim if the booking outcome is uncertain.
        raise

    else:
        batch_id = aerrand.get("batch_id")
        booking_id = aerrand.get("errand_id") or aerrand.get("id")
        stops = aerrand.get("stops")
        stop_ids = [
            str(stop["errand_id"])
            for stop in (stops if isinstance(stops, list) else [])
            if isinstance(stop, dict) and stop.get("errand_id")
        ]
        ApiBookingHistory.objects.get_or_create(
            claim_id=str(record.pk),
            defaults={
                "business_owner_id": context.business_owner_id,
                "environment": context.environment,
                "booking_id": str(booking_id) if booking_id else "",
                "batch_id": str(batch_id) if batch_id else "",
                "stop_ids": stop_ids,
                "external_reference": validated_data.get("reference") or "",
            },
        )
        response = JsonResponse(aerrand, status=201)

    if response.status_code >= 500:
        # Do not retry automatically when the outcome is uncertain.
        return response

    # Save the completed response for future idempotent replays.
    complete_idempotency_record(record, response)

    return response


@csrf_exempt
@require_GET
def list_aerrands(request):
    """Handle GET /v1/aerrands."""
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    try:
        limit = validate_pagination_limit(request.GET.get("limit"))
        cursor = validate_pagination_cursor(request.GET.get("cursor"))
    except RequestValidationError as error:
        return error_response(error.code, error, 400)

    try:
        result = list_aerrands_service(
            context=context,
            cursor=cursor,
            limit=limit,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@csrf_exempt
@require_http_methods(["GET", "POST"])
def aerrands_collection(request):
    """Dispatch Aerrand collection requests by HTTP method."""
    if request.method == "GET":
        return list_aerrands(request)

    return create_aerrand(request)


@require_GET
def retrieve_aerrand(request, aerrand_id):
    """Handle GET /v1/aerrands/{aerrand_id}."""
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    try:
        aerrand = get_aerrand_service(
            aerrand_id=aerrand_id,
            context=context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(aerrand, status=200)


@require_GET
def retrieve_aerrand_tracking(request, aerrand_id):
    """Handle GET /v1/aerrands/{aerrand_id}/tracking."""
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    try:
        tracking = get_aerrand_tracking_service(
            aerrand_id=aerrand_id,
            context=context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(tracking, status=200)


@require_GET
def retrieve_aerrand_proof(request, aerrand_id):
    """Handle GET /v1/aerrands/{aerrand_id}/proof."""
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    try:
        proof = get_aerrand_proof_service(
            aerrand_id=aerrand_id,
            context=context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(proof, status=200)


@csrf_exempt
@require_POST
def cancel_aerrand(request, aerrand_id):
    """Handle POST /v1/aerrands/{aerrand_id}/cancel."""
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    try:
        result = cancel_aerrand_service(
            aerrand_id=aerrand_id,
            context=context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@csrf_exempt
@require_http_methods(["PATCH"])
def update_aerrand_dropoff(request, aerrand_id, stop_id):
    """Handle updates to an existing Aerrand delivery drop-off."""

    # Validate the request body before passing it to the service layer.
    data, error = parse_json_body(request)
    if error is not None:
        return error

    try:
        validated_data = validate_dropoff_update(data)

    except RequestValidationError as error:
        return error_response(
            "invalid_dropoff_update",
            error,
            400,
        )

    # Identify the authenticated business making the update.
    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    # Forward the update to the existing Aerrand integration service.
    try:
        updated_dropoff = update_aerrand_dropoff_service(
            aerrand_id=aerrand_id,
            stop_id=stop_id,
            changes=validated_data,
            context=context,
        )

    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(updated_dropoff, status=200)

@csrf_exempt
@require_http_methods(["PUT"])
def update_aerrand_pickup(request, aerrand_id):
    """Handle PUT /v1/errands/{id}/pickup."""

    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    data, error = parse_json_body(request)
    if error is not None:
        return error

    try:
        validated_data = validate_pickup_update(data)
    except RequestValidationError as error:
        return error_response(
            "invalid_pickup_update",
            str(error),
            400,
        )

    try:
        result = update_aerrand_pickup_service(
            aerrand_id=aerrand_id,
            changes=validated_data,
            context=context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@require_GET
def retrieve_public_aerrand_tracking(request, aerrand_id):
    """Handle public tracking without API-key authentication."""

    try:
        result = get_public_aerrand_tracking_service(
            aerrand_id=aerrand_id,
        )

    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@csrf_exempt
@require_POST
def generate_checklist(request):
    """Handle POST /v1/checklists/generate."""

    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    data, error = parse_json_body(request)
    if error is not None:
        return error

    try:
        validated_data = validate_checklist_generate(data)
    except RequestValidationError as error:
        return error_response(
            "validation_failed",
            str(error),
            400,
        )

    try:
        result = generate_item_checklist(
            validated_data,
            context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@csrf_exempt
@require_POST
def attach_aerrand_checklist(request, aerrand_id):
    """Handle POST /v1/errands/{id}/checklist."""

    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    data, error = parse_json_body(request)
    if error is not None:
        return error

    try:
        validated_data = validate_attach_checklist(data)
    except RequestValidationError as error:
        return error_response(
            "validation_failed",
            str(error),
            400,
        )

    try:
        result = attach_aerrand_checklist_service(
            aerrand_id=aerrand_id,
            validated_data=validated_data,
            context=context,
        )
    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@csrf_exempt
@require_POST
def attach_aerrand_tags(request, aerrand_id):
    """Handle POST /v1/errands/{id}/tags."""

    context = get_authenticated_context(request, AerrandContext)
    if context is None:
        return authentication_error()

    data, error = parse_json_body(request)
    if error is not None:
        return error

    try:
        validated_data = validate_attach_tags(data)

    except RequestValidationError as error:
        return error_response(
            "validation_failed",
            str(error),
            400,
        )

    try:
        result = attach_aerrand_tags_service(
            aerrand_id=aerrand_id,
            validated_data=validated_data,
            context=context,
        )

    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)

@require_GET
def retrieve_service_areas(request):
    """Handle GET /v1/service-areas."""

    context = get_authenticated_context(request, AerrandContext)

    if context is None:
        return authentication_error()

    try:
        result = get_service_areas_service(context)

    except AerrandServiceError as error:
        return aerrand_service_error(error)

    return JsonResponse(result, status=200)
