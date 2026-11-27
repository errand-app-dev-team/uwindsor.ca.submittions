
"""Tests for payment validation and dispatch eligibility."""

from django.test import SimpleTestCase

from aerrands.services.payment_state import (
    PaymentStateError,
    can_dispatch,
    validate_payment_amount,
    validate_payment_result,
)


class PaymentAmountTests(SimpleTestCase):

    def test_valid_amount(self):
        self.assertEqual(
            str(validate_payment_amount("13.62")),
            "13.62",
        )

    def test_zero_amount_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_amount("0")

    def test_negative_amount_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_amount("-5.00")

    def test_invalid_amount_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_amount("invalid")

    def test_excess_decimal_places_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_amount("12.345")


class PaymentResultTests(SimpleTestCase):

    def test_confirmed_payment(self):
        result = validate_payment_result({
            "status": "paid",
            "method": "wallet",
            "reference": "txn_123",
        })

        self.assertEqual(result.status, "paid")
        self.assertEqual(result.method, "wallet")
        self.assertEqual(result.reference, "txn_123")

    def test_unpaid_payment(self):
        result = validate_payment_result({
            "status": "unpaid",
            "method": "wallet",
        })

        self.assertEqual(result.status, "unpaid")

    def test_pending_payment(self):
        result = validate_payment_result({
            "status": "pending",
            "method": "wallet",
        })

        self.assertEqual(result.status, "pending")

    def test_failed_payment(self):
        result = validate_payment_result({
            "status": "failed",
            "method": "wallet",
        })

        self.assertEqual(result.status, "failed")

    def test_paid_without_reference_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_result({
                "status": "paid",
                "method": "wallet",
            })

    def test_unknown_payment_status_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_result({
                "status": "unknown",
                "method": "wallet",
            })

    def test_missing_payment_method_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_result({
                "status": "unpaid",
            })

    def test_invalid_payment_result_rejected(self):
        with self.assertRaises(PaymentStateError):
            validate_payment_result(None)


class DispatchEligibilityTests(SimpleTestCase):

    def test_paid_booking_can_dispatch(self):
        self.assertTrue(can_dispatch("paid"))

    def test_unpaid_booking_cannot_dispatch(self):
        self.assertFalse(can_dispatch("unpaid"))

    def test_pending_booking_cannot_dispatch(self):
        self.assertFalse(can_dispatch("pending"))

    def test_failed_booking_cannot_dispatch(self):
        self.assertFalse(can_dispatch("failed"))

    def test_missing_payment_status_cannot_dispatch(self):
        self.assertFalse(can_dispatch(None))
