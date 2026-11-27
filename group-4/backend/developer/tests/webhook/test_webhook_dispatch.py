
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.db import IntegrityError
from django.test import TestCase, override_settings

from developer.models import WebhookDelivery, WebhookSubscription
from developer.services.webhook_dispatch_service import (
    queue_webhook_event,
)
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
)


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class WebhookDispatchTests(TestCase):

    def setUp(self):
        self.business_owner_id = str(uuid.uuid4())
        self.event_type = "delivery.created"
        self.environment = "test"
        self.data = {
            "delivery_id": "delivery_001",
            "status": "created",
        }

    def create_subscription(
        self,
        business_owner_id=None,
        environment="test",
        subscribed_events=None,
        is_active=True,
    ):
        if business_owner_id is None:
            business_owner_id = self.business_owner_id

        if subscribed_events is None:
            subscribed_events = ["delivery.created"]

        result = create_webhook_subscription(
            business_owner_id=business_owner_id,
            environment=environment,
            endpoint_url="https://example.com/webhook",
            subscribed_events=subscribed_events,
        )

        subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        if not is_active:
            subscription.is_active = False
            subscription.save(update_fields=["is_active"])

        return subscription

    def queue_event(self, environment="test"):
        return queue_webhook_event(
            event_type=self.event_type,
            business_owner_id=self.business_owner_id,
            environment=environment,
            data=self.data,
        )

    def test_queue_event_for_active_subscription(self):
        self.create_subscription()

        result = self.queue_event()

        self.assertEqual(result["queued_count"], 1)
        self.assertEqual(WebhookDelivery.objects.count(), 1)

        delivery = WebhookDelivery.objects.first()

        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.event_type, self.event_type)

    def test_skip_inactive_subscription(self):
        self.create_subscription(is_active=False)

        result = self.queue_event()

        self.assertEqual(result["queued_count"], 0)
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_skip_unsubscribed_event(self):
        self.create_subscription(
            subscribed_events=["delivery.cancelled"]
        )

        result = self.queue_event()

        self.assertEqual(result["queued_count"], 0)
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_environment_isolation(self):
        self.create_subscription(environment="test")
        self.create_subscription(environment="live")

        result = self.queue_event(environment="test")

        self.assertEqual(result["queued_count"], 1)

        delivery = WebhookDelivery.objects.first()

        self.assertEqual(
            delivery.subscription.environment,
            "test",
        )

    def test_multiple_matching_subscriptions(self):
        self.create_subscription()
        self.create_subscription()

        result = self.queue_event()

        self.assertEqual(result["queued_count"], 2)
        self.assertEqual(WebhookDelivery.objects.count(), 2)

    def test_return_correct_delivery_details(self):
        self.create_subscription()

        result = self.queue_event()

        delivery = WebhookDelivery.objects.first()

        self.assertEqual(
            result["event_id"],
            delivery.event_id,
        )
        self.assertEqual(
            result["event_type"],
            self.event_type,
        )
        self.assertEqual(result["queued_count"], 1)
        self.assertEqual(
            result["delivery_ids"],
            [str(delivery.id)],
        )

    def test_reject_invalid_environment(self):
        self.create_subscription()

        with self.assertRaises(ValueError):
            self.queue_event(environment="development")

        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_delivery_contains_correct_payload(self):
        self.create_subscription()

        self.queue_event()

        delivery = WebhookDelivery.objects.first()

        self.assertEqual(
            delivery.payload["type"],
            self.event_type,
        )
        self.assertEqual(
            delivery.payload["business_owner_id"],
            self.business_owner_id,
        )
        self.assertEqual(
            delivery.payload["data"],
            self.data,
        )
        self.assertEqual(
            delivery.payload["id"],
            delivery.event_id,
        )

    def test_handle_integrity_error(self):
        self.create_subscription()

        with patch(
            "developer.services.webhook_dispatch_service."
            "WebhookDelivery.objects.create",
            side_effect=IntegrityError("Duplicate delivery"),
        ):
            result = self.queue_event()

        self.assertEqual(result["queued_count"], 0)
        self.assertEqual(result["delivery_ids"], [])
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_business_owner_isolation(self):
        self.create_subscription()

        other_owner_id = str(uuid.uuid4())

        self.create_subscription(
            business_owner_id=other_owner_id,
        )

        result = self.queue_event()

        self.assertEqual(result["queued_count"], 1)

        delivery = WebhookDelivery.objects.first()

        self.assertEqual(
            str(delivery.subscription.business_owner_id),
            self.business_owner_id,
        )
