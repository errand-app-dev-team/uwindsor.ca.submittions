
"""HTTP endpoints for managing partner webhook subscriptions."""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from developer.models import WebhookSubscription
from developer.services.key_authorization import (
    ApiKeyAuthorizationError,
    require_api_key_scope,
    scope_error_response,
)
from developer.services.webhook_service import WebhookServiceError
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
)

logger = logging.getLogger(__name__)


def webhook_error(code, message, status):
    """Return a consistent webhook API error."""
    return JsonResponse(
        {"error": code, "message": str(message)},
        status=status,
    )


def webhook_context(request, required_scope):
    """Verify the authenticated business context and required permission."""
    business_owner_id = getattr(request, "business_owner_id", None)
    environment = getattr(request, "api_environment", None)
    api_key_id = getattr(request, "api_key_id", None)

    if not all((business_owner_id, environment, api_key_id)):
        return None, webhook_error(
            "authentication_required",
            "Authenticated API-key context is required.",
            401,
        )

    try:
        require_api_key_scope(request, required_scope)
    except ApiKeyAuthorizationError:
        return None, scope_error_response(required_scope)

    return {
        "business_owner_id": business_owner_id,
        "environment": environment,
    }, None


def serialize_subscription(subscription):
    """Return subscription details without exposing its signing secret."""
    return {
        "id": str(subscription.id),
        "endpoint_url": subscription.endpoint_url,
        "environment": subscription.environment,
        "subscribed_events": subscription.subscribed_events,
        "is_active": subscription.is_active,
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhooks_collection(request):
    """Create or list webhook subscriptions for the authenticated business."""
    required_scope = (
        # "webhooks:write" if request.method == "POST" else "webhooks:read"
        "webhooks:manage"
    )

    context, error = webhook_context(request, required_scope)
    if error is not None:
        return error

    if request.method == "GET":
        subscriptions = WebhookSubscription.objects.filter(
            business_owner_id=context["business_owner_id"],
            environment=context["environment"],
        ).order_by("-created_at")[:100]

        return JsonResponse(
            {"data": [serialize_subscription(item) for item in subscriptions]},
            status=200,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return webhook_error("invalid_json", "Request body must be valid JSON.", 400)

    if not isinstance(data, dict):
        return webhook_error(
            "invalid_request",
            "Request body must be a JSON object.",
            400,
        )

    try:
        result = create_webhook_subscription(
            business_owner_id=context["business_owner_id"],
            environment=context["environment"],
            endpoint_url=data.get("endpoint_url"),
            subscribed_events=data.get("subscribed_events"),
        )
    except (WebhookServiceError, ValueError) as error:
        return webhook_error("invalid_subscription", error, 400)

    # The signing secret is returned only when the subscription is created.
    response = JsonResponse(result, status=201)
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_POST
def disable_webhook(request, subscription_id):
    """Disable a subscription belonging to the authenticated business."""
    # context, error = webhook_context(request, "webhooks:write")
    context, error = webhook_context(request, "webhooks:manage")
    if error is not None:
        return error

    try:
        subscription = WebhookSubscription.objects.get(
            id=subscription_id,
            business_owner_id=context["business_owner_id"],
            environment=context["environment"],
        )
    except WebhookSubscription.DoesNotExist:
        return webhook_error(
            "subscription_not_found",
            "Webhook subscription not found.",
            404,
        )

    subscription.is_active = False
    subscription.save(update_fields=["is_active", "updated_at"])

    return JsonResponse(serialize_subscription(subscription), status=200)
