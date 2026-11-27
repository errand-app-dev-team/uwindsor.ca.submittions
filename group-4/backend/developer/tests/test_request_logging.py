import logging
import json
from uuid import uuid4
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from developer.models import ApiRequestLog
from developer.request_logging import ApiRequestLoggingMiddleware


class ApiRequestLoggingTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.business_owner_id = uuid4()
        self.api_key_id = uuid4()

    def make_request(self, path="/v1/errands"):
        request = self.factory.get(path)
        request.business_owner_id = self.business_owner_id
        request.api_key_id = self.api_key_id
        return request

    def test_authenticated_request_is_logged(self):
        middleware = ApiRequestLoggingMiddleware(
            lambda request: JsonResponse({"data": []}, status=200)
        )

        response = middleware(self.make_request())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ApiRequestLog.objects.count(), 1)

        log = ApiRequestLog.objects.first()
        self.assertEqual(log.path, "/v1/errands")
        self.assertEqual(log.method, "GET")
        self.assertEqual(log.status, 200)
        self.assertEqual(log.business_owner_id, self.business_owner_id)
        self.assertGreaterEqual(log.duration_ms, 0)

    def test_unauthenticated_request_is_not_logged(self):
        middleware = ApiRequestLoggingMiddleware(
            lambda request: JsonResponse({"error": "unauthorized"}, status=401)
        )

        request = self.factory.get("/v1/errands")
        middleware(request)

        self.assertEqual(ApiRequestLog.objects.count(), 0)

    def test_non_api_request_is_not_logged(self):
        middleware = ApiRequestLoggingMiddleware(
            lambda request: JsonResponse({"ok": True})
        )

        middleware(self.make_request("/admin/"))

        self.assertEqual(ApiRequestLog.objects.count(), 0)

    def test_error_code_is_logged(self):
        middleware = ApiRequestLoggingMiddleware(
            lambda request: JsonResponse(
                {"error": "validation_error"},
                status=400,
            )
        )

        middleware(self.make_request())

        log = ApiRequestLog.objects.first()
        self.assertEqual(log.status, 400)
        self.assertEqual(log.error_code, "validation_error")

    def test_idempotency_replay_is_logged(self):
        def get_response(request):
            response = JsonResponse({"id": "errand-123"}, status=201)
            response["Idempotency-Replayed"] = "true"
            return response

        middleware = ApiRequestLoggingMiddleware(get_response)

        request = self.make_request()
        request.META["HTTP_IDEMPOTENCY_KEY"] = str(uuid4())

        middleware(request)

        log = ApiRequestLog.objects.first()
        self.assertTrue(log.idempotenct_replay)
        self.assertEqual(
            log.idempotency_key,
            request.headers["Idempotency-Key"],
        )

    @patch("developer.request_logging.ApiRequestLog.objects.create")
    def test_logging_failure_does_not_interrupt_response(self, mock_create):
        mock_create.side_effect = Exception("Database unavailable")

        middleware = ApiRequestLoggingMiddleware(
            lambda request: JsonResponse({"ok": True}, status=200)
        )

        # Capture the expected error log without printing its traceback.
        with self.assertLogs("developer.request_logging", level="ERROR") as logs:
            response = middleware(self.make_request())

        self.assertEqual(response.status_code, 200)
        self.assertIn("Failed to save API request log", logs.output[0])
