from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from aerrands.services.aerrand_service import (
    AerrandContext,
    AerrandServiceError,
    validate_aerrand_context,
    validate_aerrand_id,
    create_aerrand,
    AerrandIntegrationUnavailableError,
    AerrandOutcomeUnknownError,
    build_booking_request,
    verify_booking_quote,
    AerrandValidationError, get_aerrand, get_aerrand_tracking, AerrandConflictError, cancel_aerrand,
    AerrandNotFoundError, get_aerrand_proof, update_aerrand_dropoff,
)

from aerrands.services.aerrand_adapter import (
    AerrandAdapterUnavailable,
    AerrandAdapterOutcomeUnknown, AerrandAdapterConflict, AerrandAdapterNotFound,
)


class AerrandServiceValidationTests(SimpleTestCase):
    def test_rejects_missing_authentication_context(self):
        context = AerrandContext(
            business_owner_id="",
            api_key_id="test_api_key",
            environment="test",
        )

        with self.assertRaises(AerrandServiceError):
            validate_aerrand_context(context)

    def test_rejects_invalid_aerrand_id(self):
        for aerrand_id in ("", "   ", None):
            with self.subTest(aerrand_id=aerrand_id):
                with self.assertRaises(AerrandServiceError):
                    validate_aerrand_id(aerrand_id)



