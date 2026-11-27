import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from time import time

from developer.services.key_generation import create_api_key, KeyGenerationError

"""Developer dashboard and partner webhook subscription endpoints."""

import json
import logging
from datetime import timedelta, timezone as datetime_timezone
from uuid import UUID

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from developer.models import (
    ApiAuditLog,
    ApiKey,
    ApiRequestLog,
    BusinessAccount,
    WebhookDelivery,
    WebhookSubscription,
)
from developer.services.admin_identity import get_admin_audit_identity
from developer.services.key_authorization import (
    ApiKeyAuthorizationError,
    require_api_key_scope,
    scope_error_response,
)
from developer.services.revocation import (
    KeyAlreadyRevokedError,
    KeyNotFoundError,
    revoke_api_key,
)
from developer.services.notifications import (
    notify_administrator,
    notify_business_access_changed,
    notify_business_limits_updated,
    notify_webhook_disabled,

)
from developer.services.webhook_service import WebhookServiceError
from developer.services.webhook_subscription_service import create_webhook_subscription

logger = logging.getLogger(__name__)

from django_mongodb_backend import transaction

from developer.models import BusinessApiAccess
from developer.services.audit import log_audit
from developer.services.daily_quota import DEFAULT_DAILY_CREATION_QUOTA
from developer.services.rate_limit_service import DEFAULT_RATE_LIMIT, WINDOW_SECONDS
from developer.services.dashboard_auth import get_dashboard_identity


def effective_key_status(key, now):
    """Show expiration without changing the stored key status."""
    if key.status == "revoked":
        return "revoked"

    if key.expires_at and key.expires_at <= now:
        return "expired"

    return key.status


