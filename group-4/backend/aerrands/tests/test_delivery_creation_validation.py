from django.test import SimpleTestCase

from aerrands.validators import (
    DeliveryValidationError,
    validate_delivery_creation,
    validate_delivery_details,
    RequestValidationError
)


class DeliveryCreationValidationTests(SimpleTestCase):

    def setUp(self):
        self.valid_payload = {
            "quote_id": "qt_test_123",
            "vehicle_type": "car",
            "pickup": {"label": "Windsor Store"},
            "dropoff": {"label": "Customer Address"},
            "parcel": {
                "size": "medium",
                "quantity": 1,
            },
        }

    def test_valid_single_delivery(self):
        result = validate_delivery_creation(self.valid_payload)
        self.assertEqual(result, self.valid_payload)

    def test_missing_quote_id(self):
        self.valid_payload.pop("quote_id")

        with self.assertRaises(DeliveryValidationError):
            validate_delivery_creation(self.valid_payload)

    def test_missing_pickup(self):
        self.valid_payload.pop("pickup")

        with self.assertRaises(DeliveryValidationError):
            validate_delivery_creation(self.valid_payload)

    def test_both_dropoff_formats_rejected(self):
        self.valid_payload["dropoffs"] = [
            {"label": "Customer Address"}
        ]

        with self.assertRaises(DeliveryValidationError):
            validate_delivery_creation(self.valid_payload)

    def test_more_than_five_dropoffs_rejected(self):
        self.valid_payload.pop("dropoff")
        self.valid_payload.pop("parcel")
        self.valid_payload["dropoffs"] = [
            {"label": f"Stop {i}"} for i in range(6)
        ]

        with self.assertRaises(DeliveryValidationError):
            validate_delivery_creation(self.valid_payload)

    def test_invalid_scheduled_at_rejected(self):
        self.valid_payload["scheduled_at"] = "invalid-date"

        with self.assertRaises(DeliveryValidationError):
            validate_delivery_creation(self.valid_payload)

    def test_valid_scheduled_at(self):
        self.valid_payload["scheduled_at"] = "2027-01-15T10:00:00Z"

        result = validate_delivery_creation(self.valid_payload)
        self.assertEqual(result, self.valid_payload)

    # Missing pickup coordinates should be rejected by the validator.
    def test_missing_pickup_coordinates_rejected(self):
        payload = {
            "quote_id": "qt_test_123",
            "vehicle_type": "car",
            "pickup": {
                "label": "Windsor Store",
                "contact": {
                    "name": "Store",
                    "phone_number": "+15195550137",
                    "preference": "pickup",
                },
            },
            "dropoff": {
                "label": "Customer Address",
                "lat": "42.3201",
                "lng": "-83.0187",
                "contact": {
                    "name": "Customer",
                    "phone_number": "+15195550188",
                    "preference": "meet_at_door",
                },
            },
            "parcel": {
                "size": "medium",
                "quantity": 1,
            },
        }

        validate_delivery_creation(payload)

        with self.assertRaises(RequestValidationError):
            validate_delivery_details(payload)

    # coordinates that are present but invalid.
    def test_invalid_pickup_latitude_rejected(self):
        payload = {
            "quote_id": "qt_test_123",
            "vehicle_type": "car",
            "pickup": {
                "label": "Windsor Store",
                "lat": "95.0",
                "lng": "-83.0364",
                "contact": {
                    "name": "Store",
                    "phone_number": "+15195550137",
                    "preference": "pickup",
                },
            },
            "dropoff": {
                "label": "Customer Address",
                "lat": "42.3201",
                "lng": "-83.0187",
                "contact": {
                    "name": "Customer",
                    "phone_number": "+15195550188",
                    "preference": "meet_at_door",
                },
            },
            "parcel": {
                "size": "medium",
                "quantity": 1,
            },
        }

        validate_delivery_creation(payload)

        with self.assertRaises(RequestValidationError):
            validate_delivery_details(payload)


    # Missing pickup contact information should be rejected by the validator.
    def test_missing_pickup_contact_rejected(self):
        payload = {
            "quote_id": "qt_test_123",
            "vehicle_type": "car",
            "pickup": {
                "label": "Windsor Store",
                "lat": "42.3149",
                "lng": "-83.0364",
            },
            "dropoff": {
                "label": "Customer Address",
                "lat": "42.3201",
                "lng": "-83.0187",
                "contact": {
                    "name": "Customer",
                    "phone_number": "+15195550188",
                    "preference": "meet_at_door",
                },
            },
            "parcel": {
                "size": "medium",
                "quantity": 1,
            },
        }

        validate_delivery_creation(payload)

        with self.assertRaises(RequestValidationError):
            validate_delivery_details(payload)

    def test_complete_valid_delivery_details(self):
        payload = {
            "quote_id": "qt_test_123",
            "vehicle_type": "car",
            "pickup": {
                "label": "Windsor Store",
                "lat": "42.3149",
                "lng": "-83.0364",
                "contact": {
                    "name": "Store",
                    "phone_number": "+15195550137",
                    "preference": "pickup",
                },
            },
            "dropoff": {
                "label": "Customer Address",
                "lat": "42.3201",
                "lng": "-83.0187",
                "contact": {
                    "name": "Customer",
                    "phone_number": "+15195550188",
                    "preference": "meet_at_door",
                },
            },
            "parcel": {
                "size": "medium",
                "quantity": 1,
            },
        }

        validate_delivery_creation(payload)
        validate_delivery_details(payload)