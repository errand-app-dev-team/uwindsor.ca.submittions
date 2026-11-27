
import uuid
from datetime import timedelta

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from django.utils import timezone

from developer.models import WebhookDelivery, WebhookSubscription
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
)
from developer.services.webhook_sender_service import (
    claim_webhook_delivery,
    complete_webhook_delivery,
)


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class WebhookDeliveryTests(TestCase):

    def setUp(self):
        result = create_webhook_subscription(
            business_owner_id=uuid.uuid4(),
            environment="test",
            endpoint_url="https://example.com/webhook",
            subscribed_events=["delivery.created"],
        )

        self.subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        self.delivery = WebhookDelivery.objects.create(
            subscription=self.subscription,
            event_id=f"evt_{uuid.uuid4().hex}",
            event_type="delivery.created",
            payload={"type": "delivery.created"},
            status="pending",
        )

    def test_claim_pending_delivery(self):
        token = claim_webhook_delivery(self.delivery.id)

        self.delivery.refresh_from_db()

        self.assertIsNotNone(token)
        self.assertEqual(self.delivery.status, "processing")
        self.assertEqual(self.delivery.claim_token, token)
        self.assertGreater(
            self.delivery.claim_expires_at,
            timezone.now(),
        )

    def test_prevent_duplicate_claim(self):
        first_token = claim_webhook_delivery(self.delivery.id)
        second_token = claim_webhook_delivery(self.delivery.id)

        self.assertIsNotNone(first_token)
        self.assertIsNone(second_token)

    def test_recover_expired_claim(self):
        old_token = uuid.uuid4()

        self.delivery.status = "processing"
        self.delivery.claim_token = old_token
        self.delivery.claim_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )
        self.delivery.save()

        new_token = claim_webhook_delivery(self.delivery.id)

        self.delivery.refresh_from_db()

        self.assertIsNotNone(new_token)
        self.assertNotEqual(new_token, old_token)
        self.assertEqual(self.delivery.claim_token, new_token)

    def test_reject_unexpired_processing_claim(self):
        self.delivery.status = "processing"
        self.delivery.claim_token = uuid.uuid4()
        self.delivery.claim_expires_at = (
            timezone.now() + timedelta(minutes=1)
        )
        self.delivery.save()

        token = claim_webhook_delivery(self.delivery.id)

        self.assertIsNone(token)

    def test_complete_claimed_delivery(self):
        token = claim_webhook_delivery(self.delivery.id)

        completed = complete_webhook_delivery(
            self.delivery.id,
            token,
            status="delivered",
            response_status_code=200,
            delivered_at=timezone.now(),
        )

        self.delivery.refresh_from_db()

        self.assertTrue(completed)
        self.assertEqual(self.delivery.status, "delivered")
        self.assertEqual(self.delivery.response_status_code, 200)
        self.assertIsNone(self.delivery.claim_token)
        self.assertIsNone(self.delivery.claim_expires_at)

    def test_reject_wrong_claim_token(self):
        claim_webhook_delivery(self.delivery.id)

        completed = complete_webhook_delivery(
            self.delivery.id,
            uuid.uuid4(),
            status="delivered",
        )

        self.delivery.refresh_from_db()

        self.assertFalse(completed)
        self.assertEqual(self.delivery.status, "processing")

    def test_reject_expired_claim_completion(self):
        token = claim_webhook_delivery(self.delivery.id)

        self.delivery.claim_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.delivery.save(update_fields=["claim_expires_at"])

        completed = complete_webhook_delivery(
            self.delivery.id,
            token,
            status="delivered",
        )

        self.assertFalse(completed)

    def test_reject_invalid_completion_status(self):
        token = claim_webhook_delivery(self.delivery.id)

        with self.assertRaises(ValueError):
            complete_webhook_delivery(
                self.delivery.id,
                token,
                status="pending",
            )

    def test_reject_invalid_update_fields(self):
        token = claim_webhook_delivery(self.delivery.id)

        with self.assertRaises(ValueError):
            complete_webhook_delivery(
                self.delivery.id,
                token,
                status="delivered",
                invalid_field="test",
            )

        self.delivery.refresh_from_db()

        self.assertEqual(self.delivery.status, "processing")
        self.assertEqual(self.delivery.claim_token, token)

    def test_delivered_webhook_cannot_be_claimed_again(self):
        self.delivery.status = "delivered"
        self.delivery.save(update_fields=["status"])

        token = claim_webhook_delivery(self.delivery.id)

        self.assertIsNone(token)

    def test_retry_not_due_cannot_be_claimed(self):
        self.delivery.status = "retrying"
        self.delivery.next_retry_at = (
            timezone.now() + timedelta(minutes=5)
        )
        self.delivery.save()

        token = claim_webhook_delivery(self.delivery.id)

        self.assertIsNone(token)

    def test_due_retry_can_be_claimed(self):
        self.delivery.status = "retrying"
        self.delivery.next_retry_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.delivery.save()

        token = claim_webhook_delivery(self.delivery.id)

        self.assertIsNotNone(token)
