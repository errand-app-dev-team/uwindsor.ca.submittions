
"""Verify webhook subscription isolation between partner businesses."""

import uuid
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory

from developer import webhook_views
from developer.models import WebhookSubscription


class WebhookIsolationTests(SimpleTestCase):
    """Ensure webhook operations use the authenticated business context."""

    def setUp(self):
        self.factory = RequestFactory()
        self.business_a = uuid.uuid4()
        self.business_b = uuid.uuid4()

    def make_request(self, method, business_id, scopes, path="/v1/webhooks"):
        """Create a request with an authenticated partner API context."""
        request = getattr(self.factory, method.lower())(path)
        request.business_owner_id = business_id
        request.api_environment = "test"
        request.api_key_id = uuid.uuid4()
        request.api_scopes = scopes
        return request

    @patch.object(webhook_views, "require_api_key_scope")
    @patch.object(WebhookSubscription.objects, "filter")
    def test_business_a_lists_only_own_subscriptions(self, mock_filter, mock_scope):
        request = self.make_request(
            "GET", self.business_a, ["webhooks:manage"]
        )
        mock_filter.return_value.order_by.return_value.__getitem__.return_value = []

        response = webhook_views.webhooks_collection(request)

        self.assertEqual(response.status_code, 200)
        mock_filter.assert_called_once_with(
            business_owner_id=self.business_a,
            environment="test",
        )

    @patch.object(webhook_views, "require_api_key_scope")
    @patch.object(WebhookSubscription.objects, "filter")
    def test_business_b_cannot_list_business_a_subscriptions(
        self, mock_filter, mock_scope
    ):
        request = self.make_request(
            "GET", self.business_b, ["webhooks:manage"]
        )
        mock_filter.return_value.order_by.return_value.__getitem__.return_value = []

        response = webhook_views.webhooks_collection(request)

        self.assertEqual(response.status_code, 200)
        mock_filter.assert_called_once_with(
            business_owner_id=self.business_b,
            environment="test",
        )

    @patch.object(webhook_views, "require_api_key_scope")
    @patch.object(WebhookSubscription.objects, "get")
    def test_business_b_cannot_disable_business_a_webhook(
        self, mock_get, mock_scope
    ):
        subscription_id = uuid.uuid4()
        request = self.make_request(
            "POST", self.business_b, ["webhooks:manage"]
        )

        mock_get.side_effect = WebhookSubscription.DoesNotExist

        response = webhook_views.disable_webhook(request, subscription_id)

        self.assertEqual(response.status_code, 404)
        mock_get.assert_called_once_with(
            id=subscription_id,
            business_owner_id=self.business_b,
            environment="test",
        )

    @patch.object(webhook_views, "require_api_key_scope")
    def test_key_without_manage_scope_is_rejected(self, mock_scope):
        from developer.services.key_authorization import ApiKeyAuthorizationError

        mock_scope.side_effect = ApiKeyAuthorizationError(
            "Missing required scope."
        )

        request = self.make_request(
            "GET", self.business_a, ["webhooks:read"]
        )

        response = webhook_views.webhooks_collection(request)

        self.assertEqual(response.status_code, 403)

    def test_missing_api_key_context_is_rejected(self):
        request = self.factory.get("/v1/webhooks")

        response = webhook_views.webhooks_collection(request)

        self.assertEqual(response.status_code, 401)



from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from developer.services.webhook_subscription_service import (
    create_webhook_subscription,
)


TEST_DB_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@override_settings(WEBHOOK_ENCRYPTION_KEY=TEST_DB_ENCRYPTION_KEY)
class WebhookDatabaseIsolationTests(TestCase):
    """Verify business and environment isolation using stored subscriptions."""

    def setUp(self):
        self.factory = RequestFactory()
        self.business_a = uuid.uuid4()
        self.business_b = uuid.uuid4()

        self.subscription_a = self.create_subscription(
            self.business_a, "test"
        )
        self.subscription_b = self.create_subscription(
            self.business_b, "test"
        )
        self.subscription_a_live = self.create_subscription(
            self.business_a, "live"
        )

    def create_subscription(self, business_id, environment):
        """Create a subscription through the existing service."""
        result = create_webhook_subscription(
            business_owner_id=business_id,
            environment=environment,
            endpoint_url="https://example.com/webhook",
            subscribed_events=["delivery.created"],
        )
        return WebhookSubscription.objects.get(id=result["id"])

    def make_request(self, method, business_id, environment="test"):
        """Build an authenticated request for a specific business."""
        request = getattr(self.factory, method.lower())("/v1/webhooks")
        request.business_owner_id = business_id
        request.api_environment = environment
        request.api_key_id = uuid.uuid4()
        request.api_scopes = ["webhooks:manage"]
        return request

    @patch.object(webhook_views, "require_api_key_scope")
    def test_business_a_lists_only_its_test_subscriptions(self, mock_scope):
        request = self.make_request("GET", self.business_a)

        response = webhook_views.webhooks_collection(request)

        self.assertEqual(response.status_code, 200)

        import json

        subscriptions = json.loads(response.content)["data"]
        returned_ids = {item["id"] for item in subscriptions}

        self.assertEqual(returned_ids, {str(self.subscription_a.id)})
        self.assertNotIn(str(self.subscription_b.id), returned_ids)
        self.assertNotIn(str(self.subscription_a_live.id), returned_ids)

    @patch.object(webhook_views, "require_api_key_scope")
    def test_business_b_cannot_list_business_a_subscriptions(self, mock_scope):
        request = self.make_request("GET", self.business_b)

        response = webhook_views.webhooks_collection(request)

        self.assertEqual(response.status_code, 200)

        import json

        subscriptions = json.loads(response.content)["data"]
        returned_ids = {item["id"] for item in subscriptions}

        self.assertEqual(returned_ids, {str(self.subscription_b.id)})
        self.assertNotIn(str(self.subscription_a.id), returned_ids)

    @patch.object(webhook_views, "require_api_key_scope")
    def test_business_b_cannot_disable_business_a_webhook(self, mock_scope):
        request = self.make_request("POST", self.business_b)

        response = webhook_views.disable_webhook(
            request, self.subscription_a.id
        )

        self.assertEqual(response.status_code, 404)

        self.subscription_a.refresh_from_db()
        self.assertTrue(self.subscription_a.is_active)

    @patch.object(webhook_views, "require_api_key_scope")
    def test_business_a_can_disable_its_own_webhook(self, mock_scope):
        request = self.make_request("POST", self.business_a)

        response = webhook_views.disable_webhook(
            request, self.subscription_a.id
        )

        self.assertEqual(response.status_code, 200)

        self.subscription_a.refresh_from_db()
        self.assertFalse(self.subscription_a.is_active)

        self.subscription_b.refresh_from_db()
        self.assertTrue(self.subscription_b.is_active)

    @patch.object(webhook_views, "require_api_key_scope")
    def test_test_environment_cannot_disable_live_webhook(self, mock_scope):
        request = self.make_request(
            "POST", self.business_a, environment="test"
        )

        response = webhook_views.disable_webhook(
            request, self.subscription_a_live.id
        )

        self.assertEqual(response.status_code, 404)

        self.subscription_a_live.refresh_from_db()
        self.assertTrue(self.subscription_a_live.is_active)