@require_GET
def admin_dashboard_data(request):
    """Return dashboard records for an authenticated business user."""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    identity = get_dashboard_identity(request.user)

    if identity is None:
        return JsonResponse(
            {"error": "Dashboard access denied."},
            status=403,
        )

    now = timezone.now().astimezone(datetime_timezone.utc)

    days_value = request.GET.get("days", "7")

    if days_value not in {"7", "30"}:
        return JsonResponse(
            {"error": "days must be 7 or 30."},
            status=400,
        )

    days = int(days_value)

    requested_business_id = request.GET.get(
        "business_owner_id", ""
    ).strip()
    api_key_id = request.GET.get("api_key_id", "").strip()

    if identity["role"] == "business":
        business_uuid = identity["business_owner_id"]
        business_id = str(business_uuid)

        # Restrict business users to their assigned business.
        if requested_business_id:
            try:
                requested_uuid = UUID(requested_business_id)
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid business_owner_id."},
                    status=400,
                )

            if requested_uuid != business_uuid:
                return JsonResponse(
                    {"error": "Access to this business is denied."},
                    status=403,
                )
    else:
        business_uuid = None
        business_id = ""

        # Administrators can inspect all businesses or select one.
        if requested_business_id:
            try:
                business_uuid = UUID(requested_business_id)
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid business_owner_id."},
                    status=400,
                )

            business_id = str(business_uuid)

    key_records = ApiKey.objects.all()
    request_records = ApiRequestLog.objects.all()
    event_records = ApiAuditLog.objects.all()

    # Scope all dashboard records before calculating totals.
    if business_uuid is not None:
        key_records = key_records.filter(
            business_owner_id=business_uuid,
        )
        request_records = request_records.filter(
            business_owner_id=business_uuid,
        )
        event_records = event_records.filter(
            business_owner_id=business_uuid,
        )


    # Match request logs by api_key_id and audit events by target_id.
    if api_key_id:
        try:
            key_uuid = UUID(api_key_id)
        except ValueError:
            return JsonResponse(
                {"error": "api_key_id must be a valid UUID."},
                status=400,
            )

        api_key_id = str(key_uuid)

        # When a business is selected, the key must belong to it.
        if not key_records.filter(pk=key_uuid).exists():
            return JsonResponse(
                {"error": "API key not found in the selected scope."},
                status=404,
            )

        key_records = key_records.filter(pk=key_uuid)
        request_records = request_records.filter(api_key_id=key_uuid)
        event_records = event_records.filter(target_id=key_uuid)

    today_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    period_start = today_start - timedelta(days=days - 1)

    trend = []

    for index in range(days):
        day_start = period_start + timedelta(days=index)
        day_end = min(day_start + timedelta(days=1), now)

        daily_requests = request_records.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
        )

        trend.append({
            "date": day_start.date().isoformat(),
            "requests": daily_requests.count(),
            "failed": daily_requests.filter(status__gte=400).count(),
        })

    period_requests = sum(day["requests"] for day in trend)
    period_failed = sum(day["failed"] for day in trend)

    # Calculate analytics from the full filtered querysets, before
    # applying the 100-record limit used by dashboard tables.
    analytics = {}

    for environment in ("test", "live"):
        environment_keys = key_records.filter(environment=environment)

        # Match requests to keys in the selected environment.
        # This also preserves business and API-key filters above.
        environment_requests = request_records.filter(
            api_key_id__in=environment_keys.values_list("id", flat=True)
        )

        last_24_hours = environment_requests.filter(
            created_at__gte=now - timedelta(hours=24),
            created_at__lte=now,
        )

        request_count = last_24_hours.count()
        failed_count = last_24_hours.filter(status__gte=400).count()
        successful_count = last_24_hours.filter(
            status__gte=200,
            status__lt=400,
        ).count()

        average_duration = last_24_hours.aggregate(
            average=Avg("duration_ms")
        )["average"]

        daily_requests = []

        for index in range(days):
            day_start = period_start + timedelta(days=index)
            day_end = min(day_start + timedelta(days=1), now)

            daily_queryset = environment_requests.filter(
                created_at__gte=day_start,
                created_at__lt=day_end,
            )

            daily_total = daily_queryset.count()
            daily_failed = daily_queryset.filter(
                status__gte=400
            ).count()
            daily_successful = daily_queryset.filter(
                status__gte=200,
                status__lt=400,
            ).count()

            daily_requests.append({
                "date": day_start.date().isoformat(),
                "requests": daily_total,
                "success": daily_successful,
                "failed": daily_failed,
            })

        active_keys = environment_keys.filter(
            status="active"
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        ).count()

        analytics[environment] = {
            "requests_24h": request_count,
            "successful_requests_24h": successful_count,
            "failed_requests_24h": failed_count,
            "success_rate_24h": (
                round(successful_count / request_count * 100, 1)
                if request_count else None
            ),
            "avg_response_ms_24h": (
                round(float(average_duration))
                if average_duration is not None else None
            ),
            "active_keys": active_keys,
            "daily_requests": daily_requests,
        }

    recent_requests = request_records.filter(
        created_at__gte=now - timedelta(hours=24),
        created_at__lte=now,
    )

    webhook_failure_rate = None
    completed_count = None
    failed_count = None
    delivered_count = None
    # Webhook subscriptions belong to a business, not an individual API key.
    if not api_key_id:
        completed_webhooks = WebhookDelivery.objects.filter(
            status__in=["delivered", "failed"],
            updated_at__gte=now - timedelta(hours=24),
            updated_at__lte=now,
        )
        if business_id:
            subscriptions = WebhookSubscription.objects.filter(
                business_owner_id=business_uuid,
            )
            completed_webhooks = completed_webhooks.filter(
                subscription_id__in=subscriptions.values_list("pk", flat=True),
            )
        delivered_count = completed_webhooks.filter(status="delivered").count()
        failed_count = completed_webhooks.filter(status="failed").count()
        completed_count = delivered_count + failed_count
        if completed_count:
            webhook_failure_rate = round(100 * failed_count / completed_count, 1)

    top_businesses = []
    if not business_id and not api_key_id:
        top_businesses = list(
            recent_requests
            .filter(business_owner_id__isnull=False)
            .values("business_owner_id")
            .annotate(request_count=Count("pk"))
            .order_by("-request_count", "business_owner_id")[:5]
        )

    if top_businesses:
        business_names = {
            str(pk): name
            for pk, name in BusinessAccount.objects.filter(
                pk__in=[row["business_owner_id"] for row in top_businesses],
            ).values_list("pk", "name")
        }
        for row in top_businesses:
            row["business_name"] = business_names.get(str(row["business_owner_id"]))

    from aerrands.models import ApiBookingHistory

    api_deliveries = []
    if not api_key_id:
        history = ApiBookingHistory.objects.all()
        if business_id:
            history = history.filter(business_owner_id=business_uuid)
        api_deliveries = list(
            history.order_by("-created_at", "-pk").values(
                "pk", "business_owner_id", "environment", "booking_id",
                "batch_id", "stop_ids", "external_reference", "created_at",
            )[:100]
        )
        for delivery in api_deliveries:
            delivery["pk"] = str(delivery["pk"])

    booking_requests = recent_requests
    if identity["role"] != "business":
        live_key_ids = key_records.filter(environment="live").values_list("id", flat=True)
        booking_requests = booking_requests.filter(api_key_id__in=live_key_ids)

    summary = {
        "api_deliveries": api_deliveries,
        "total_keys": key_records.count(),
        "active_keys": key_records.filter(
            status="active",
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        ).count(),
        "total_requests": request_records.count(),
        "requests_last_24h": recent_requests.count(),
        "webhook_failure_rate_last_24h": webhook_failure_rate,
        "webhook_completed_last_24h": completed_count,
        "webhook_delivered_last_24h": delivered_count,
        "webhook_failed_last_24h": failed_count,
        "top_businesses_last_24h": top_businesses,
        "api_bookings_last_24h": booking_requests.filter(
            method="POST",
            path__in=["/v1/errands", "/v1/errands/"],
            status=201,
            idempotenct_replay=False,
        ).count(),
        "failed_requests": request_records.filter(
            status__gte=400,
        ).count(),
    }

    keys = list(
        key_records.order_by("-created_at", "-id")[:100]
    )

    requests = list(
        request_records.order_by("-created_at", "-pk").values(
            "request_id",
            "api_key_id",
            "business_owner_id",
            "method",
            "path",
            "status",
            "duration_ms",
            "error_code",
            "created_at",
        )[:100]
    )

    request_business_ids = {
        row["business_owner_id"] for row in requests if row["business_owner_id"]
    }
    request_business_names = {
        str(business_id): name
        for business_id, name in BusinessAccount.objects.filter(
            pk__in=request_business_ids,
        ).values_list("pk", "name")
    }
    for row in requests:
        row["business_name"] = request_business_names.get(str(row["business_owner_id"]))

    events = list(
        event_records.order_by("-timestamp", "-pk").values(
            "action",
            "business_owner_id",
            "actor_id",
            "target_id",
            "timestamp",
        )[:100]
    )

    event_business_ids = {
        event["business_owner_id"] for event in events if event["business_owner_id"]
    }
    event_business_names = {
        str(business_id): name
        for business_id, name in BusinessAccount.objects.filter(
            pk__in=event_business_ids,
        ).values_list("pk", "name")
    }
    for event in events:
        event["business_name"] = event_business_names.get(
            str(event["business_owner_id"])
        )

    key_business_ids = {
        key.business_owner_id for key in keys if key.business_owner_id
    }
    key_business_names = {
        str(business_id): name
        for business_id, name in BusinessAccount.objects.filter(
            pk__in=key_business_ids,
        ).values_list("pk", "name")
    }

    key_data = [
        {
            "id": str(key.id),
            "name": key.name,
            "business_owner_id": str(key.business_owner_id),
            "business_name": key_business_names.get(str(key.business_owner_id)),
            "prefix": key.key_prefix,
            "environment": key.environment,
            "scopes": key.scopes,
            "status": effective_key_status(key, now),
            "created_at": key.created_at,
            "expires_at": key.expires_at,
            "last_used_at": key.last_used_at,
        }
        for key in keys
    ]

    # Determine onboarding milestones from stored backend records,
    # without limiting the search to recent dashboard activity.
    onboarding = {
        "test_key_created": key_records.filter(
            environment="test",
        ).exists(),

        "first_quote_requested": request_records.filter(
            method="POST",
            path__in=["/v1/quotes", "/v1/quotes/"],
            status__gte=200,
            status__lt=400,
        ).exists(),

        "webhook_registered": request_records.filter(
            method="POST",
            path__in=["/v1/webhooks", "/v1/webhooks/"],
            status__gte=200,
            status__lt=400,
        ).exists(),

        "live_key_created": key_records.filter(
            environment="live",
        ).exists(),
    }


    response = JsonResponse({
        "generated_at": now,
        "record_limit": 100,
        "analytics": analytics,
        "onboarding": onboarding,
        "business_owner_id": business_id or None,
        "api_key_id": api_key_id or None,
        "summary": summary,
        "request_trends": {
            "days": days,
            "timezone": "UTC",
            "requests": period_requests,
            "failed": period_failed,
            "daily": trend,
        },
        "keys": key_data,
        "requests": requests,
        "security_events": events,
        "csrf_token": get_token(request),
    })

    response["Cache-Control"] = "no-store"
    return response


