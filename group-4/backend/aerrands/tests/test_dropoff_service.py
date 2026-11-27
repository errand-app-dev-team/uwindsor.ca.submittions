
"""Regression tests for drop-off service argument forwarding."""

from unittest.mock import patch, sentinel

from django.test import SimpleTestCase

from aerrands.services import aerrand_service


class DropoffServiceTests(SimpleTestCase):

    @patch.object(aerrand_service, "call_aerrand_adapter")
    @patch.object(aerrand_service, "get_partner_identity")
    @patch.object(aerrand_service, "get_aerrand_adapter")
    @patch.object(aerrand_service, "validate_aerrand_id")
    @patch.object(aerrand_service, "validate_aerrand_context")
    def test_update_dropoff_forwards_stop_id(
        self,
        mock_validate_context,
        mock_validate_id,
        mock_get_adapter,
        mock_get_identity,
        mock_call_adapter,
    ):
        """Ensure the service forwards the stop ID to the adapter."""
        adapter = mock_get_adapter.return_value
        mock_get_identity.return_value = sentinel.partner
        mock_call_adapter.return_value = {"status": "updated"}

        changes = {"instructions": "Leave at reception"}

        result = aerrand_service.update_aerrand_dropoff(
            aerrand_id="delivery-123",
            stop_id="stop-456",
            changes=changes,
            context=sentinel.context,
        )

        mock_call_adapter.assert_called_once_with(
            adapter.update_dropoff,
            "delivery-123",
            "stop-456",
            changes,
            sentinel.partner,
        )

        self.assertEqual(result, {"status": "updated"})
