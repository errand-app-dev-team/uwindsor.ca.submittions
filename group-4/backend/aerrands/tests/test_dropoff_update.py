
"""Tests for forwarding delivery drop-off updates to the service layer."""

import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from aerrands import views


class DropoffUpdateTests(SimpleTestCase):
    """Verify that drop-off updates preserve delivery and stop identifiers."""

    def setUp(self):
        self.factory = RequestFactory()
        self.aerrand_id = "delivery-123"
        self.stop_id = "stop-456"
        self.changes = {"instructions": "Leave at reception"}

    @patch.object(views, "update_aerrand_dropoff_service")
    @patch.object(views, "get_authenticated_context")
    @patch.object(views, "validate_dropoff_update")
    def test_dropoff_update_passes_correct_arguments(
        self,
        mock_validate,
        mock_context,
        mock_service,
    ):
        """Forward validated changes and the authenticated business context."""
        context = object()
        mock_context.return_value = context
        mock_validate.return_value = self.changes
        mock_service.return_value = {
            "id": self.stop_id,
            "instructions": self.changes["instructions"],
        }

        request = self.factory.patch(
            f"/v1/errands/{self.aerrand_id}/dropoff/{self.stop_id}",
            data=json.dumps(self.changes),
            content_type="application/json",
        )

        response = views.update_aerrand_dropoff(
            request,
            aerrand_id=self.aerrand_id,
            stop_id=self.stop_id,
        )

        self.assertEqual(response.status_code, 200)
        mock_validate.assert_called_once_with(self.changes)

        mock_service.assert_called_once_with(
            aerrand_id=self.aerrand_id,
            stop_id=self.stop_id,
            changes=self.changes,
            context=context,
        )