@never_cache
@require_POST
@csrf_protect
def admin_revoke_key(request, business_owner_id, api_key_id):
    """Revoke an API key belonging to an authorized business."""

    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    identity = get_dashboard_identity(request.user)

    if identity is None:
        return JsonResponse(
            {"error": "Dashboard access denied."},
            status=403,
        )

    # Administrators can revoke keys for any business.
    # Business users can revoke only their assigned business's keys.
    if (
        identity["role"] == "business"
        and identity["business_owner_id"] != business_owner_id
    ):
        return JsonResponse(
            {"error": "Access to this business is denied."},
            status=403,
        )

    if request.content_type != "application/json":
        return JsonResponse(
            {"error": "Content-Type must be application/json."},
            status=415,
        )

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "Request body must contain valid JSON."},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"error": "Request body must be a JSON object."},
            status=400,
        )

    if set(payload) - {"reason"}:
        return JsonResponse(
            {"error": "Only the reason field is accepted."},
            status=400,
        )

    reason = payload.get("reason", "")

    if not isinstance(reason, str) or len(reason) > 500:
        return JsonResponse(
            {"error": "reason must be a string of at most 500 characters."},
            status=400,
        )

    # Confirm the key belongs to the authorized business.
    if not ApiKey.objects.filter(
        pk=api_key_id,
        business_owner_id=business_owner_id,
    ).exists():
        return JsonResponse(
            {"error": "API key not found."},
            status=404,
        )

    # Generate the audit identity for the authenticated dashboard user.
    actor_id = get_admin_audit_identity(request.user)

    try:
        key = revoke_api_key(
            api_key_id=api_key_id,
            business_owner_id=business_owner_id,
            revoked_by_id=actor_id,
            actor_email=request.user.email or "",
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
            reason=reason.strip(),
        )

    except KeyNotFoundError:
        return JsonResponse(
            {"error": "API key not found."},
            status=404,
        )

    except KeyAlreadyRevokedError:
        return JsonResponse(
            {"error": "API key is already revoked."},
            status=409,
        )
    # Notify the administrator only when they perform the revocation.
    if identity["role"] == "admin":
        notify_administrator(
            admin_user_id=request.user.pk,
            event_type="key.revoked",
            title="API key revoked",
            message=f'API key "{key.name}" has been revoked.',
            level="warning",
            target_id=key.id,
            environment=key.environment,
        )

    return JsonResponse({
        "id": str(key.id),
        "status": key.status,
        "revoked_at": key.revoked_at,
        "message": "API key revoked.",
    })