class AerrandCreationIntegrationTests(SimpleTestCase):
    """Verify delivery creation through the production adapter boundary."""

    def setUp(self):
        self.context = AerrandContext(
            business_owner_id="business_123",
            api_key_id="key_123",
            environment="test",
        )

        self.validated_data = {
            "quote_id": "quote_123",
        }

        self.quote = Mock()
        self.quote.id = "quote_123"
        self.quote.total = "24.92"

        self.booking = Mock()
        self.booking.quote_id = "quote_123"

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    @patch("aerrands.services.aerrand_service.verify_booking_quote")
    @patch("aerrands.services.aerrand_service.build_booking_request")
    @patch("aerrands.services.aerrand_service.get_quote_for_aerrand")
    def test_verified_booking_reaches_adapter(
        self,
        mock_get_quote,
        mock_build_booking,
        mock_verify,
        mock_get_adapter,
    ):
        """A verified booking must reach the adapter with partner identity."""

        mock_get_quote.return_value = self.quote
        mock_build_booking.return_value = self.booking

        adapter = Mock()
        adapter.create_booking.return_value = {
            "batch_id": "batch_123",
            "status": "pending_payment",
            "stop_count": 1,
            "stops": [
                {
                    "errand_id": "errand_123",
                    "status": "draft",
                    "price": "24.92",
                }
            ],
        }
        mock_get_adapter.return_value = adapter

        response = create_aerrand(self.validated_data, self.context)

        mock_get_quote.assert_called_once()
        mock_build_booking.assert_called_once_with(self.validated_data)
        mock_verify.assert_called_once_with(self.booking, self.quote)

        adapter.create_booking.assert_called_once()

        args = adapter.create_booking.call_args.args

        self.assertIs(args[0], self.booking)
        self.assertIs(args[1], self.quote)
        self.assertEqual(args[2].business_owner_id, "business_123")
        self.assertEqual(args[2].api_key_id, "key_123")
        self.assertEqual(args[2].environment, "test")

        self.assertEqual(response["status"], "pending_payment")
        self.assertEqual(response["stop_count"], 1)

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    @patch("aerrands.services.aerrand_service.verify_booking_quote")
    @patch("aerrands.services.aerrand_service.build_booking_request")
    @patch("aerrands.services.aerrand_service.get_quote_for_aerrand")
    def test_unavailable_adapter_does_not_create_booking(
        self,
        mock_get_quote,
        mock_build_booking,
        mock_verify,
        mock_get_adapter,
    ):
        """Unavailable integration must produce a service error."""

        mock_get_quote.return_value = self.quote
        mock_build_booking.return_value = self.booking

        adapter = Mock()
        adapter.create_booking.side_effect = AerrandAdapterUnavailable(
            "Aerrand integration is unavailable."
        )
        mock_get_adapter.return_value = adapter

        with self.assertRaises(AerrandIntegrationUnavailableError):
            create_aerrand(self.validated_data, self.context)

        mock_verify.assert_called_once()
        adapter.create_booking.assert_called_once()

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    @patch("aerrands.services.aerrand_service.verify_booking_quote")
    @patch("aerrands.services.aerrand_service.build_booking_request")
    @patch("aerrands.services.aerrand_service.get_quote_for_aerrand")
    def test_unknown_booking_outcome_is_preserved(
        self,
        mock_get_quote,
        mock_build_booking,
        mock_verify,
        mock_get_adapter,
    ):
        """An uncertain backend outcome must not be treated as failure."""

        mock_get_quote.return_value = self.quote
        mock_build_booking.return_value = self.booking

        adapter = Mock()
        adapter.create_booking.side_effect = AerrandAdapterOutcomeUnknown(
            "Booking result could not be confirmed."
        )
        mock_get_adapter.return_value = adapter

        with self.assertRaises(AerrandOutcomeUnknownError):
            create_aerrand(self.validated_data, self.context)

        adapter.create_booking.assert_called_once()

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    def test_retrieve_aerrand_uses_adapter(self, mock_get_adapter):
        adapter = Mock()
        adapter.get_booking.return_value = {
            "errand_id": "errand_123",
            "status": "in_transit",
        }
        mock_get_adapter.return_value = adapter

        context = Mock()
        context.business_owner_id = "business_123"
        context.api_key_id = "key_123"
        context.environment = "test"

        result = get_aerrand("errand_123", context)

        self.assertEqual(result["status"], "in_transit")
        adapter.get_booking.assert_called_once()

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    def test_tracking_retrieval_uses_adapter(self, mock_get_adapter):
        adapter = Mock()
        adapter.get_tracking.return_value = {
            "errand_id": "errand_123",
            "status": "in_transit",
            "driver_location": {
                "lat": 42.3110,
                "lng": -83.0250,
            },
        }
        mock_get_adapter.return_value = adapter

        context = Mock()
        context.business_owner_id = "business_123"
        context.api_key_id = "key_123"
        context.environment = "test"

        result = get_aerrand_tracking("errand_123", context)

        self.assertEqual(result["status"], "in_transit")
        self.assertEqual(result["driver_location"]["lat"], 42.3110)
        adapter.get_tracking.assert_called_once()

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    def test_retrieve_proof_uses_adapter(self, mock_get_adapter):
        adapter = Mock()
        adapter.get_proof.return_value = {
            "errand_id": "errand_123",
            "status": "delivered",
            "proof_of_delivery": {
                "photo_url": "https://example.com/proof.jpg",
            },
        }
        mock_get_adapter.return_value = adapter

        context = AerrandContext(
            business_owner_id="business_123",
            api_key_id="key_123",
            environment="test",
        )

        result = get_aerrand_proof("errand_123", context)

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(
            result["proof_of_delivery"]["photo_url"],
            "https://example.com/proof.jpg",
        )

        adapter.get_proof.assert_called_once()
        args = adapter.get_proof.call_args.args

        self.assertEqual(args[0], "errand_123")
        self.assertEqual(args[1].business_owner_id, "business_123")

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    def test_retrieve_proof_rejects_missing_delivery(self, mock_get_adapter):
        adapter = Mock()
        adapter.get_proof.side_effect = AerrandAdapterNotFound(
            "Delivery not found."
        )
        mock_get_adapter.return_value = adapter

        context = AerrandContext(
            business_owner_id="business_123",
            api_key_id="key_123",
            environment="test",
        )

        with self.assertRaises(AerrandNotFoundError):
            get_aerrand_proof("errand_123", context)

        adapter.get_proof.assert_called_once()

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    def test_update_dropoff_uses_adapter(self, mock_get_adapter):
        adapter = Mock()
        adapter.update_dropoff.return_value = {
            "status": True,
            "message": "Dropoff instruction updated",
        }
        mock_get_adapter.return_value = adapter

        context = AerrandContext(
            business_owner_id="business_123",
            api_key_id="key_123",
            environment="test",
        )

        changes = {
            "instructions": "Leave with concierge.",
            "preference": "leave_at_door",
        }

        result = update_aerrand_dropoff(
            "errand_123",
            "stop_456",
            changes,
            context,
        )

        self.assertTrue(result["status"])

        args = adapter.update_dropoff.call_args.args
        self.assertEqual(args[0], "errand_123")
        self.assertEqual(args[1], "stop_456")
        self.assertEqual(args[2], changes)
        self.assertEqual(args[3].business_owner_id, context.business_owner_id)
        self.assertEqual(args[3].api_key_id, context.api_key_id)
        self.assertEqual(args[3].environment, context.environment)

        adapter.update_dropoff.assert_called_once()

    @patch("aerrands.services.aerrand_service.get_aerrand_adapter")
    def test_update_dropoff_preserves_conflict(self, mock_get_adapter):
        adapter = Mock()
        adapter.update_dropoff.side_effect = AerrandAdapterConflict(
            "Drop-off editing window is closed."
        )
        mock_get_adapter.return_value = adapter

        context = AerrandContext(
            business_owner_id="business_123",
            api_key_id="key_123",
            environment="test",
        )

        with self.assertRaises(AerrandConflictError):
            update_aerrand_dropoff(
                "errand_123",
                "stop_456",
                {"instructions": "Updated instructions"},
                context,
            )
        adapter.update_dropoff.assert_called_once()



