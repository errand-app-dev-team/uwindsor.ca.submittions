
import hashlib
import hmac
import json
import uuid
from unittest.mock import Mock

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from developer.models import WebhookDelivery, WebhookSubscription
from developer.services.webhook_sender_service import send_signed_webhook
from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
    get_webhook_signing_secret,
)


TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class WebhookSigningTests(TestCase):

    def setUp(self):
        self.business_owner_id = uuid.uuid4()

        result = create_webhook_subscription(
            business_owner_id=self.business_owner_id,
            environment="test",
            endpoint_url="https://example.com/webhook",
            subscribed_events=["delivery.created"],
        )

        self.subscription = WebhookSubscription.objects.get(
            id=result["id"]
        )

        self.signing_secret = result["signing_secret"]
        self.event_id = f"evt_{uuid.uuid4().hex}"

        self.payload = {
            "id": self.event_id,
            "type": "delivery.created",
            "business_owner_id": str(self.business_owner_id),
            "data": {
                "delivery_id": "delivery_001",
                "status": "created",
            },
        }

        self.delivery = WebhookDelivery.objects.create(
            subscription=self.subscription,
            event_id=self.event_id,
            event_type="delivery.created",
            payload=self.payload,
            status="processing",
        )

        self.mock_post = Mock(
            return_value=Mock(status_code=200)
        )

    def send_webhook(self):
        return send_signed_webhook(
            self.delivery,
            self.mock_post,
        )

    def test_generate_valid_hmac_signature(self):
        self.send_webhook()

        kwargs = self.mock_post.call_args.kwargs
        payload_bytes = kwargs["data"]
        actual_signature = kwargs["headers"]["X-Aerrand-Signature"]

        expected_signature = hmac.new(
            self.signing_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        self.assertEqual(
            actual_signature,
            f"sha256={expected_signature}",
        )

    def test_signature_matches_exact_payload_bytes(self):
        self.send_webhook()

        kwargs = self.mock_post.call_args.kwargs
        transmitted_body = kwargs["data"]
        signature = kwargs["headers"]["X-Aerrand-Signature"]

        expected_body = json.dumps(
            self.payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        self.assertEqual(transmitted_body, expected_body)

        expected_signature = hmac.new(
            self.signing_secret.encode("utf-8"),
            transmitted_body,
            hashlib.sha256,
        ).hexdigest()

        self.assertEqual(
            signature,
            f"sha256={expected_signature}",
        )

    def test_signature_header_format(self):
        self.send_webhook()

        headers = self.mock_post.call_args.kwargs["headers"]
        signature = headers["X-Aerrand-Signature"]

        self.assertTrue(signature.startswith("sha256="))
        self.assertEqual(len(signature), 71)

    def test_event_id_header(self):
        self.send_webhook()

        headers = self.mock_post.call_args.kwargs["headers"]

        self.assertEqual(
            headers["X-Aerrand-Event-ID"],
            self.event_id,
        )
        self.assertEqual(
            headers["Content-Type"],
            "application/json",
        )

    def test_different_secrets_produce_different_signatures(self):
        self.send_webhook()

        original_signature = (
            self.mock_post.call_args.kwargs["headers"]
            ["X-Aerrand-Signature"]
        )

        other_secret = "different_signing_secret"

        payload_bytes = self.mock_post.call_args.kwargs["data"]

        other_signature = hmac.new(
            other_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        self.assertNotEqual(
            original_signature,
            f"sha256={other_signature}",
        )

    def test_modified_payload_invalidates_signature(self):
        self.send_webhook()

        kwargs = self.mock_post.call_args.kwargs
        original_signature = kwargs["headers"]["X-Aerrand-Signature"]

        modified_payload = dict(self.payload)
        modified_payload["data"] = {
            "delivery_id": "delivery_001",
            "status": "cancelled",
        }

        modified_bytes = json.dumps(
            modified_payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        modified_signature = hmac.new(
            self.signing_secret.encode("utf-8"),
            modified_bytes,
            hashlib.sha256,
        ).hexdigest()

        self.assertNotEqual(
            original_signature,
            f"sha256={modified_signature}",
        )

    def test_redirects_are_disabled(self):
        self.send_webhook()

        kwargs = self.mock_post.call_args.kwargs

        self.assertFalse(kwargs["allow_redirects"])

    def test_request_timeout_is_five_seconds(self):
        self.send_webhook()

        kwargs = self.mock_post.call_args.kwargs

        self.assertEqual(kwargs["timeout"], 5)
        self.assertEqual(
            self.mock_post.call_args.args[0],
            self.subscription.endpoint_url,
        )

    def test_inactive_subscription_cannot_send(self):
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active"])

        with self.assertRaises(ValueError):
            self.send_webhook()

        self.mock_post.assert_not_called()

    def test_unclaimed_delivery_cannot_send(self):
        self.delivery.status = "pending"
        self.delivery.save(update_fields=["status"])

        with self.assertRaises(ValueError):
            self.send_webhook()

        self.mock_post.assert_not_called()