def business_rate_limit_data(access, window):
    effective_window = access.rate_limit_effective_window if access else None
    has_pending_limit = effective_window is not None and effective_window > window

    return {
        "rate_limit_requests_per_minute": (
            access.rate_limit_for_window(window) if access else None
        ),
        "pending_rate_limit_requests_per_minute": (
            access.pending_rate_limit_requests_per_minute
            if has_pending_limit else None
        ),
        "rate_limit_effective_at": (
            datetime.fromtimestamp(
                effective_window * WINDOW_SECONDS, tz=datetime_timezone.utc,
            ) if has_pending_limit else None
        ),
        "default_rate_limit_requests_per_minute": DEFAULT_RATE_LIMIT,
    }


@never_cache
@require_http_methods(["GET", "PATCH"])
@csrf_protect
def admin_business_api_access(request, business_owner_id):
    """Read or change business API access with an audit trail."""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Please sign in to Django admin."},
            status=401,
        )

    if not request.user.is_active or not request.user.is_superuser:
        return JsonResponse(
            {"error": "Administrator access is required."},
            status=403,
        )

    # Support registered accounts and older businesses represented by API keys.
    if not (
        BusinessAccount.objects.filter(pk=business_owner_id).exists()
        or ApiKey.objects.filter(business_owner_id=business_owner_id).exists()
        or ApiRequestLog.objects.filter(business_owner_id=business_owner_id).exists()
    ):
        return JsonResponse(
            {"error": "No API keys found for this business."},
            status=404,
        )

    if request.method == "GET":
        access = BusinessApiAccess.objects.filter(
            business_owner_id=business_owner_id,
        ).first()

        return JsonResponse({
            "business_owner_id": str(business_owner_id),
            "api_access_enabled": (
                access.api_access_enabled if access else True
            ),
            "updated_at": access.updated_at if access else None,
            "csrf_token": get_token(request),
            "daily_creation_quota": access.daily_creation_quota if access else None,
            "default_daily_creation_quota": DEFAULT_DAILY_CREATION_QUOTA,
            **business_rate_limit_data(access, int(time()) // WINDOW_SECONDS),
        })

    if request.content_type != "application/json":
        return JsonResponse(
            {"error": "Content-Type must be application/json."},
            status=415,
        )

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "Request body must contain valid JSON."},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"error": "Request body must be a JSON object."},
            status=400,
        )

    setting_fields = {
        "api_access_enabled", "rate_limit_requests_per_minute", "daily_creation_quota",
    }
    if set(payload) - (setting_fields | {"reason"}) or not setting_fields.intersection(payload):
        return JsonResponse(
            {"error": "Provide api_access_enabled, rate_limit_requests_per_minute, or daily_creation_quota."},
            status=400,
        )

    enabled = payload.get("api_access_enabled")
    if "api_access_enabled" in payload and type(enabled) is not bool:
        return JsonResponse(
            {"error": "api_access_enabled must be true or false."},
            status=400,
        )

    requested_quota = payload.get("daily_creation_quota")
    if requested_quota is not None and (
        type(requested_quota) is not int or not 1 <= requested_quota <= 2_147_483_647
    ):
        return JsonResponse(
            {"error": "The daily creation quota must be a positive integer up to 2147483647, or null."},
            status=400,
        )

    requested_limit = payload.get("rate_limit_requests_per_minute")
    if requested_limit is not None and (
        type(requested_limit) is not int or not 1 <= requested_limit <= 2_147_483_647
    ):
        return JsonResponse(
            {"error": "The rate limit must be a positive integer up to 2147483647, or null."},
            status=400,
        )

    reason = payload.get("reason", "")

    if not isinstance(reason, str) or len(reason) > 500:
        return JsonResponse(
            {"error": "reason must be a string of at most 500 characters."},
            status=400,
        )

    # Commit the settings and their audit events together.
    with transaction.atomic():
        access = BusinessApiAccess.objects.filter(
            business_owner_id=business_owner_id,
        ).first()

        window = int(time()) // WINDOW_SECONDS
        previous_enabled = access.api_access_enabled if access else True
        if enabled is None:
            enabled = previous_enabled
        access_changed = previous_enabled != enabled

        previous_limits = business_rate_limit_data(access, window)
        active_limit = previous_limits["rate_limit_requests_per_minute"]
        scheduled_limit = (
            previous_limits["pending_rate_limit_requests_per_minute"]
            if previous_limits["rate_limit_effective_at"] is not None
            else active_limit
        )
        limit_changed = (
            "rate_limit_requests_per_minute" in payload
            and requested_limit != scheduled_limit
        )
        previous_quota = access.daily_creation_quota if access else None
        quota_changed = (
            "daily_creation_quota" in payload and requested_quota != previous_quota
        )
        changed = access_changed or limit_changed or quota_changed

        if changed:
            actor_id = get_admin_audit_identity(request.user)
            if access is None:
                access = BusinessApiAccess(business_owner_id=business_owner_id)

            access.api_access_enabled = enabled
            access.updated_by = actor_id
            if limit_changed:
                access.rate_limit_requests_per_minute = active_limit
                access.pending_rate_limit_requests_per_minute = requested_limit
                access.rate_limit_effective_window = (
                    window + 1 if requested_limit != active_limit else None
                )

            if quota_changed:
                access.daily_creation_quota = requested_quota

            access.save()

            audit_context = {
                "business_owner_id": business_owner_id,
                "actor_id": actor_id,
                "actor_email": request.user.email or "",
                "target_id": business_owner_id,
                "ip": request.META.get("REMOTE_ADDR"),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
            }
            if access_changed:
                log_audit(
                    action=(
                        "business.api_access_enabled"
                        if enabled else "business.api_access_disabled"
                    ),
                    **audit_context,
                    detail={
                        "previous_enabled": previous_enabled,
                        "api_access_enabled": enabled,
                        "reason": reason.strip(),
                    },
                )
                notify_business_access_changed(access)
                notify_administrator(
                    admin_user_id=request.user.pk,
                    event_type=(
                        "business.api_enabled"
                        if access.api_access_enabled
                        else "business.api_disabled"
                    ),
                    title=(
                        "Business API access restored"
                        if access.api_access_enabled
                        else "Business API access disabled"
                    ),
                    message=(
                        f"API access for business {access.business_owner_id} "
                        f"has been {'restored' if access.api_access_enabled else 'disabled'}."
                    ),
                    level="success" if access.api_access_enabled else "warning",
                    target_id=access.business_owner_id,
                )

            if limit_changed:
                log_audit(
                    action="business.api_rate_limit_updated",
                    **audit_context,
                    detail={
                        "previous_requests_per_minute": scheduled_limit,
                        "requests_per_minute": requested_limit,
                        "effective_window": access.rate_limit_effective_window,
                        "reason": reason.strip(),
                    },
                )

            if quota_changed:
                log_audit(
                    action="business.api_daily_creation_quota_updated",
                    **audit_context,
                    detail={
                        "previous_daily_creation_quota": previous_quota,
                        "daily_creation_quota": requested_quota,
                        "reason": reason.strip(),
                    },
                )

        if limit_changed or quota_changed:
            notify_business_limits_updated(access)
            notify_administrator(
                admin_user_id=request.user.pk,
                event_type="business.limits_updated",
                title="Business API limits updated",
                message=(
                    f"API usage limits for business "
                    f"{access.business_owner_id} have been updated."
                ),
                level="info",
                target_id=access.business_owner_id,
            )

        rate_limit_data = business_rate_limit_data(access, window)

    if "daily_creation_quota" in payload:
        message = (
            "Business daily creation quota updated."
            if quota_changed else "Business daily creation quota was already set to this value."
        )
    elif "rate_limit_requests_per_minute" in payload:
        message = (
            "Business rate limit updated."
            if limit_changed else "Business rate limit was already set to this value."
        )
    else:
        message = (
            "Business API access updated."
            if changed else "Business API access was already set to this value."
        )

    return JsonResponse({
        "business_owner_id": str(business_owner_id),
        "api_access_enabled": enabled,
        "changed": changed,
        "updated_at": access.updated_at if access else None,
        "message": message,
        "daily_creation_quota": access.daily_creation_quota if access else None,
        "default_daily_creation_quota": DEFAULT_DAILY_CREATION_QUOTA,
        **rate_limit_data,
    })

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

    # Disable the subscription only if it is currently active.
    if subscription.is_active:
        with transaction.atomic():
            subscription.is_active = False
            subscription.save(update_fields=["is_active", "updated_at"])

            notify_webhook_disabled(subscription)

    return JsonResponse(serialize_subscription(subscription), status=200)