class BookingQuoteMatchingTests(SimpleTestCase):
    """Verify booking inputs against the original quote."""

    def setUp(self):
        self.pickup = {
            "label": "Windsor Store",
            "lat": "42.3149",
            "lng": "-83.0364",
        }

        self.dropoff = {
            "label": "Customer Address",
            "lat": "42.3201",
            "lng": "-83.0187",
        }

    def make_quote(self, stops):
        quote = Mock()
        quote.total = "24.92"
        quote.inputs = {
            "pickup": {
                "lat": 42.3149,
                "lng": -83.0364,
            },
            "stops": stops,
        }
        return quote

    def test_single_stop_parcel_matches_original_quote(self):
        payload = {
            "quote_id": "quote_123",
            "vehicle_type": "car",
            "pickup": self.pickup,
            "dropoff": self.dropoff,
            "parcel": {
                "size": "medium",
                "quantity": 1,
            },
        }

        booking = build_booking_request(payload)
        quote = self.make_quote([
            {
                "lat": 42.3201,
                "lng": -83.0187,
                "parcels": {"medium": 1},
            }
        ])

        self.assertEqual(len(booking.dropoffs), 1)

        self.assertEqual(
            booking.dropoffs[0]["parcels"],
            {"medium": 1},
        )
        self.assertTrue(verify_booking_quote(booking, quote))

    def test_multi_stop_parcels_match_original_quote(self):
        payload = {
            "quote_id": "quote_123",
            "vehicle_type": "car",
            "pickup": self.pickup,
            "dropoffs": [
                {
                    **self.dropoff,
                    "parcels": {"small": 2},
                },
                {
                    "label": "Second Customer",
                    "lat": "42.3300",
                    "lng": "-83.0200",
                    "parcels": {"medium": 1},
                },
            ],
        }

        booking = build_booking_request(payload)
        quote = self.make_quote([
            {
                "lat": 42.3201,
                "lng": -83.0187,
                "parcels": {"small": 2},
            },
            {
                "lat": 42.3300,
                "lng": -83.0200,
                "parcels": {"medium": 1},
            },
        ])

        self.assertEqual(len(booking.dropoffs), 2)
        self.assertTrue(verify_booking_quote(booking, quote))

    def test_booking_preserves_external_reference(self):
        payload = {
            "quote_id": "quote_123",
            "vehicle_type": "car",
            "reference": "SHOP-10432",
            "pickup": self.pickup,
            "dropoff": self.dropoff,
        }

        booking = build_booking_request(payload)

        self.assertEqual(
            booking.external_reference,
            "SHOP-10432",
        )

    def test_booking_rejects_total_above_maximum(self):
        payload = {
            "quote_id": "quote_123",
            "vehicle_type": "car",
            "pickup": self.pickup,
            "dropoff": self.dropoff,
            "max_total": "20.00",
        }

        booking = build_booking_request(payload)

        quote = self.make_quote([
            {
                "lat": 42.3201,
                "lng": -83.0187,
            }
        ])

        # The quote total is 24.92, exceeding the allowed 20.00.
        with self.assertRaises(AerrandValidationError):
            verify_booking_quote(booking, quote)

    def test_booking_rejects_location_mismatch(self):
        payload = {
            "quote_id": "quote_123",
            "vehicle_type": "car",
            "pickup": self.pickup,
            "dropoff": {
                **self.dropoff,
                "lat": "42.3500",
                "lng": "-83.0187",
            },
        }

        booking = build_booking_request(payload)

        quote = self.make_quote([
            {
                "lat": 42.3201,
                "lng": -83.0187,
            }
        ])

        # The delivery location must match the original quote.
        with self.assertRaises(AerrandValidationError):
            verify_booking_quote(booking, quote)

    def test_booking_rejects_invalid_maximum_total(self):
        payload = {
            "quote_id": "quote_123",
            "vehicle_type": "car",
            "pickup": self.pickup,
            "dropoff": self.dropoff,
            "max_total": "invalid_amount",
        }

        booking = build_booking_request(payload)

        quote = self.make_quote([
            {
                "lat": 42.3201,
                "lng": -83.0187,
            }
        ])

        # A non-numeric maximum total must not be accepted.
        with self.assertRaises(AerrandValidationError):
            verify_booking_quote(booking, quote)



@patch("aerrands.services.aerrand_service.get_aerrand_adapter")
def test_cancel_aerrand_uses_adapter(self, mock_get_adapter):
    adapter = Mock()
    adapter.cancel_booking.return_value = {
        "errand_id": "errand_123",
        "status": "cancelled",
    }
    mock_get_adapter.return_value = adapter

    context = AerrandContext(
        business_owner_id="business_123",
        api_key_id="key_123",
        environment="test",
    )

    result = cancel_aerrand("errand_123", context)

    self.assertEqual(result["status"], "cancelled")
    adapter.cancel_booking.assert_called_once()

    args = adapter.cancel_booking.call_args.args

    self.assertEqual(args[0], "errand_123")
    self.assertEqual(args[1].business_owner_id, "business_123")


@patch("aerrands.services.aerrand_service.get_aerrand_adapter")
def test_cancel_aerrand_preserves_conflict(self, mock_get_adapter):
    adapter = Mock()
    adapter.cancel_booking.side_effect = AerrandAdapterConflict(
        "This delivery cannot be cancelled."
    )
    mock_get_adapter.return_value = adapter

    context = AerrandContext(
        business_owner_id="business_123",
        api_key_id="key_123",
        environment="test",
    )

    with self.assertRaises(AerrandConflictError):
        cancel_aerrand("errand_123", context)

    adapter.cancel_booking.assert_called_once()