
import json
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from django.test import RequestFactory, TestCase

from aerrands.views import create_aerrand
from aerrands.services.aerrand_service import QuoteNotFoundError
from developer.models import ApiIdempotencyRecord, BusinessApiAccess
from developer.services.idempotency_service import claim_idempotency_key


class IdempotencyViewTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.business_owner_id = uuid4()
        self.key = str(uuid4())

        # Valid delivery payload shared by the idempotency tests.
        self.payload = {
            "reference": "SHOP-10432",
            "quote_id": "quote-123",
            "vehicle_type": "car",
            "pickup": {
                "label": "500 Ouellette Ave, Windsor, ON",
                "lat": "42.3149",
                "lng": "-83.0364",
                "contact": {
                    "name": "Store Manager",
                    "phone_number": "+15195550137",
                    "preference": "pickup",
                },
            },
            "dropoff": {
                "label": "1823 Wyandotte St E, Windsor, ON",
                "lat": "42.3201",
                "lng": "-83.0187",
                "contact": {
                    "name": "Customer",
                    "phone_number": "+15195550188",
                    "preference": "leave_at_door",
                },
            },
            "parcel": {
                "size": "medium",
                "quantity": 1,
                "description": "Package",
            },
            "payment": {
                "method": "invoice",
            },
        }

    def make_request(self, payload=None, key=None):
        request = self.factory.post(
            "/v1/errands",
            data=json.dumps(
                self.payload if payload is None else payload
            ),
            content_type="application/json",
            **(
                {
                    "HTTP_IDEMPOTENCY_KEY": (
                        self.key if key is None else key
                    )
                }
                if key is not False
                else {}
            ),
        )

        request.business_owner_id = self.business_owner_id
        request.api_key_id = str(uuid4())
        request.api_environment = "test"

        return request

    @patch("aerrands.views.validate_aerrand_request")
    def test_missing_idempotency_key(self, mock_validate):
        mock_validate.return_value = self.payload

        response = create_aerrand(
            self.make_request(key=False)
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content)["error"],
            "missing_idempotency_key",
        )

    @patch("aerrands.views.validate_aerrand_request")
    @patch("aerrands.views.create_aerrand_service")
    def test_successful_request_creates_record(
        self, mock_service, mock_validate
    ):
        mock_validate.return_value = self.payload
        mock_service.return_value = {"id": "errand-123"}

        response = create_aerrand(self.make_request())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            ApiIdempotencyRecord.objects.count(),
            1,
        )
        self.assertEqual(
            ApiIdempotencyRecord.objects.first().status,
            "completed",
        )

    @patch("aerrands.views.validate_aerrand_request")
    @patch("aerrands.views.create_aerrand_service")
    def test_completed_request_is_replayed(
        self, mock_service, mock_validate
    ):
        mock_validate.return_value = self.payload
        mock_service.return_value = {"id": "errand-123"}

        first = create_aerrand(self.make_request())
        second = create_aerrand(self.make_request())

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            second["Idempotency-Replayed"],
            "true",
        )
        mock_service.assert_called_once()

    @patch("aerrands.views.validate_aerrand_request")
    @patch("aerrands.views.create_aerrand_service")
    def test_different_payload_returns_conflict(
        self, mock_service, mock_validate
    ):
        mock_validate.side_effect = lambda data: data
        mock_service.return_value = {"id": "errand-123"}

        # Complete the original request using the idempotency key.
        first = create_aerrand(self.make_request())
        self.assertEqual(first.status_code, 201)

        # Change the quote while preserving a valid delivery payload.
        different_payload = {
            **self.payload,
            "quote_id": "different-quote",
        }

        response = create_aerrand(
            self.make_request(payload=different_payload)
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"],
            "idempotency_conflict",
        )
        mock_service.assert_called_once()

    @patch("aerrands.views.validate_aerrand_request")
    @patch("aerrands.views.create_aerrand_service")
    def test_processing_request_returns_conflict(
        self, mock_service, mock_validate
    ):
        mock_validate.return_value = self.payload

        # Simulate a request that has already claimed the key.
        claim_idempotency_key(
            self.business_owner_id,
            self.key,
            "POST",
            "/v1/errands",
            self.payload,
        )

        response = create_aerrand(self.make_request())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"],
            "idempotency_in_progress",
        )
        mock_service.assert_not_called()

    @patch("aerrands.views.validate_aerrand_request")
    @patch("aerrands.views.create_aerrand_service")
    def test_service_unavailable_keeps_idempotency_claim(
        self, mock_service, mock_validate
    ):
        from aerrands.services.aerrand_service import (
            AerrandIntegrationUnavailableError,
        )

        mock_validate.return_value = self.payload
        mock_service.side_effect = AerrandIntegrationUnavailableError(
            "Aerrand platform integration is unavailable."
        )

        first = create_aerrand(self.make_request())
        second = create_aerrand(self.make_request())

        self.assertEqual(first.status_code, 503)
        self.assertEqual(second.status_code, 409)

        record = ApiIdempotencyRecord.objects.get(
            business_owner_id=self.business_owner_id,
            idempotency_key=self.key,
        )

        self.assertEqual(record.status, "processing")
        mock_service.assert_called_once()

    @patch("aerrands.views.create_aerrand_service", return_value={"id": "errand-123"})
    @patch("developer.services.daily_quota.now")
    def test_quota_is_shared_across_keys_and_replay_does_not_consume_it(
        self, mock_now, mock_service
    ):
        mock_now.return_value = datetime(2026, 11, 10, 23, 59, 59, tzinfo=timezone.utc)
        BusinessApiAccess.objects.create(
            business_owner_id=self.business_owner_id, daily_creation_quota=1,
        )

        self.assertEqual(create_aerrand(self.make_request()).status_code, 201)
        replay = create_aerrand(self.make_request())
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay["Idempotency-Replayed"], "true")

        other_key = str(uuid4())
        blocked = create_aerrand(self.make_request(key=other_key))
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(json.loads(blocked.content)["error"], "daily_quota_exceeded")
        self.assertEqual(blocked["Retry-After"], "1")
        mock_service.assert_called_once()

        # Another business gets its own allowance on the same day.
        another_business = self.make_request()
        another_business.business_owner_id = uuid4()
        self.assertEqual(create_aerrand(another_business).status_code, 201)

        # The rejected key can try again at midnight without a stale claim.
        mock_now.return_value = datetime(2026, 11, 11, tzinfo=timezone.utc)
        self.assertEqual(
            create_aerrand(self.make_request(key=other_key)).status_code, 201,
        )
        self.assertEqual(mock_service.call_count, 3)

    @patch("aerrands.views.create_aerrand_service")
    def test_definite_failure_returns_the_reserved_quota_slot(self, mock_service):
        BusinessApiAccess.objects.create(
            business_owner_id=self.business_owner_id, daily_creation_quota=1,
        )
        mock_service.side_effect = [
            QuoteNotFoundError("Quote not found."), {"id": "errand-123"},
        ]

        self.assertEqual(create_aerrand(self.make_request()).status_code, 404)
        self.assertEqual(
            create_aerrand(self.make_request(key=str(uuid4()))).status_code, 201,
        )