@never_cache
@require_GET
def dashboard_businesses(request):
    """List active businesses for administrator selection."""

    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    identity = get_dashboard_identity(request.user)

    if identity is None or identity["role"] != "admin":
        return JsonResponse(
            {"error": "Administrator access required."},
            status=403,
        )

    businesses = BusinessAccount.objects.order_by("name", "email")
    if request.GET.get("include_inactive") != "1":
        businesses = businesses.filter(is_active=True)

    from django.db.models import Count, Max, Q

    now = timezone.now()
    window_start = now - timedelta(hours=24)
    businesses = list(businesses)
    business_ids = [business.pk for business in businesses]
    linked_ids = {str(business_id) for business_id in business_ids}
    legacy_ids = []

    if request.GET.get("include_inactive") == "1":
        from uuid import UUID

        recorded_ids = set()
        for model in (ApiKey, ApiRequestLog):
            owners = model.objects.order_by().values_list(
                "business_owner_id", flat=True
            ).distinct()
            for owner in owners:
                try:
                    recorded_ids.add(str(UUID(str(owner))))
                except (TypeError, ValueError):
                    continue

        legacy_ids = [UUID(owner) for owner in sorted(recorded_ids - linked_ids)]
        business_ids.extend(legacy_ids)

    active_keys = {
        (row["business_owner_id"], row["environment"]): row["total"]
        for row in ApiKey.objects.filter(
            business_owner_id__in=business_ids,
            status="active",
            environment__in=("live", "test"),
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by()
        .values("business_owner_id", "environment")
        .annotate(total=Count("pk"))
    }

    logs = ApiRequestLog.objects.filter(business_owner_id__in=business_ids)
    recent = logs.filter(created_at__gte=window_start, created_at__lte=now)

    def counts_by_business(queryset):
        return {
            row["business_owner_id"]: row["total"]
            for row in queryset.order_by()
            .values("business_owner_id")
            .annotate(total=Count("pk"))
        }

    request_counts = counts_by_business(recent)
    failure_counts = counts_by_business(recent.filter(status__gte=400))
    last_requests = {
        row["business_owner_id"]: row["last_request_at"]
        for row in logs.order_by()
        .values("business_owner_id")
        .annotate(last_request_at=Max("created_at"))
    }

    return JsonResponse({
        "businesses": [
            {
                "id": str(business.id),
                "name": business.name,
                "email": business.email,
                "is_active": business.is_active,
                "is_unlinked": False,
                "active_live_keys": active_keys.get((business.pk, "live"), 0),
                "active_test_keys": active_keys.get((business.pk, "test"), 0),
                "requests_24h": request_counts.get(business.pk, 0),
                "failed_requests_24h": failure_counts.get(business.pk, 0),
                "last_request_at": last_requests.get(business.pk),
            }
            for business in businesses
        ] + [
            {
                "id": str(owner_id),
                "name": "Unlinked business",
                "email": "",
                "is_unlinked": True,
                "active_live_keys": active_keys.get((owner_id, "live"), 0),
                "active_test_keys": active_keys.get((owner_id, "test"), 0),
                "requests_24h": request_counts.get(owner_id, 0),
                "failed_requests_24h": failure_counts.get(owner_id, 0),
                "last_request_at": last_requests.get(owner_id),
            }
            for owner_id in legacy_ids
        ]
    })


@never_cache
@require_POST
@csrf_protect
def admin_create_key(request):
    """Create an API key through the developer dashboard."""
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    identity = get_dashboard_identity(request.user)

    if identity is None:
        return JsonResponse(
            {"error": "Dashboard access denied."},
            status=403,
        )

    if request.content_type != "application/json":
        return JsonResponse(
            {"error": "Content-Type must be application/json."},
            status=415,
        )

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "Request body must contain valid JSON."},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"error": "Request body must be a JSON object."},
            status=400,
        )

    name = payload.get("name")
    environment = payload.get("environment")
    scopes = payload.get("scopes")
    expiry_days = payload.get("expiryDays")
    business_owner_id = payload.get("businessOwnerId")

    # Validate the key name.
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        return JsonResponse(
            {"error": "Key name must contain 1–100 characters."},
            status=400,
        )

    # Validate the environment.
    if environment not in ("test", "live"):
        return JsonResponse(
            {"error": "Environment must be test or live."},
            status=400,
        )

    # Validate the requested permissions.
    if (
        not isinstance(scopes, list)
        or not scopes
        or not all(isinstance(scope, str) for scope in scopes)
        or len(set(scopes)) != len(scopes)
    ):
        return JsonResponse(
            {"error": "At least one valid, unique scope is required."},
            status=400,
        )

    # Validate the expiration period.
    if type(expiry_days) is not int and expiry_days is not None:
        return JsonResponse(
            {"error": "Invalid expiration period."},
            status=400,
        )

    if expiry_days not in (None, 30, 90, 365):
        return JsonResponse(
            {"error": "Expiration must be 30, 90, 365 days, or never."},
            status=400,
        )


    # Administrators select a registered business.
    # Business users always operate on their assigned business.
    if identity["role"] == "admin":
        try:
            business_owner_id = uuid.UUID(str(business_owner_id))
        except (ValueError, TypeError, AttributeError):
            return JsonResponse(
                {"error": "Invalid business owner ID."},
                status=400,
            )

        if not BusinessAccount.objects.filter(
            id=business_owner_id,
            is_active=True,
        ).exists():
            return JsonResponse(
                {"error": "Business not found or inactive."},
                status=404,
            )
    else:
        business_owner_id = identity["business_owner_id"]

        # Reject attempts to select another business.
        submitted_id = payload.get("businessOwnerId")

        if submitted_id not in (None, ""):
            try:
                submitted_uuid = uuid.UUID(str(submitted_id))
            except (ValueError, TypeError, AttributeError):
                return JsonResponse(
                    {"error": "Invalid business owner ID."},
                    status=400,
                )

            if submitted_uuid != business_owner_id:
                return JsonResponse(
                    {"error": "Access to this business is denied."},
                    status=403,
                )

    # Generate a stable UUID for the Django administrator.
    # Django uses a MongoDB ObjectId, while the API key model
    # requires created_by_id to be a UUID.
    creator_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"aerrand:django-admin:{request.user.pk}",
    )

    # Generate the API key and return validation errors to the client.
    try:
        key, secret = create_api_key(
            business_owner_id=business_owner_id,
            created_by_id=creator_id,
            name=name.strip(),
            environment=environment,
            scopes=scopes,
            expires_in_days=expiry_days,
            actor_email=request.user.email or "",
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
    except KeyGenerationError as error:
        return JsonResponse(
            {"error": str(error)},
            status=400,
        )

    # Notify the administrator only when they create a key.
    if identity["role"] == "admin":
        notify_administrator(
            admin_user_id=request.user.pk,
            event_type="key.created",
            title="API key created",
            message=f'API key "{key.name}" has been created.',
            level="success",
            target_id=key.id,
            environment=key.environment,
        )

    # Return the plaintext secret only when the key is created.
    response = JsonResponse(
        {
            "id": str(key.id),
            "name": key.name,
            "prefix": key.key_prefix,
            "environment": key.environment,
            "scopes": key.scopes,
            "status": key.status,
            "business_owner_id": str(key.business_owner_id),
            "created_at": key.created_at,
            "expires_at": key.expires_at,
            "secret": secret,
        },
        status=201,
    )

    response["Cache-Control"] = "no-store"

    return response


@never_cache
def admin_list_business_keys(request, business_owner_id):
    """Return safe API key metadata for one business."""
    if request.method != "GET":
        return JsonResponse(
            {"error": "Method not allowed."},
            status=405,
            headers={"Allow": "GET"},
        )

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)

    if not request.user.is_active or not request.user.is_superuser:
        return JsonResponse({"error": "Administrator access required."}, status=403)

    now = timezone.now()
    keys = ApiKey.objects.filter(
        business_owner_id=business_owner_id,
    ).order_by("-created_at", "-id")

    return JsonResponse({
        "business_owner_id": str(business_owner_id),
        "keys": [
            {
                "id": str(key.id),
                "name": key.name,
                "prefix": key.key_prefix,
                "environment": key.environment,
                "created_at": key.created_at,
                "last_used_at": key.last_used_at,
                "status": effective_key_status(key, now),
            }
            for key in keys
        ],
    })
