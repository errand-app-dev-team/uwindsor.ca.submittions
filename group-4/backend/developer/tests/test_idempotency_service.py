
from uuid import uuid4

from django.test import TestCase

from developer.models import ApiIdempotencyRecord
from developer.services.idempotency_service import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    claim_idempotency_key,
    complete_idempotency_record,
    generate_request_hash,
)
from django.http import JsonResponse


class IdempotencyServiceTests(TestCase):

    def setUp(self):
        self.business_owner_id = uuid4()
        self.key = str(uuid4())
        self.method = "POST"
        self.path = "/v1/errands"
        self.data = {"quote_id": "quote-123"}

    def claim(self, data=None):
        return claim_idempotency_key(
            business_owner_id=self.business_owner_id,
            key=self.key,
            method=self.method,
            path=self.path,
            data=self.data if data is None else data,
        )

    def test_request_hash_is_order_independent(self):
        first = {"quote_id": "123", "priority": "standard"}
        second = {"priority": "standard", "quote_id": "123"}

        self.assertEqual(
            generate_request_hash(first),
            generate_request_hash(second),
        )

    def test_new_key_creates_processing_record(self):
        record, replay = self.claim()

        self.assertFalse(replay)
        self.assertEqual(record.status, "processing")
        self.assertEqual(ApiIdempotencyRecord.objects.count(), 1)

    def test_duplicate_processing_request_is_rejected(self):
        self.claim()

        with self.assertRaises(IdempotencyInProgressError):
            self.claim()

    def test_same_key_different_payload_is_rejected(self):
        self.claim()

        with self.assertRaises(IdempotencyConflictError):
            self.claim({"quote_id": "different-quote"})

    def test_completed_request_can_be_replayed(self):
        record, _ = self.claim()

        response = JsonResponse(
            {"id": "errand-123"},
            status=201,
        )

        complete_idempotency_record(record, response)

        saved_record, replay = self.claim()

        self.assertTrue(replay)
        self.assertEqual(saved_record.status, "completed")
        self.assertEqual(saved_record.response_status, 201)
        self.assertEqual(
            saved_record.response_body,
            {"id": "errand-123"},
        )
