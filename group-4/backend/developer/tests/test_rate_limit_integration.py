
import json
from uuid import uuid4
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from developer.request_logging import ApiRequestLoggingMiddleware
from developer.rate_limit_middleware import ApiRateLimitMiddleware


class RateLimitIntegrationTests(SimpleTestCase):

    @patch("developer.request_logging.ApiRequestLog.objects.create")
    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    def test_rate_limit_response_is_logged(
        self, mock_rate_limit, mock_filter, mock_log
    ):
        api_key_id = uuid4()
        business_owner_id = uuid4()

        # Simulate authentication attaching the partner identity.
        def authenticate(request):
            request.api_key_id = api_key_id
            request.business_owner_id = business_owner_id
            return rate_limit(request)

        rate_limit = ApiRateLimitMiddleware(
            lambda request: JsonResponse({"success": True})
        )

        logging_middleware = ApiRequestLoggingMiddleware(authenticate)

        # Simulate the default rate limit being exceeded.
        mock_filter.return_value.values_list.return_value.first.return_value = None
        mock_rate_limit.return_value = (False, 20)

        request = RequestFactory().get("/v1/errands")
        with patch(
            "developer.rate_limit_middleware.BusinessApiAccess.objects.filter"
        ) as lookup:
            lookup.return_value.first.return_value = None
            response = logging_middleware(request)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "20")
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "rate_limit_exceeded",
        )

        mock_rate_limit.assert_called_once_with(api_key_id, limit=60)
        mock_filter.assert_called_once_with(pk=api_key_id)
        mock_log.assert_called_once()

        logged_data = mock_log.call_args.kwargs

        self.assertEqual(logged_data["status"], 429)
        self.assertEqual(logged_data["api_key_id"], api_key_id)
        self.assertEqual(
            logged_data["business_owner_id"],
            business_owner_id,
        )
        self.assertEqual(
            logged_data["error_code"],
            "rate_limit_exceeded",
        )
