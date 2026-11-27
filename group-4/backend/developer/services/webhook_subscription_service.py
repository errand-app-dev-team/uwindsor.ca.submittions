
"""Service functions for managing partner webhook subscriptions."""

import secrets

from cryptography.fernet import Fernet
from django.conf import settings

from developer.models import WebhookSubscription
from developer.services.notifications import notify_webhook_created
from developer.services.webhook_service import validate_webhook_subscription


def get_encryption_cipher():
    """Initialize Fernet using the configured encryption key."""
    return Fernet(settings.WEBHOOK_ENCRYPTION_KEY.encode("utf-8"))


def create_webhook_subscription(
    business_owner_id,
    environment,
    endpoint_url,
    subscribed_events,
):
    """Create a webhook subscription with an encrypted signing secret."""

    if environment not in ("test", "live"):
        raise ValueError("Invalid webhook environment.")

    # Validate the endpoint and supported event types.
    validated = validate_webhook_subscription(
        endpoint_url=endpoint_url,
        subscribed_events=subscribed_events,
    )

    # Generate a separate signing secret for each subscription.
    signing_secret = secrets.token_urlsafe(32)

    # Encrypt the secret before saving it to the database.
    encrypted_secret = get_encryption_cipher().encrypt(
        signing_secret.encode("utf-8")
    ).decode("utf-8")

    subscription = WebhookSubscription.objects.create(
        business_owner_id=business_owner_id,
        environment=environment,
        endpoint_url=validated["endpoint_url"],
        subscribed_events=validated["subscribed_events"],
        signing_secret_encrypted=encrypted_secret,
        is_active=True,
    )

    notify_webhook_created(subscription)

    # Return the plaintext secret only at creation time.
    return {
        "id": str(subscription.id),
        "endpoint_url": subscription.endpoint_url,
        "environment": subscription.environment,
        "subscribed_events": subscription.subscribed_events,
        "is_active": subscription.is_active,
        "signing_secret": signing_secret,
    }


def get_webhook_signing_secret(subscription):
    """Decrypt a subscription's signing secret for webhook delivery."""
    return get_encryption_cipher().decrypt(
        subscription.signing_secret_encrypted.encode("utf-8")
    ).decode("utf-8")
