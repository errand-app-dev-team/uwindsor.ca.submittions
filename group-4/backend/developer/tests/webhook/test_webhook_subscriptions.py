
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from developer.models import WebhookSubscription
from developer.services.webhook_service import WebhookServiceError
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
    get_webhook_signing_secret,
)


# Use a separate encryption key for subscription tests.
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class WebhookSubscriptionTests(TestCase):

    def setUp(self):
        self.business_owner_id = uuid.uuid4()
        self.environment = "test"
        self.endpoint_url = "https://example.com/webhook"
        self.subscribed_events = ["delivery.created"]

    def create_subscription(self):
        return create_webhook_subscription(
            business_owner_id=self.business_owner_id,
            environment=self.environment,
            endpoint_url=self.endpoint_url,
            subscribed_events=self.subscribed_events,
        )

    def test_create_valid_subscription(self):
        result = self.create_subscription()

        subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        self.assertEqual(
            subscription.business_owner_id,
            self.business_owner_id,
        )
        self.assertEqual(
            subscription.endpoint_url,
            self.endpoint_url,
        )
        self.assertEqual(subscription.environment, "test")
        self.assertEqual(
            subscription.subscribed_events,
            self.subscribed_events,
        )
        self.assertTrue(subscription.is_active)

    def test_return_subscription_details(self):
        result = self.create_subscription()

        self.assertIn("id", result)
        self.assertEqual(result["endpoint_url"], self.endpoint_url)
        self.assertEqual(result["environment"], "test")
        self.assertEqual(
            result["subscribed_events"],
            self.subscribed_events,
        )
        self.assertTrue(result["is_active"])
        self.assertTrue(result["signing_secret"])

    def test_reject_invalid_environment(self):
        with self.assertRaises(ValueError):
            create_webhook_subscription(
                business_owner_id=self.business_owner_id,
                environment="development",
                endpoint_url=self.endpoint_url,
                subscribed_events=self.subscribed_events,
            )

        self.assertEqual(
            WebhookSubscription.objects.count(),
            0,
        )

    def test_create_live_subscription(self):
        result = create_webhook_subscription(
            business_owner_id=self.business_owner_id,
            environment="live",
            endpoint_url=self.endpoint_url,
            subscribed_events=self.subscribed_events,
        )

        subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        self.assertEqual(subscription.environment, "live")

    def test_signing_secret_is_encrypted(self):
        result = self.create_subscription()

        subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        self.assertNotEqual(
            subscription.signing_secret_encrypted,
            result["signing_secret"],
        )

        self.assertNotIn(
            result["signing_secret"],
            subscription.signing_secret_encrypted,
        )

    def test_decrypt_signing_secret(self):
        result = self.create_subscription()

        subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        decrypted_secret = get_webhook_signing_secret(
            subscription
        )

        self.assertEqual(
            decrypted_secret,
            result["signing_secret"],
        )

    def test_each_subscription_has_unique_secret(self):
        first = self.create_subscription()
        second = self.create_subscription()

        self.assertNotEqual(
            first["id"],
            second["id"],
        )

        self.assertNotEqual(
            first["signing_secret"],
            second["signing_secret"],
        )

    def test_secret_is_not_stored_in_plaintext(self):
        result = self.create_subscription()

        subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        stored_secret = subscription.signing_secret_encrypted

        self.assertNotEqual(
            stored_secret,
            result["signing_secret"],
        )

        decrypted = Fernet(
            TEST_ENCRYPTION_KEY.encode("utf-8")
        ).decrypt(
            stored_secret.encode("utf-8")
        ).decode("utf-8")

        self.assertEqual(
            decrypted,
            result["signing_secret"],
        )

    def test_reject_invalid_endpoint(self):
        with self.assertRaises(WebhookServiceError):
            self.create_subscription_with_endpoint(
                "http://example.com/webhook"
            )

        self.assertEqual(
            WebhookSubscription.objects.count(),
            0,
        )

    def create_subscription_with_endpoint(self, endpoint):
        return create_webhook_subscription(
            business_owner_id=self.business_owner_id,
            environment=self.environment,
            endpoint_url=endpoint,
            subscribed_events=self.subscribed_events,
        )

    def test_validation_runs_before_database_creation(self):
        with patch(
            "developer.services.webhook_subscription_service."
            "validate_webhook_subscription",
            side_effect=ValueError("Invalid subscription"),
        ):
            with self.assertRaises(ValueError):
                self.create_subscription()

        self.assertEqual(
            WebhookSubscription.objects.count(),
            0,
        )
