
"""Process queued webhook deliveries."""
import uuid
from datetime import timedelta

from django.utils import timezone
import hashlib
import hmac
import json
from unittest.mock import Mock

from developer.services.webhook_subscription_service import get_webhook_signing_secret

from developer.models import WebhookDelivery
from django.db.models import Q


def process_webhook_delivery(delivery_id, http_post=None):
    """Process a webhook using atomic claiming and ownership checks."""

    delivery = WebhookDelivery.objects.select_related(
        "subscription"
    ).get(id=delivery_id)

    if delivery.status not in ("pending", "retrying", "processing"):
        return {
            "delivery_id": str(delivery.id),
            "status": delivery.status,
            "message": "Delivery is not eligible for processing.",
        }


    if not delivery.subscription.is_active:
        now = timezone.now()

        # Fail unclaimed deliveries and expired claims for disabled subscriptions.
        WebhookDelivery.objects.filter(
            id=delivery.id,
        ).filter(
            Q(status__in=["pending", "retrying"])
            | (
                Q(status="processing")
                & (
                    Q(claim_expires_at__lte=now)
                    | Q(claim_expires_at__isnull=True)
                )
            )
        ).update(
            status="failed",
            last_error="Webhook subscription is disabled.",
            next_retry_at=None,
            claim_token=None,
            claim_expires_at=None,
            updated_at=now,
        )

        return {
            "delivery_id": str(delivery.id),
            "status": "skipped",
            "message": "Webhook subscription is disabled.",
        }

    if http_post is None:
        raise ValueError(
            "An HTTP client must be provided. Real HTTP sending is not enabled."
        )

    if delivery.status == "retrying":
        if delivery.next_retry_at and delivery.next_retry_at > timezone.now():
            return {
                "delivery_id": str(delivery.id),
                "status": "retrying",
                "message": "Retry is not due yet.",
            }

    # Atomically claim this delivery or recover an expired claim.
    token = claim_webhook_delivery(delivery.id)

    if token is None:
        return {
            "delivery_id": str(delivery.id),
            "status": "skipped",
            "message": "Delivery is already claimed or not eligible.",
        }

    delivery.refresh_from_db()
    max_attempts = 5

    # Stop exhausted deliveries before making another HTTP request.
    if delivery.attempt_count >= max_attempts:
        completed = complete_webhook_delivery(
            delivery.id,
            token,
            status="failed",
            next_retry_at=None,
            last_error="Maximum webhook delivery attempts reached.",
        )

        return {
            "delivery_id": str(delivery.id),
            "status": "failed" if completed else "skipped",
            "message": (
                "Maximum webhook delivery attempts reached."
                if completed
                else "Claim expired or ownership changed."
            ),
        }

    # Count the attempt only while this worker owns the claim.
    updated = WebhookDelivery.objects.filter(
        id=delivery.id,
        status="processing",
        claim_token=token,
        claim_expires_at__gt=timezone.now(),
    ).update(
        attempt_count=delivery.attempt_count + 1,
        updated_at=timezone.now(),
    )

    if updated != 1:
        return {
            "delivery_id": str(delivery.id),
            "status": "skipped",
            "message": "Claim ownership was lost.",
        }

    delivery.refresh_from_db()

    response_status = None
    last_error = ""
    delivered_at = None
    next_retry_at = None

    try:
        # This uses only the injected HTTP client during testing.
        response = send_signed_webhook(delivery, http_post)
        response_status = response.status_code

        if 200 <= response_status < 300:
            status = "delivered"
            delivered_at = timezone.now()

        elif response_status in (408, 429) or response_status >= 500:
            last_error = f"HTTP {response_status}"
            status = "retrying"

        else:
            status = "failed"
            last_error = f"HTTP {response_status}"

    except Exception as exc:
        status = "retrying"
        last_error = f"{type(exc).__name__}: {exc}"

    if status == "retrying":
        if delivery.attempt_count >= max_attempts:
            status = "failed"
        else:
            delay = min(
                60 * (2 ** (delivery.attempt_count - 1)),
                3600,
            )
            next_retry_at = timezone.now() + timedelta(seconds=delay)

    # Only the current claim owner may save the final result.
    completed = complete_webhook_delivery(
        delivery.id,
        token,
        status=status,
        response_status_code=response_status,
        last_error=last_error,
        next_retry_at=next_retry_at,
        delivered_at=delivered_at,
    )

    if not completed:
        return {
            "delivery_id": str(delivery.id),
            "status": "skipped",
            "message": "Claim expired or ownership changed.",
        }

    return {
        "delivery_id": str(delivery.id),
        "status": status,
        "attempt_count": delivery.attempt_count,
        "response_status_code": response_status,
        "next_retry_at": (
            next_retry_at.isoformat() if next_retry_at else None
        ),
        "last_error": last_error,
    }



def send_signed_webhook(delivery, http_post):
    """Prepare and send a signed webhook using an injected HTTP client."""

    subscription = delivery.subscription

    if not subscription.is_active:
        raise ValueError("Webhook subscription is disabled.")

    if delivery.status != "processing":
        raise ValueError("Webhook delivery must be claimed before sending.")

    # Use consistent JSON bytes for both signing and sending.
    payload_bytes = json.dumps(
        delivery.payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    signing_secret = get_webhook_signing_secret(subscription)

    signature = hmac.new(
        signing_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Aerrand-Event-ID": delivery.event_id,
        "X-Aerrand-Signature": f"sha256={signature}",
    }

    return http_post(
        subscription.endpoint_url,
        data=payload_bytes,
        headers=headers,
        timeout=5,
        allow_redirects=False,
    )



def claim_webhook_delivery(delivery_id):
    """Atomically claim an eligible or abandoned webhook delivery."""

    now = timezone.now()
    token = uuid.uuid4()
    expires_at = now + timedelta(minutes=2)

    # Claim a pending/retrying delivery or recover an expired claim.
    updated = WebhookDelivery.objects.filter(
        id=delivery_id
    ).filter(
        (
            Q(status__in=["pending", "retrying"]) &
            (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        ) |
        (
            Q(status="processing") &
            Q(claim_expires_at__lte=now)
        )
    ).update(
        status="processing",
        claim_token=token,
        claim_expires_at=expires_at,
        updated_at=now,
    )

    return token if updated == 1 else None


def complete_webhook_delivery(delivery_id, claim_token, **updates):
    """Update a delivery only if the worker still owns its claim."""

    now = timezone.now()

    allowed_fields = {
        "status",
        "attempt_count",
        "response_status_code",
        "last_error",
        "next_retry_at",
        "delivered_at",
    }

    if not updates or not set(updates).issubset(allowed_fields):
        raise ValueError("Invalid webhook delivery update fields.")

    if updates.get("status") not in ("delivered", "retrying", "failed"):
        raise ValueError("Invalid completion status.")

    # Reject updates from workers whose claim has expired or changed.
    updated = WebhookDelivery.objects.filter(
        id=delivery_id,
        status="processing",
        claim_token=claim_token,
        claim_expires_at__gt=now,
    ).update(
        **updates,
        claim_token=None,
        claim_expires_at=None,
        updated_at=now,
    )

    return updated == 1
