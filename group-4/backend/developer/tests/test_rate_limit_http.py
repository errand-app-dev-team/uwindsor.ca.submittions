
import json
from uuid import uuid4
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver"])
class RateLimitHTTPTests(SimpleTestCase):

    @patch("developer.request_logging.ApiRequestLog.objects.create")
    @patch("developer.rate_limit_middleware.ApiKey.objects.filter")
    @patch("developer.rate_limit_middleware.check_rate_limit")
    @patch(
        "developer.middleware.ApiKeyAuthenticationMiddleware.__call__",
        autospec=True,
    )
    def test_rate_limited_request(
        self, mock_auth, mock_rate_limit, mock_filter, mock_log
    ):
        api_key_id = uuid4()
        business_owner_id = uuid4()

        # Simulate successful authentication while preserving downstream middleware.
        def authenticated_request(middleware, request):
            request.api_key_id = api_key_id
            request.business_owner_id = business_owner_id
            return middleware.get_response(request)

        mock_auth.side_effect = authenticated_request

        mock_filter.return_value.values_list.return_value.first.return_value = None
        mock_rate_limit.return_value = (False, 15)

        with patch(
            "developer.rate_limit_middleware.BusinessApiAccess.objects.filter"
        ) as lookup:
            lookup.return_value.first.return_value = None
            response = Client().get("/v1/errands")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "15")
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "rate_limit_exceeded",
        )

        mock_rate_limit.assert_called_once_with(api_key_id, limit=60)
        mock_log.assert_called_once()

        logged_data = mock_log.call_args.kwargs
        self.assertEqual(logged_data["status"], 429)
        self.assertEqual(logged_data["error_code"], "rate_limit_exceeded")
