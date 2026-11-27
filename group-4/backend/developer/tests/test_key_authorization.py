
import uuid
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from developer.services.key_authorization import (
    ApiKeyAuthorizationError,
    require_api_key_scope,
    scope_error_response,
)
from developer.services.key_generation import create_api_key


class ApiKeyAuthorizationServiceTests(SimpleTestCase):

    def test_valid_scope_is_accepted(self):
        request = SimpleNamespace(
            api_key_scopes=["quotes:read", "aerrands:read"]
        )

        self.assertTrue(
            require_api_key_scope(request, "quotes:read")
        )

    def test_missing_scope_is_rejected(self):
        request = SimpleNamespace(
            api_key_scopes=["quotes:read"]
        )

        with self.assertRaises(ApiKeyAuthorizationError):
            require_api_key_scope(request, "aerrands:write")

    def test_missing_authentication_context_is_rejected(self):
        # Requests without authenticated scopes must never be authorized.
        request = SimpleNamespace()

        with self.assertRaises(ApiKeyAuthorizationError):
            require_api_key_scope(request, "quotes:read")

    def test_invalid_scope_collection_is_rejected(self):
        request = SimpleNamespace(
            api_key_scopes="quotes:read"
        )

        with self.assertRaises(ApiKeyAuthorizationError):
            require_api_key_scope(request, "quotes:read")

    def test_scope_error_response_returns_403(self):
        response = scope_error_response("aerrands:write")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json() if hasattr(response, "json")
            else __import__("json").loads(response.content),
            {
                "error": {
                    "code": "insufficient_scope",
                    "message": "API key lacks the required permission.",
                    "required_scope": "aerrands:write",
                }
            },
        )


@override_settings(
    API_KEY_HASH_PEPPER="test_only_pepper",
    API_KEYS_ENABLED=True,
)
class ApiKeyAuthorizationMiddlewareTests(TestCase):

    def setUp(self):
        self.api_key, self.raw_key = create_api_key(
            business_owner_id=uuid.uuid4(),
            created_by_id=uuid.uuid4(),
            name="Authorization Test Key",
            environment="test",
            scopes=["quotes:read", "aerrands:read"],
        )

    def test_missing_api_key_returns_401(self):
        response = self.client.post(
            "/v1/quotes",
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            "invalid_api_key",
        )

    def test_invalid_api_key_returns_401(self):
        response = self.client.post(
            "/v1/quotes",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY="aer_test_invalid123",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            "invalid_api_key",
        )

    def test_read_only_key_cannot_create_aerrand(self):
        # Authorization must reject writes before delivery creation executes.
        response = self.client.post(
            "/v1/errands",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY=self.raw_key,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["required_scope"],
            "aerrands:write",
        )

    def test_read_only_key_cannot_cancel_aerrand(self):
        response = self.client.post(
            "/v1/errands/test-delivery-id/cancel",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY=self.raw_key,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["required_scope"],
            "aerrands:cancel",
        )

    def test_read_only_key_cannot_update_dropoff(self):
        response = self.client.patch(
            "/v1/errands/arr_demo/dropoffs/stop_1",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY=self.raw_key,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["required_scope"],
            "aerrands:write",
        )

    def test_authorized_quote_request_reaches_validation(self):
        # A valid read scope should allow the quote view to validate input.
        response = self.client.post(
            "/v1/quotes",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY=self.raw_key,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "validation_error",
        )

    def test_valid_bearer_key_reaches_validation(self):
        # Send our valid test key using the Bearer header.
        response = self.client.post(
            "/v1/quotes",
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_key}",
        )

        # Authentication passes, but the empty delivery details are invalid.
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "validation_error",
        )

    def test_key_without_read_scope_cannot_view_aerrand(self):
        # Create an API key that can write but cannot read deliveries.
        _, write_only_key = create_api_key(
            business_owner_id=uuid.uuid4(),
            created_by_id=uuid.uuid4(),
            name="Write Only Test Key",
            environment="test",
            scopes=["aerrands:write"],
        )

        response = self.client.get(
            "/v1/errands/test-delivery-id",
            HTTP_X_API_KEY=write_only_key,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["required_scope"],
            "aerrands:read",
        )

    def test_read_only_key_can_reach_aerrand_view(self):
        response = self.client.get(
            "/v1/errands/test-delivery-id",
            HTTP_X_API_KEY=self.raw_key,
        )

        # The key has aerrands:read, so authorization should pass.
        # The delivery does not exist, so the view may return 404.
        self.assertNotEqual(response.status_code, 401)
        self.assertNotEqual(response.status_code, 403)

    def test_key_with_cancel_scope_can_reach_cancel_endpoint(self):
        # Create a key with cancellation permission.
        _, cancel_key = create_api_key(
            business_owner_id=uuid.uuid4(),
            created_by_id=uuid.uuid4(),
            name="Cancel Permission Test Key",
            environment="test",
            scopes=["aerrands:cancel"],
        )

        response = self.client.post(
            "/v1/errands/test-delivery-id/cancel",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY=cancel_key,
        )

        # Authentication and scope authorization should pass.
        # The endpoint may still reject the nonexistent delivery.
        self.assertNotEqual(response.status_code, 401)
        self.assertNotEqual(response.status_code, 403)

    def test_key_with_write_scope_can_reach_create_endpoint(self):
        # Create an API key with delivery creation permission.
        _, write_key = create_api_key(
            business_owner_id=uuid.uuid4(),
            created_by_id=uuid.uuid4(),
            name="Write Permission Test Key",
            environment="test",
            scopes=["aerrands:write"],
        )

        response = self.client.post(
            "/v1/errands",
            data="{}",
            content_type="application/json",
            HTTP_X_API_KEY=write_key,
        )

        # The key is authorized, but the empty payload is invalid.
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.status_code, 403)

    def test_malformed_authorization_is_rejected(self):
        # Try several incorrectly written Authorization headers.
        malformed_headers = [
            "",
            "Bearer",
            "Bearer key extra",
            f"Token {self.raw_key}",
        ]

        for header in malformed_headers:
            with self.subTest(header=header):
                response = self.client.post(
                    "/v1/quotes",
                    data="{}",
                    content_type="application/json",
                    HTTP_AUTHORIZATION=header,
                    # A valid alternative key must not hide a bad
                    # Authorization header.
                    HTTP_X_API_KEY=self.raw_key,
                )

                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "invalid_api_key",
                )
