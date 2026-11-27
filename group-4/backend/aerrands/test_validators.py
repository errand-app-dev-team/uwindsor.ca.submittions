from django.test import SimpleTestCase

from aerrands.validators import (
    RequestValidationError,
    validate_aerrand_request,
    validate_quote_request,
    validate_pagination_limit,
    validate_pagination_cursor,
)


def make_stop(n):
    return {"address": f"{n} Main St", "parcels": {"small": 1}}


def quote_payload(stop_count):
    return {
        "pickup": {"address": "1 Pickup St"},
        "stops": [make_stop(i) for i in range(stop_count)],
    }


def aerrand_payload(stop_count):
    data = quote_payload(stop_count)
    data["quote_id"] = "q_123"
    return data


class StackingLimitTests(SimpleTestCase):
    def test_quote_accepts_one_to_five_stops(self):
        for n in (1, 5):
            validate_quote_request(quote_payload(n))

    def test_quote_rejects_zero_or_six_stops(self):
        for n in (0, 6):
            with self.assertRaises(RequestValidationError):
                validate_quote_request(quote_payload(n))

    def test_aerrand_accepts_one_to_five_stops(self):
        for n in (1, 5):
            validate_aerrand_request(aerrand_payload(n))

    def test_aerrand_rejects_zero_or_six_stops(self):
        for n in (0, 6):
            with self.assertRaises(RequestValidationError):
                validate_aerrand_request(aerrand_payload(n))


class AerrandRequestTests(SimpleTestCase):
    def test_requires_quote_id(self):
        data = aerrand_payload(1)
        del data["quote_id"]
        with self.assertRaises(RequestValidationError):
            validate_aerrand_request(data)

    def test_rejects_unknown_parcel_size(self):
        data = quote_payload(1)
        data["stops"][0]["parcels"] = {"huge": 1}
        with self.assertRaises(RequestValidationError):
            validate_quote_request(data)

    def test_rejects_invalid_payment_mode(self):
        data = aerrand_payload(1)
        data["payment"] = {"mode": "cash"}
        with self.assertRaises(RequestValidationError):
            validate_aerrand_request(data)

class PaginationValidationTests(SimpleTestCase):

    def test_pagination_limit_accepts_valid_values(self):
        self.assertEqual(validate_pagination_limit("25"), 25)
        self.assertEqual(validate_pagination_limit("100"), 100)

    def test_pagination_limit_rejects_invalid_values(self):
        for value in ("0", "101", "abc", "2.5", ""):
            with self.subTest(value=value):
                with self.assertRaises(RequestValidationError):
                    validate_pagination_limit(value)

    def test_pagination_cursor_accepts_valid_values(self):
        self.assertIsNone(validate_pagination_cursor(None))
        self.assertEqual(
            validate_pagination_cursor("opaque_token_123"),
            "opaque_token_123",
        )

    def test_pagination_cursor_rejects_invalid_values(self):
        for value in ("", "   ", 123):
            with self.subTest(value=value):
                with self.assertRaises(RequestValidationError):
                    validate_pagination_cursor(value)