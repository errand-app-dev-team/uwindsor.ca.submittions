"""Dashboard endpoints for managing persistent notifications."""

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from developer.models import Notification
from developer.services.dashboard_auth import get_dashboard_identity


def notification_context(request):
    """Resolve notification ownership from the authenticated dashboard user."""

    if not request.user.is_authenticated:
        return None, JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    identity = get_dashboard_identity(request.user)

    if identity is None:
        return None, JsonResponse(
            {"error": "Dashboard access denied."},
            status=403,
        )

    # Administrators can only access their own notifications.
    if identity["role"] == "admin":
        return {
            "admin_user_id": str(request.user.pk),
            "business_owner_id__isnull": True,
        }, None

    # Business users can only access their assigned business notifications.
    if identity["role"] == "business":
        business_owner_id = identity.get("business_owner_id")

        if business_owner_id is not None:
            return {
                "business_owner_id": business_owner_id,
                "admin_user_id__isnull": True,
            }, None

    return None, JsonResponse(
        {"error": "Dashboard access denied."},
        status=403,
    )


def serialize_notification(notification):
    """Convert a notification into dashboard response data."""

    return {
        "id": str(notification.id),
        "event_type": notification.event_type,
        "title": notification.title,
        "message": notification.message,
        "level": notification.level,
        "target_id": (
            str(notification.target_id)
            if notification.target_id else None
        ),
        "environment": notification.environment,
        "is_read": notification.is_read,
        "read_at": notification.read_at,
        "created_at": notification.created_at,
    }


@never_cache
@require_GET
def dashboard_notifications(request):
    """Return recent notifications and the total unread count."""

    recipient, error = notification_context(request)

    if error is not None:
        return error

    notifications = Notification.objects.filter(**recipient)

    unread_count = notifications.filter(is_read=False).count()

    recent_notifications = notifications.order_by(
        "-created_at", "-id"
    )[:100]

    return JsonResponse({
        "notifications": [
            serialize_notification(notification)
            for notification in recent_notifications
        ],
        "unread_count": unread_count,
        "csrf_token": get_token(request),
    })


@never_cache
@require_POST
@csrf_protect
def mark_notification_read(request, notification_id):
    """Mark a notification belonging to the current recipient as read."""

    recipient, error = notification_context(request)

    if error is not None:
        return error

    notifications = Notification.objects.filter(
        id=notification_id,
        **recipient,
    )

    if not notifications.exists():
        return JsonResponse(
            {"error": "Notification not found."},
            status=404,
        )

    # Preserve the original read timestamp on repeated requests.
    notifications.filter(is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )

    return JsonResponse({
        "message": "Notification marked as read.",
        "id": str(notification_id),
    })


@never_cache
@require_POST
@csrf_protect
def mark_all_notifications_read(request):
    """Mark all unread notifications for the current recipient as read."""

    recipient, error = notification_context(request)

    if error is not None:
        return error

    updated_count = Notification.objects.filter(
        is_read=False,
        **recipient,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )

    return JsonResponse({
        "message": "All notifications marked as read.",
        "updated_count": updated_count,
    })