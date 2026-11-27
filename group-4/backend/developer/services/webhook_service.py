
"""Utilities for creating and signing Partner API webhook events."""

import hashlib
import hmac
import ipaddress
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


class WebhookServiceError(Exception):
    """Raised when a webhook event or signing request is invalid."""


def generate_webhook_event(
    event_type: str,
    business_owner_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Create a webhook event with a unique ID and UTC timestamp."""

    if not isinstance(event_type, str) or not event_type.strip():
        raise WebhookServiceError("event_type is required.")

    if not isinstance(business_owner_id, str) or not business_owner_id.strip():
        raise WebhookServiceError("business_owner_id is required.")

    if not isinstance(data, dict):
        raise WebhookServiceError("Webhook event data must be an object.")

    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_owner_id": business_owner_id,
        "data": data,
    }


def serialize_webhook_event(event: dict[str, Any]) -> str:
    """Serialize an event consistently before signing and delivery."""

    try:
        return json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    except (TypeError, ValueError) as error:
        raise WebhookServiceError(
            "Webhook event contains invalid JSON data."
        ) from error


def generate_webhook_signature(
    payload: str,
    secret: str,
    timestamp: int | None = None,
) -> tuple[str, int]:
    """Sign a webhook payload using HMAC-SHA256."""

    if not isinstance(payload, str):
        raise WebhookServiceError("Webhook payload must be a string.")

    if not isinstance(secret, str) or not secret:
        raise WebhookServiceError("Webhook signing secret is required.")

    if timestamp is None:
        timestamp = int(time.time())

    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        raise WebhookServiceError("Webhook timestamp must be an integer.")

    # Include the timestamp to protect against replayed webhook requests.
    signed_content = f"{timestamp}.{payload}".encode("utf-8")

    signature = hmac.new(
        secret.encode("utf-8"),
        signed_content,
        hashlib.sha256,
    ).hexdigest()

    return signature, timestamp


def build_webhook_headers(
    payload: str,
    secret: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Build the HTTP headers required for a signed webhook request."""

    signature, timestamp = generate_webhook_signature(
        payload=payload,
        secret=secret,
        timestamp=timestamp,
    )

    return {
        "Content-Type": "application/json",
        "X-Aerrand-Event": "webhook",
        "X-Aerrand-Timestamp": str(timestamp),
        "X-Aerrand-Signature": f"sha256={signature}",
    }


def verify_webhook_signature(
    payload: str,
    secret: str,
    timestamp: int,
    signature: str,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify a received webhook signature and its timestamp."""

    if (
        not isinstance(timestamp, int)
        or isinstance(timestamp, bool)
        or not isinstance(signature, str)
        or tolerance_seconds < 0
    ):
        return False

    # Reject stale and future-dated requests outside the allowed time window.
    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        return False

    expected_signature, _ = generate_webhook_signature(
        payload=payload,
        secret=secret,
        timestamp=timestamp,
    )

    return hmac.compare_digest(
        expected_signature,
        signature,
    )

SUPPORTED_WEBHOOK_EVENTS = {
    "delivery.created",
    "delivery.assigned",
    "delivery.picked_up",
    "delivery.in_transit",
    "delivery.completed",
    "delivery.cancelled",
    "delivery.failed",
}


def validate_webhook_subscription(endpoint_url, subscribed_events):
    """Validate a partner's webhook endpoint and event subscriptions."""

    if not isinstance(endpoint_url, str) or not endpoint_url.strip():
        raise WebhookServiceError("Webhook endpoint URL is required.")

    if len(endpoint_url) > 2048:
        raise WebhookServiceError("Webhook endpoint URL is too long.")

    try:
        parsed = urlsplit(endpoint_url)
        port = parsed.port
    except ValueError as error:
        raise WebhookServiceError("Invalid webhook endpoint URL.") from error

    # Production webhook endpoints must use HTTPS.
    if parsed.scheme != "https" or not parsed.hostname:
        raise WebhookServiceError("Webhook endpoint must use HTTPS.")

    if parsed.username or parsed.password or parsed.fragment:
        raise WebhookServiceError(
            "Webhook URL must not contain credentials or fragments."
        )

    if port not in (None, 443):
        raise WebhookServiceError(
            "Webhook endpoint must use the standard HTTPS port."
        )

    hostname = parsed.hostname

    # Reject direct IP addresses to reduce access to internal infrastructure.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise WebhookServiceError(
            "Webhook endpoint must use a public domain name."
        )

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise WebhookServiceError(
            "Localhost webhook endpoints are not allowed."
        )

    if not isinstance(subscribed_events, list) or not subscribed_events:
        raise WebhookServiceError(
            "At least one webhook event must be selected."
        )

    if (
        any(not isinstance(event, str) for event in subscribed_events)
        or len(set(subscribed_events)) != len(subscribed_events)
    ):
        raise WebhookServiceError(
            "Webhook events must be unique strings."
        )

    unsupported = set(subscribed_events) - SUPPORTED_WEBHOOK_EVENTS

    if unsupported:
        raise WebhookServiceError(
            "Unsupported webhook events: " + ", ".join(sorted(unsupported))
        )

    return {
        "endpoint_url": endpoint_url,
        "subscribed_events": subscribed_events,
    }