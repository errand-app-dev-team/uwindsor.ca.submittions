
import uuid
from datetime import datetime

from django.test import SimpleTestCase

from developer.services.webhook_service import (
    WebhookServiceError,
    generate_webhook_event,
)


class WebhookEventTests(SimpleTestCase):

    def setUp(self):
        self.business_owner_id = str(uuid.uuid4())
        self.event_type = "delivery.created"
        self.data = {
            "delivery_id": "delivery_001",
            "status": "created",
        }

    def test_generate_valid_event(self):
        event = generate_webhook_event(
            event_type=self.event_type,
            business_owner_id=self.business_owner_id,
            data=self.data,
        )

        self.assertTrue(event["id"].startswith("evt_"))
        self.assertEqual(event["type"], self.event_type)
        self.assertEqual(
            event["business_owner_id"],
            self.business_owner_id,
        )
        self.assertEqual(event["data"], self.data)

        timestamp = datetime.fromisoformat(event["created_at"])
        self.assertIsNotNone(timestamp.tzinfo)

    def test_reject_empty_event_type(self):
        with self.assertRaises(WebhookServiceError):
            generate_webhook_event(
                event_type="",
                business_owner_id=self.business_owner_id,
                data=self.data,
            )

    def test_reject_invalid_business_owner_id(self):
        with self.assertRaises(WebhookServiceError):
            generate_webhook_event(
                event_type=self.event_type,
                business_owner_id=uuid.uuid4(),
                data=self.data,
            )

    def test_reject_invalid_event_data(self):
        with self.assertRaises(WebhookServiceError):
            generate_webhook_event(
                event_type=self.event_type,
                business_owner_id=self.business_owner_id,
                data="invalid data",
            )

    def test_generate_unique_event_ids(self):
        first = generate_webhook_event(
            self.event_type,
            self.business_owner_id,
            self.data,
        )

        second = generate_webhook_event(
            self.event_type,
            self.business_owner_id,
            self.data,
        )

        self.assertNotEqual(first["id"], second["id"])
