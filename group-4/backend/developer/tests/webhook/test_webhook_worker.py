
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch
from django.contrib.auth import get_user_model
from django.urls import reverse

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from developer.models import WebhookDelivery, WebhookSubscription
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
)


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

HTTP_CLIENT_PATH = (
    "developer.management.commands.process_webhooks.secure_webhook_post"
)

PROCESS_DELIVERY_PATH = (
    "developer.management.commands.process_webhooks.process_webhook_delivery"
)


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class WebhookWorkerTests(TestCase):

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

    def create_delivery(self, status="pending", **fields):
        values = {
            "subscription": self.subscription,
            "event_id": f"evt_{uuid.uuid4().hex}",
            "event_type": "delivery.created",
            "payload": {
                "type": "delivery.created",
                "data": {"status": "created"},
            },
            "status": status,
        }
        values.update(fields)

        return WebhookDelivery.objects.create(**values)

    def run_worker(self, batch_size=20):
        output = StringIO()

        with patch(
            HTTP_CLIENT_PATH,
            return_value=Mock(status_code=200),
        ) as mock_post:
            call_command(
                "process_webhooks",
                once=True,
                batch_size=batch_size,
                stdout=output,
            )

        return mock_post, output.getvalue()

    def test_process_pending_delivery(self):
        delivery = self.create_delivery()

        mock_post, output = self.run_worker()

        delivery.refresh_from_db()

        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(mock_post.call_count, 1)

    def test_process_due_retry(self):
        delivery = self.create_delivery(
            status="retrying",
            next_retry_at=timezone.now() - timedelta(seconds=10),
        )

        mock_post, output = self.run_worker()

        delivery.refresh_from_db()

        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(mock_post.call_count, 1)

    def test_skip_future_retry(self):
        delivery = self.create_delivery(
            status="retrying",
            next_retry_at=timezone.now() + timedelta(minutes=5),
        )

        mock_post, output = self.run_worker()

        delivery.refresh_from_db()

        self.assertEqual(delivery.status, "retrying")
        self.assertEqual(delivery.attempt_count, 0)
        mock_post.assert_not_called()

    def test_recover_expired_claim(self):
        delivery = self.create_delivery(
            status="processing",
            claim_token=uuid.uuid4(),
            claim_expires_at=timezone.now() - timedelta(minutes=1),
        )

        mock_post, output = self.run_worker()

        delivery.refresh_from_db()

        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIsNone(delivery.claim_token)
        self.assertEqual(mock_post.call_count, 1)

    def test_skip_active_claim(self):
        delivery = self.create_delivery(
            status="processing",
            claim_token=uuid.uuid4(),
            claim_expires_at=timezone.now() + timedelta(minutes=1),
        )

        mock_post, output = self.run_worker()

        delivery.refresh_from_db()

        self.assertEqual(delivery.status, "processing")
        self.assertEqual(delivery.attempt_count, 0)
        mock_post.assert_not_called()

    def test_respect_batch_size(self):
        deliveries = [
            self.create_delivery()
            for _ in range(5)
        ]

        mock_post, output = self.run_worker(batch_size=2)

        delivered_count = WebhookDelivery.objects.filter(
            id__in=[delivery.id for delivery in deliveries],
            status="delivered",
        ).count()

        self.assertEqual(delivered_count, 2)
        self.assertEqual(mock_post.call_count, 2)

    def test_process_multiple_deliveries(self):
        deliveries = [
            self.create_delivery()
            for _ in range(3)
        ]

        mock_post, output = self.run_worker()

        for delivery in deliveries:
            delivery.refresh_from_db()
            self.assertEqual(delivery.status, "delivered")

        self.assertEqual(mock_post.call_count, 3)

    def test_continue_after_delivery_error(self):
        first = self.create_delivery()
        second = self.create_delivery()

        output = StringIO()
        errors = StringIO()

        with patch(
            PROCESS_DELIVERY_PATH,
            side_effect=[
                RuntimeError("Simulated worker error"),
                {"status": "delivered"},
            ],
        ) as mock_process:
            call_command(
                "process_webhooks",
                once=True,
                stdout=output,
                stderr=errors,
            )

        self.assertEqual(mock_process.call_count, 2)
        self.assertIn("Simulated worker error", errors.getvalue())

    def test_reject_invalid_interval(self):
        with self.assertRaises(ValueError):
            call_command(
                "process_webhooks",
                once=True,
                interval=0,
            )

    def test_reject_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            call_command(
                "process_webhooks",
                once=True,
                batch_size=0,
            )

    def test_dashboard_webhook_failure_rate(self):
        admin = get_user_model().objects.create_superuser(
            username="webhook-metrics-admin",
            email="webhook-metrics-admin@example.com",
            password="test-only-password",
        )
        self.client.force_login(admin)
        url = reverse("admin-dashboard-data")
        metric = "webhook_failure_rate_last_24h"

        def assert_rate(expected):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertContains(response, f'"{metric}": {expected}')

        self.create_delivery(status="pending")
        self.create_delivery(status="retrying")
        assert_rate("null")

        self.create_delivery(status="delivered")
        assert_rate("0.0")

        self.create_delivery(status="failed")
        assert_rate("50.0")