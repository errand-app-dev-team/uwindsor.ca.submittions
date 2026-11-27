
import uuid
from datetime import timedelta
from unittest.mock import Mock

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from django.utils import timezone

from developer.models import WebhookDelivery, WebhookSubscription
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
)
from developer.services.webhook_sender_service import (
    process_webhook_delivery,
)


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class WebhookRetryTests(TestCase):

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
            payload={
                "type": "delivery.created",
                "data": {"status": "created"},
            },
            status="pending",
        )

    def process_with_status(self, status_code):
        mock_post = Mock(
            return_value=Mock(status_code=status_code)
        )
        result = process_webhook_delivery(
            self.delivery.id,
            http_post=mock_post,
        )
        self.delivery.refresh_from_db()
        return result, mock_post

    def test_http_200_marks_delivered(self):
        result, mock_post = self.process_with_status(200)

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(self.delivery.status, "delivered")
        self.assertEqual(self.delivery.attempt_count, 1)
        self.assertEqual(self.delivery.response_status_code, 200)
        self.assertIsNotNone(self.delivery.delivered_at)
        self.assertIsNone(self.delivery.next_retry_at)
        self.assertEqual(mock_post.call_count, 1)

    def test_http_500_schedules_retry(self):
        result, mock_post = self.process_with_status(500)

        self.assertEqual(result["status"], "retrying")
        self.assertEqual(self.delivery.status, "retrying")
        self.assertEqual(self.delivery.attempt_count, 1)
        self.assertEqual(self.delivery.response_status_code, 500)
        self.assertGreater(self.delivery.next_retry_at, timezone.now())
        self.assertEqual(mock_post.call_count, 1)

    def test_http_429_schedules_retry(self):
        result, mock_post = self.process_with_status(429)

        self.assertEqual(result["status"], "retrying")
        self.assertEqual(self.delivery.status, "retrying")
        self.assertEqual(self.delivery.response_status_code, 429)
        self.assertIsNotNone(self.delivery.next_retry_at)
        self.assertEqual(mock_post.call_count, 1)

    def test_timeout_schedules_retry(self):
        mock_post = Mock(
            side_effect=TimeoutError("Connection timed out")
        )

        result = process_webhook_delivery(
            self.delivery.id,
            http_post=mock_post,
        )
        self.delivery.refresh_from_db()

        self.assertEqual(result["status"], "retrying")
        self.assertEqual(self.delivery.status, "retrying")
        self.assertEqual(self.delivery.attempt_count, 1)
        self.assertIsNone(self.delivery.response_status_code)
        self.assertIn("TimeoutError", self.delivery.last_error)
        self.assertIsNotNone(self.delivery.next_retry_at)

    def test_http_400_fails_without_retry(self):
        result, mock_post = self.process_with_status(400)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.delivery.status, "failed")
        self.assertEqual(self.delivery.attempt_count, 1)
        self.assertIsNone(self.delivery.next_retry_at)
        self.assertEqual(mock_post.call_count, 1)

    def test_exponential_backoff(self):
        expected_delays = [60, 120, 240, 480]

        for attempt, expected_delay in enumerate(
            expected_delays, start=1
        ):
            self.delivery.status = "pending"
            self.delivery.attempt_count = attempt - 1
            self.delivery.next_retry_at = None
            self.delivery.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "next_retry_at",
                ]
            )

            before = timezone.now()
            self.process_with_status(500)
            after = timezone.now()

            self.assertEqual(self.delivery.status, "retrying")
            self.assertEqual(self.delivery.attempt_count, attempt)

            actual_delay = (
                self.delivery.next_retry_at - before
            ).total_seconds()

            self.assertGreaterEqual(actual_delay, expected_delay)
            self.assertLessEqual(
                actual_delay,
                expected_delay + (after - before).total_seconds() + 1,
            )

    def test_stop_after_five_attempts(self):
        self.delivery.attempt_count = 4
        self.delivery.save(update_fields=["attempt_count"])

        result, mock_post = self.process_with_status(500)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.delivery.status, "failed")
        self.assertEqual(self.delivery.attempt_count, 5)
        self.assertIsNone(self.delivery.next_retry_at)
        self.assertEqual(mock_post.call_count, 1)

    def test_future_retry_is_not_processed(self):
        self.delivery.status = "retrying"
        self.delivery.next_retry_at = (
            timezone.now() + timedelta(minutes=5)
        )
        self.delivery.save(
            update_fields=["status", "next_retry_at"]
        )

        mock_post = Mock()
        result = process_webhook_delivery(
            self.delivery.id,
            http_post=mock_post,
        )

        self.delivery.refresh_from_db()

        self.assertEqual(result["status"], "retrying")
        self.assertEqual(self.delivery.attempt_count, 0)
        mock_post.assert_not_called()

    def test_disabled_subscription_fails_delivery(self):
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active"])

        mock_post = Mock()
        result = process_webhook_delivery(
            self.delivery.id,
            http_post=mock_post,
        )

        self.delivery.refresh_from_db()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(self.delivery.status, "failed")
        self.assertIn("disabled", self.delivery.last_error)
        mock_post.assert_not_called()

    def test_success_clears_claim(self):
        self.process_with_status(200)

        self.assertIsNone(self.delivery.claim_token)
        self.assertIsNone(self.delivery.claim_expires_at)

    def test_retry_clears_claim(self):
        self.process_with_status(500)

        self.assertIsNone(self.delivery.claim_token)
        self.assertIsNone(self.delivery.claim_expires_at)

    def test_failed_delivery_cannot_be_reprocessed(self):
        self.delivery.status = "failed"
        self.delivery.save(update_fields=["status"])

        mock_post = Mock()
        result = process_webhook_delivery(
            self.delivery.id,
            http_post=mock_post,
        )

        self.assertEqual(result["status"], "failed")
        mock_post.assert_not_called()

    def test_exhausted_delivery_cannot_send_again(self):
        self.delivery.status = "retrying"
        self.delivery.attempt_count = 5
        self.delivery.next_retry_at = timezone.now() - timedelta(minutes=1)
        self.delivery.save(
            update_fields=["status", "attempt_count", "next_retry_at"]
        )

        mock_post = Mock(return_value=Mock(status_code=500))

        process_webhook_delivery(
            self.delivery.id,
            http_post=mock_post,
        )

        self.delivery.refresh_from_db()

        mock_post.assert_not_called()
        self.assertEqual(self.delivery.attempt_count, 5)
        self.assertEqual(self.delivery.status, "failed")
