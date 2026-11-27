"""Tests for persistent dashboard notifications and recipient isolation."""

import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase
from django.urls import reverse

from developer.models import ApiKey, Notification
from developer.services.notifications import (
    create_notification,
    notify_administrator,
)


class NotificationTests(TransactionTestCase):
    """Verify notification storage, access control and event integration."""

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_user(
            username="notification_admin",
            password="Test-password-123!",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        self.other_admin = User.objects.create_user(
            username="notification_other_admin",
            password="Test-password-123!",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        self.business_user = User.objects.create_user(
            username="notification_business",
            password="Test-password-123!",
            is_active=True,
        )

        self.owner_id = uuid.uuid4()
        self.other_owner_id = uuid.uuid4()

        self.key = ApiKey.objects.create(
            business_owner_id=self.owner_id,
            created_by_id=self.owner_id,
            name="Notification test key",
            environment="test",
            key_prefix="aer_test_notification",
            key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            scopes=["quotes:read"],
            status="active",
        )

        self.notifications_url = (
            "/dashboard-api/dashboard/notifications/"
        )

        self.read_all_url = (
            f"{self.notifications_url}read-all/"
        )

        self.revoke_url = reverse(
            "admin-revoke-key",
            kwargs={
                "business_owner_id": self.owner_id,
                "api_key_id": self.key.id,
            },
        )

        self.access_url = reverse(
            "admin-business-api-access",
            kwargs={"business_owner_id": self.owner_id},
        )

    def create_business_notification(self, owner_id=None):
        """Create a notification for the selected business."""
        return create_notification(
            business_owner_id=owner_id or self.owner_id,
            event_type="test.business",
            title="Business notification",
            message="Business notification test.",
            level="success",
        )

    def create_admin_notification(self, admin=None):
        """Create a notification for the selected administrator."""
        return notify_administrator(
            admin_user_id=(admin or self.admin).pk,
            event_type="test.admin",
            title="Administrator notification",
            message="Administrator notification test.",
            level="info",
        )

    def read_url(self, notification):
        return f"{self.notifications_url}{notification.id}/read/"

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type="application/json",
        )

    def patch_access(self, payload):
        return self.client.patch(
            self.access_url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def assert_event_pair(self, event_type, level):
        """Verify that an event produces one record per recipient."""
        records = Notification.objects.filter(
            event_type=event_type,
        )

        self.assertEqual(records.count(), 2)

        business_notification = records.get(
            business_owner_id=self.owner_id,
        )

        admin_notification = records.get(
            admin_user_id=str(self.admin.pk),
        )

        self.assertIsNone(business_notification.admin_user_id)
        self.assertIsNone(admin_notification.business_owner_id)

        self.assertEqual(business_notification.level, level)
        self.assertEqual(admin_notification.level, level)

        self.assertFalse(business_notification.is_read)
        self.assertFalse(admin_notification.is_read)

    # Notification storage

    def test_create_business_notification(self):
        notification = self.create_business_notification()

        notification.refresh_from_db()

        self.assertEqual(
            notification.business_owner_id,
            self.owner_id,
        )
        self.assertIsNone(notification.admin_user_id)
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        self.assertIsNotNone(notification.created_at)

    def test_create_admin_notification(self):
        notification = self.create_admin_notification()

        notification.refresh_from_db()

        self.assertEqual(
            notification.admin_user_id,
            str(self.admin.pk),
        )
        self.assertIsNone(notification.business_owner_id)
        self.assertFalse(notification.is_read)

    def test_notification_requires_recipient(self):
        with self.assertRaises(ValueError):
            create_notification(
                event_type="test.invalid",
                title="Invalid notification",
                message="Missing recipient.",
            )

        self.assertFalse(Notification.objects.exists())

    def test_notification_rejects_multiple_recipients(self):
        with self.assertRaises(ValueError):
            create_notification(
                business_owner_id=self.owner_id,
                admin_user_id=self.admin.pk,
                event_type="test.invalid",
                title="Invalid notification",
                message="Multiple recipients.",
            )

        self.assertFalse(Notification.objects.exists())

    # Authentication and recipient isolation

    def test_anonymous_user_cannot_access_notifications(self):
        notification = self.create_admin_notification()

        self.assertEqual(
            self.client.get(self.notifications_url).status_code,
            401,
        )

        self.assertEqual(
            self.post_json(self.read_url(notification)).status_code,
            401,
        )

        self.assertEqual(
            self.post_json(self.read_all_url).status_code,
            401,
        )

    def test_admin_receives_only_own_notifications(self):
        own = self.create_admin_notification()

        self.create_admin_notification(self.other_admin)
        self.create_business_notification()

        self.client.force_login(self.admin)

        response = self.client.get(self.notifications_url)

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["unread_count"], 1)
        self.assertEqual(
            [item["id"] for item in body["notifications"]],
            [str(own.id)],
        )

    def test_business_receives_only_own_notifications(self):
        own = self.create_business_notification()

        self.create_business_notification(self.other_owner_id)
        self.create_admin_notification()

        self.client.force_login(self.business_user)

        # Supply the business identity independently of account provisioning.
        with patch(
            "developer.notification_views.get_dashboard_identity",
            return_value={
                "role": "business",
                "business_owner_id": self.owner_id,
            },
        ):
            response = self.client.get(self.notifications_url)

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["unread_count"], 1)
        self.assertEqual(
            [item["id"] for item in body["notifications"]],
            [str(own.id)],
        )

    def test_admin_cannot_read_another_recipients_notification(self):
        business_notification = self.create_business_notification()
        other_notification = self.create_admin_notification(
            self.other_admin,
        )

        self.client.force_login(self.admin)

        for notification in (
            business_notification,
            other_notification,
        ):
            with self.subTest(notification=notification.id):
                response = self.post_json(
                    self.read_url(notification),
                )

                self.assertEqual(response.status_code, 404)

                notification.refresh_from_db()
                self.assertFalse(notification.is_read)

    def test_business_cannot_read_another_recipients_notification(self):
        other_business = self.create_business_notification(
            self.other_owner_id,
        )
        admin_notification = self.create_admin_notification()

        self.client.force_login(self.business_user)

        with patch(
            "developer.notification_views.get_dashboard_identity",
            return_value={
                "role": "business",
                "business_owner_id": self.owner_id,
            },
        ):
            for notification in (
                other_business,
                admin_notification,
            ):
                with self.subTest(notification=notification.id):
                    response = self.post_json(
                        self.read_url(notification),
                    )

                    self.assertEqual(response.status_code, 404)

                    notification.refresh_from_db()
                    self.assertFalse(notification.is_read)

    # Read status and unread counts

    def test_mark_notification_read(self):
        notification = self.create_admin_notification()

        self.client.force_login(self.admin)

        response = self.post_json(self.read_url(notification))

        self.assertEqual(response.status_code, 200)

        notification.refresh_from_db()

        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

        response = self.client.get(self.notifications_url)

        self.assertEqual(response.json()["unread_count"], 0)
        self.assertTrue(
            response.json()["notifications"][0]["is_read"],
        )

    def test_repeated_read_preserves_original_timestamp(self):
        notification = self.create_admin_notification()

        self.client.force_login(self.admin)

        self.assertEqual(
            self.post_json(self.read_url(notification)).status_code,
            200,
        )

        notification.refresh_from_db()
        original_read_at = notification.read_at

        self.assertEqual(
            self.post_json(self.read_url(notification)).status_code,
            200,
        )

        notification.refresh_from_db()

        self.assertEqual(notification.read_at, original_read_at)

    def test_admin_mark_all_read_respects_recipient_isolation(self):
        first = self.create_admin_notification()
        second = self.create_admin_notification()

        other_admin = self.create_admin_notification(
            self.other_admin,
        )
        business = self.create_business_notification()

        self.client.force_login(self.admin)

        response = self.post_json(self.read_all_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_count"], 2)

        for notification in (first, second):
            notification.refresh_from_db()
            self.assertTrue(notification.is_read)
            self.assertIsNotNone(notification.read_at)

        for notification in (other_admin, business):
            notification.refresh_from_db()
            self.assertFalse(notification.is_read)

        response = self.client.get(self.notifications_url)

        self.assertEqual(response.json()["unread_count"], 0)

    def test_business_mark_all_read_respects_recipient_isolation(self):
        first = self.create_business_notification()
        second = self.create_business_notification()

        other_business = self.create_business_notification(
            self.other_owner_id,
        )
        admin = self.create_admin_notification()

        self.client.force_login(self.business_user)

        with patch(
            "developer.notification_views.get_dashboard_identity",
            return_value={
                "role": "business",
                "business_owner_id": self.owner_id,
            },
        ):
            response = self.post_json(self.read_all_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_count"], 2)

        for notification in (first, second):
            notification.refresh_from_db()
            self.assertTrue(notification.is_read)

        for notification in (other_business, admin):
            notification.refresh_from_db()
            self.assertFalse(notification.is_read)

    def test_notification_read_requires_csrf(self):
        notification = self.create_admin_notification()

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.post(
            self.read_url(notification),
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    # Automatic event notifications

    def test_admin_revocation_notifies_both_recipients(self):
        self.client.force_login(self.admin)

        response = self.post_json(
            self.revoke_url,
            {"reason": "Notification integration test"},
        )

        self.assertEqual(response.status_code, 200)
        self.assert_event_pair("key.revoked", "warning")

    def test_repeated_revocation_does_not_duplicate_notifications(self):
        self.client.force_login(self.admin)

        self.assertEqual(
            self.post_json(self.revoke_url).status_code,
            200,
        )

        self.assertEqual(
            self.post_json(self.revoke_url).status_code,
            409,
        )

        self.assert_event_pair("key.revoked", "warning")

    def test_failed_revocation_does_not_create_notifications(self):
        self.client.force_login(self.admin)

        response = self.post_json(
            self.revoke_url,
            {"reason": 123},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Notification.objects.exists())

    def test_business_revocation_does_not_notify_admin(self):
        self.client.force_login(self.business_user)

        # Supply the authorized business context and audit identity.
        with (
            patch(
                "developer.views.get_dashboard_identity",
                return_value={
                    "role": "business",
                    "business_owner_id": self.owner_id,
                },
            ),
            patch(
                "developer.views.get_admin_audit_identity",
                return_value=self.owner_id,
            ),
        ):
            response = self.post_json(self.revoke_url)

        self.assertEqual(response.status_code, 200)

        notification = Notification.objects.get(
            event_type="key.revoked",
        )

        self.assertEqual(
            notification.business_owner_id,
            self.owner_id,
        )
        self.assertIsNone(notification.admin_user_id)
        self.assertEqual(notification.level, "warning")
        self.assertEqual(notification.target_id, self.key.id)
        self.assertEqual(Notification.objects.count(), 1)

    def test_disabling_business_access_notifies_both_recipients(self):
        self.client.force_login(self.admin)

        response = self.patch_access({
            "api_access_enabled": False,
        })

        self.assertEqual(response.status_code, 200)
        self.assert_event_pair("business.api_disabled", "warning")

    def test_restoring_business_access_notifies_both_recipients(self):
        self.client.force_login(self.admin)

        self.assertEqual(
            self.patch_access({
                "api_access_enabled": False,
            }).status_code,
            200,
        )

        response = self.patch_access({
            "api_access_enabled": True,
        })

        self.assertEqual(response.status_code, 200)
        self.assert_event_pair("business.api_enabled", "success")

    def test_unchanged_business_access_does_not_duplicate_notifications(self):
        self.client.force_login(self.admin)

        for _ in range(2):
            response = self.patch_access({
                "api_access_enabled": False,
            })

            self.assertEqual(response.status_code, 200)

        self.assert_event_pair("business.api_disabled", "warning")

    def test_rate_limit_update_notifies_both_recipients(self):
        self.client.force_login(self.admin)

        response = self.patch_access({
            "rate_limit_requests_per_minute": 100,
        })

        self.assertEqual(response.status_code, 200)
        self.assert_event_pair("business.limits_updated", "info")

    def test_daily_quota_update_notifies_both_recipients(self):
        self.client.force_login(self.admin)

        response = self.patch_access({
            "daily_creation_quota": 500,
        })

        self.assertEqual(response.status_code, 200)
        self.assert_event_pair("business.limits_updated", "info")

    def test_combined_limit_update_creates_one_notification_per_recipient(self):
        self.client.force_login(self.admin)

        response = self.patch_access({
            "rate_limit_requests_per_minute": 100,
            "daily_creation_quota": 500,
        })

        self.assertEqual(response.status_code, 200)
        self.assert_event_pair("business.limits_updated", "info")

    def test_invalid_business_settings_do_not_create_notifications(self):
        self.client.force_login(self.admin)

        response = self.patch_access({
            "daily_creation_quota": -1,
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Notification.objects.exists())