
import json
from uuid import uuid4
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from developer.rate_limit_middleware import ApiRateLimitMiddleware


class ApiRateLimitMiddlewareTests(SimpleTestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.api_key_id = uuid4()

        self.middleware = ApiRateLimitMiddleware(
            lambda request: JsonResponse({"success": True})
        )

    def make_request(self, path="/v1/errands", authenticated=True):
        request = self.factory.get(path)

        if authenticated:
            request.api_key_id = self.api_key_id

        return request

    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_request_within_limit(self, mock_check, mock_filter):
        mock_filter.return_value.values_list.return_value.first.return_value = None
        mock_check.return_value = (True, 30)

        response = self.middleware(self.make_request())

        self.assertEqual(response.status_code, 200)
        mock_check.assert_called_once_with(self.api_key_id, limit=60)
        mock_filter.assert_called_once_with(pk=self.api_key_id)

    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_rate_limit_exceeded(self, mock_check, mock_filter):
        mock_filter.return_value.values_list.return_value.first.return_value = None
        mock_check.return_value = (False, 25)

        response = self.middleware(self.make_request())

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "25")
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "rate_limit_exceeded",
        )
        mock_check.assert_called_once_with(self.api_key_id, limit=60)

    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_unauthenticated_request_is_skipped(self, mock_check, mock_filter):
        response = self.middleware(
            self.make_request(authenticated=False)
        )

        self.assertEqual(response.status_code, 200)
        mock_check.assert_not_called()
        mock_filter.assert_not_called()

    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_non_api_request_is_skipped(self, mock_check, mock_filter):
        response = self.middleware(
            self.make_request(path="/admin/")
        )

        self.assertEqual(response.status_code, 200)
        mock_check.assert_not_called()
        mock_filter.assert_not_called()

    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_custom_rate_limit_override(self, mock_check, mock_filter):
        # A configured override replaces the default request limit.
        mock_filter.return_value.values_list.return_value.first.return_value = {
            "requests_per_minute": 120
        }
        mock_check.return_value = (True, 30)

        response = self.middleware(self.make_request())

        self.assertEqual(response.status_code, 200)
        mock_check.assert_called_once_with(self.api_key_id, limit=120)

    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_invalid_rate_limit_override(self, mock_check, mock_filter):
        # Invalid limits fall back to the default of 60.
        mock_filter.return_value.values_list.return_value.first.return_value = {
            "requests_per_minute": -10
        }
        mock_check.return_value = (True, 30)

        response = self.middleware(self.make_request())

        self.assertEqual(response.status_code, 200)
        mock_check.assert_called_once_with(self.api_key_id, limit=60)
