
import json
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory

from aerrands.services.aerrand_service import AerrandContext
from aerrands.services.quote_service import QuoteInputError
from aerrands.views import (
    authentication_error,
    get_authenticated_context,
    list_aerrands,
    retrieve_aerrand,
    create_quote,
)


class AerrandViewHelperTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def authenticated_request(self, path):
        """Create a request with the authentication context supplied by middleware."""
        request = self.factory.get(path)
        request.business_owner_id = "business_123"
        request.api_key_id = "key_123"
        request.api_environment = "test"
        return request

    def test_missing_authentication_context(self):
        request = self.factory.get("/v1/errands")

        # Requests without middleware authentication must not have a valid context.
        context = get_authenticated_context(request, AerrandContext)

        self.assertIsNone(context)

    def test_valid_authentication_context(self):
        request = self.authenticated_request("/v1/errands")

        context = get_authenticated_context(request, AerrandContext)

        self.assertEqual(context.business_owner_id, "business_123")
        self.assertEqual(context.api_key_id, "key_123")
        self.assertEqual(context.environment, "test")

    def test_authentication_error_response(self):
        response = authentication_error()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["error"],
            "authentication_context_unavailable",
        )

    def test_retrieve_aerrand_without_authentication(self):
        request = self.factory.get("/v1/errands/arr_123")

        # The view must reject requests without a valid authentication context.
        response = retrieve_aerrand(request, "arr_123")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["error"],
            "authentication_context_unavailable",
        )

    def test_retrieve_aerrand_without_platform_integration(self):
        request = self.authenticated_request("/v1/errands/arr_123")

        # Authentication alone must not bypass unavailable platform services.
        response = retrieve_aerrand(request, "arr_123")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["error"],
            "aerrand_service_unavailable",
        )

    def test_list_aerrands_rejects_invalid_limit(self):
        request = self.authenticated_request("/v1/errands?limit=101")

        # Pagination limits outside the accepted range must be rejected.
        response = list_aerrands(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content)["error"],
            "validation_error",
        )

    def test_list_aerrands_accepts_valid_limit(self):
        request = self.authenticated_request("/v1/errands?limit=25")

        # A valid request reaches the service, which remains unavailable.
        response = list_aerrands(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["error"],
            "aerrand_service_unavailable",
        )

    def test_list_aerrands_passes_limit_to_service(self):
        request = self.authenticated_request(
            "/v1/errands?limit=25&cursor=next_page"
        )

        # Mock the service to verify pagination and tenant context forwarding.
        with patch("aerrands.views.list_aerrands_service") as mock_service:
            mock_service.return_value = {
                "data": [],
                "next_cursor": None,
            }

            response = list_aerrands(request)

        self.assertEqual(response.status_code, 200)
        mock_service.assert_called_once()

        kwargs = mock_service.call_args.kwargs

        self.assertEqual(kwargs["limit"], 25)
        self.assertEqual(kwargs["cursor"], "next_page")
        self.assertEqual(kwargs["context"].business_owner_id, "business_123")
        self.assertEqual(kwargs["context"].environment, "test")

    def test_list_aerrands_rejects_invalid_cursor(self):
        request = self.authenticated_request("/v1/errands?cursor=")

        # Empty pagination cursors must fail validation before service execution.
        response = list_aerrands(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content)["error"],
            "validation_error",
        )

    def test_create_quote_returns_400_for_unsupported_location(self):
        request = self.factory.post(
            "/v1/quotes",
            data=json.dumps({
                "pickup": {"address": "1 Pickup St"},
                "stops": [
                    {
                        "address": "2 Delivery St",
                        "parcels": {"small": 1},
                    }
                ],
            }),
            content_type="application/json",
        )

        # Supply the authentication context normally attached by middleware.
        request.business_owner_id = "business_123"
        request.api_key_id = "key_123"
        request.api_environment = "test"

        # Isolate the view's handling of unsupported quote inputs.
        with patch(
                "aerrands.views.create_quote_service",
                side_effect=QuoteInputError("Coordinates are required."),
        ):
            response = create_quote(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content)["error"],
            "validation_error",
        )
