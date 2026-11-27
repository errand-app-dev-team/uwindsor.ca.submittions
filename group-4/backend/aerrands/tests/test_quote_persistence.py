
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from aerrands.models import ApiQuote
from aerrands.services.quote_service import (
    QuoteAccessError,
    QuoteContext,
    QuoteExpiredError,
    get_quote,
    save_quote,
)
from aerrands.services.aerrand_service import (
    AerrandContext,
    QuoteAccessError as AerrandQuoteAccessError,
    QuoteNotFoundError as AerrandQuoteNotFoundError,
    QuoteExpiredError as AerrandQuoteExpiredError,
    get_quote_for_aerrand,
)


class QuotePersistenceTests(TestCase):
    def setUp(self):
        self.context = QuoteContext(
            business_owner_id="test_business",
            api_key_id="test_api_key",
            environment="test",
        )

        self.quote_data = {
            "pickup": {"address": "1 Pickup St"},
            "stops": [
                {
                    "address": "2 Delivery St",
                    "parcels": {"small": 1},
                }
            ],
        }

    def create_saved_quote(self):
        """Create a quote with consistent data for persistence tests."""
        return save_quote(
            validated_data=self.quote_data,
            context=self.context,
            route_km=Decimal("5.50"),
            breakdown={"distance_charge": "10.00"},
            total=Decimal("10.00"),
            resolved_stops=[],
        )

    def test_save_quote_creates_database_record(self):
        quote = self.create_saved_quote()
        saved_quote = ApiQuote.objects.get(pk=quote.id)

        self.assertTrue(quote.id.startswith("qt_"))
        self.assertEqual(saved_quote.business_owner_id, "test_business")
        self.assertEqual(saved_quote.api_key_id, "test_api_key")
        self.assertEqual(saved_quote.environment, "test")
        self.assertEqual(saved_quote.total, "10.00")
        self.assertEqual(saved_quote.route_km, Decimal("5.50"))

    def test_get_quote_returns_saved_quote(self):
        quote = self.create_saved_quote()
        retrieved_quote = get_quote(quote.id, self.context)

        self.assertEqual(retrieved_quote.id, quote.id)
        self.assertEqual(
            retrieved_quote.business_owner_id,
            self.context.business_owner_id,
        )
        self.assertEqual(
            retrieved_quote.api_key_id,
            self.context.api_key_id,
        )
        self.assertEqual(
            retrieved_quote.environment,
            self.context.environment,
        )

    def test_get_quote_rejects_different_business(self):
        quote = self.create_saved_quote()

        other_context = QuoteContext(
            business_owner_id="another_business",
            api_key_id=self.context.api_key_id,
            environment=self.context.environment,
        )

        with self.assertRaises(QuoteAccessError):
            get_quote(quote.id, other_context)

    def test_get_quote_rejects_different_api_key(self):
        quote = self.create_saved_quote()

        other_context = QuoteContext(
            business_owner_id=self.context.business_owner_id,
            api_key_id="another_api_key",
            environment=self.context.environment,
        )

        with self.assertRaises(QuoteAccessError):
            get_quote(quote.id, other_context)

    def test_get_quote_rejects_different_environment(self):
        quote = self.create_saved_quote()

        live_context = QuoteContext(
            business_owner_id=self.context.business_owner_id,
            api_key_id=self.context.api_key_id,
            environment="live",
        )

        with self.assertRaises(QuoteAccessError):
            get_quote(quote.id, live_context)

    def test_get_quote_rejects_expired_quote(self):
        quote = self.create_saved_quote()

        ApiQuote.objects.filter(pk=quote.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        with self.assertRaises(QuoteExpiredError):
            get_quote(quote.id, self.context)

    def test_get_quote_for_aerrand_returns_valid_quote(self):
        quote = self.create_saved_quote()

        aerrand_context = AerrandContext(
            business_owner_id=self.context.business_owner_id,
            api_key_id=self.context.api_key_id,
            environment=self.context.environment,
        )

        retrieved_quote = get_quote_for_aerrand(
            quote.id,
            aerrand_context,
        )

        self.assertEqual(retrieved_quote.id, quote.id)

    def test_get_quote_for_aerrand_rejects_different_business(self):
        quote = self.create_saved_quote()

        other_context = AerrandContext(
            business_owner_id="another_business",
            api_key_id=self.context.api_key_id,
            environment=self.context.environment,
        )

        with self.assertRaises(AerrandQuoteAccessError):
            get_quote_for_aerrand(quote.id, other_context)

    def test_get_quote_for_aerrand_rejects_missing_quote(self):
        context = AerrandContext(
            business_owner_id=self.context.business_owner_id,
            api_key_id=self.context.api_key_id,
            environment=self.context.environment,
        )

        with self.assertRaises(AerrandQuoteNotFoundError):
            get_quote_for_aerrand("qt_nonexistent", context)

    def test_get_quote_for_aerrand_rejects_expired_quote(self):
        quote = self.create_saved_quote()

        context = AerrandContext(
            business_owner_id=self.context.business_owner_id,
            api_key_id=self.context.api_key_id,
            environment=self.context.environment,
        )

        ApiQuote.objects.filter(pk=quote.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        with self.assertRaises(AerrandQuoteExpiredError):
            get_quote_for_aerrand(quote.id, context)
