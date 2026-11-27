
"""Queue webhook events for active partner subscriptions."""

from django.db import IntegrityError

from developer.models import WebhookDelivery, WebhookSubscription
from developer.services.webhook_service import generate_webhook_event


def queue_webhook_event(event_type, business_owner_id, environment, data):
    """Create delivery records for subscriptions interested in an event."""

    if environment not in ("test", "live"):
        raise ValueError("Invalid webhook environment.")

    event = generate_webhook_event(
        event_type=event_type,
        business_owner_id=business_owner_id,
        data=data,
    )

    subscriptions = WebhookSubscription.objects.filter(
        business_owner_id=business_owner_id,
        environment=environment,
        is_active=True,
    )

    queued_deliveries = []

    for subscription in subscriptions:
        if event_type not in subscription.subscribed_events:
            continue

        try:
            delivery = WebhookDelivery.objects.create(
                subscription=subscription,
                event_id=event["id"],
                event_type=event_type,
                payload=event,
                status="pending",
            )
        except IntegrityError:
            # Avoid duplicate delivery records for the same event.
            continue

        queued_deliveries.append(str(delivery.id))

    return {
        "event_id": event["id"],
        "event_type": event_type,
        "queued_count": len(queued_deliveries),
        "delivery_ids": queued_deliveries,
    }
