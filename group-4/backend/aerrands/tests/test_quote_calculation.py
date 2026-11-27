
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings

from aerrands.services.demo_quote_service import (
    calculate_demo_quote,
    calculate_distance_km,
)
from aerrands.services.quote_service import (
    QuoteContext,
    QuoteIntegrationUnavailableError,
    QuoteServiceError,
    create_quote,
    get_quote,
)


class QuoteCalculationTests(SimpleTestCase):
    def setUp(self):
        self.quote_data = {
            "pickup": {"lat": 42.3043, "lng": -83.0660},
            "stops": [
                {
                    "lat": 42.3174,
                    "lng": -83.0388,
                    "parcels": {"small": 1, "medium": 2},
                }
            ],
        }

    def test_distance_between_identical_coordinates_is_zero(self):
        location = {"lat": 42.3043, "lng": -83.0660}

        distance = calculate_distance_km(location, location)

        self.assertEqual(distance, 0.0)

    def test_distance_between_different_coordinates(self):
        distance = calculate_distance_km(
            self.quote_data["pickup"],
            self.quote_data["stops"][0],
        )

        # Verify the Haversine calculation against the expected route distance.
        self.assertAlmostEqual(distance, 2.67, places=2)

    def test_calculate_quote_returns_expected_pricing(self):
        result = calculate_demo_quote(self.quote_data)

        # Pricing combines the base fare, distance charge, and parcel fees.
        self.assertEqual(result["route_km"], Decimal("2.67"))
        self.assertEqual(result["breakdown"]["base_fare"], "5.00")
        self.assertEqual(result["breakdown"]["distance_fee"], "4.01")
        self.assertEqual(result["breakdown"]["parcel_fee"], "5.00")
        self.assertEqual(result["total"], Decimal("14.01"))

    def test_calculate_quote_identifies_simulated_pricing(self):
        result = calculate_demo_quote(self.quote_data)

        # The response must distinguish simulated pricing from platform pricing.
        self.assertEqual(
            result["breakdown"]["pricing_source"],
            "demo_simulation",
        )
        self.assertEqual(
            result["breakdown"]["distance_type"],
            "straight_line",
        )
        self.assertEqual(result["breakdown"]["currency"], "CAD")

    def test_calculate_quote_returns_resolved_stops(self):
        result = calculate_demo_quote(self.quote_data)

        self.assertEqual(
            result["resolved_stops"],
            [{"lat": 42.3174, "lng": -83.0388}],
        )

    def test_calculate_quote_rejects_address_only_locations(self):
        quote_data = {
            "pickup": {"address": "1 Pickup St"},
            "stops": [
                {
                    "address": "2 Delivery St",
                    "parcels": {"small": 1},
                }
            ],
        }

        # Coordinate-based calculations cannot resolve street addresses.
        with self.assertRaises(ValueError):
            calculate_demo_quote(quote_data)


class QuoteCreationTests(TestCase):
    def setUp(self):
        self.context = QuoteContext(
            business_owner_id="test_business",
            api_key_id="test_api_key",
            environment="test",
        )

        self.quote_data = {
            "pickup": {"lat": 42.3043, "lng": -83.0660},
            "stops": [
                {
                    "lat": 42.3174,
                    "lng": -83.0388,
                    "parcels": {"small": 1, "medium": 2},
                }
            ],
        }

    @override_settings(DEBUG=True, ENABLE_DEMO_QUOTES=True)
    def test_create_quote_saves_calculated_quote(self):
        quote = create_quote(self.quote_data, self.context)

        # Confirm that calculated pricing is persisted for the owning API key.
        retrieved_quote = get_quote(quote.id, self.context)

        self.assertTrue(quote.id.startswith("qt_"))
        self.assertEqual(retrieved_quote.total, "14.01")
        self.assertEqual(retrieved_quote.route_km, Decimal("2.67"))
        self.assertEqual(
            retrieved_quote.breakdown["pricing_source"],
            "demo_simulation",
        )

    @override_settings(DEBUG=True, ENABLE_DEMO_QUOTES=True)
    def test_create_quote_rejects_live_environment(self):
        live_context = QuoteContext(
            business_owner_id="test_business",
            api_key_id="live_api_key",
            environment="live",
        )

        # Simulated pricing must never be used for live API requests.
        with self.assertRaises(QuoteIntegrationUnavailableError):
            create_quote(self.quote_data, live_context)

    @override_settings(DEBUG=True, ENABLE_DEMO_QUOTES=False)
    def test_create_quote_rejects_disabled_simulation(self):
        # Disabling simulated pricing requires the real pricing integration.
        with self.assertRaises(QuoteIntegrationUnavailableError):
            create_quote(self.quote_data, self.context)

    @override_settings(DEBUG=False, ENABLE_DEMO_QUOTES=True)
    def test_create_quote_rejects_production_mode(self):
        # The simulation flag alone must not enable pricing in production.
        with self.assertRaises(QuoteIntegrationUnavailableError):
            create_quote(self.quote_data, self.context)

    @override_settings(DEBUG=True, ENABLE_DEMO_QUOTES=True)
    def test_create_quote_rejects_missing_coordinates(self):
        quote_data = {
            "pickup": {"address": "1 Pickup St"},
            "stops": [
                {
                    "address": "2 Delivery St",
                    "parcels": {"small": 1},
                }
            ],
        }

        # Unsupported address-only requests must fail without saving a quote.
        with self.assertRaises(QuoteServiceError):
            create_quote(quote_data, self.context)
