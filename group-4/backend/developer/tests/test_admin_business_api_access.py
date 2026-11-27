import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import Client, RequestFactory, TransactionTestCase
from django.urls import reverse

from developer.rate_limit_middleware import ApiRateLimitMiddleware
from developer.models import (
    AdminAuditIdentity,
    ApiAuditLog,
    ApiKey,
    BusinessApiAccess,
)


class AdminBusinessApiAccessTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_user(
            username="business_access_admin",
            email="admin@example.com",
            password="Test-password-123!",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        self.staff = User.objects.create_user(
            username="business_access_staff",
            password="Test-password-123!",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )

        self.owner_id = uuid.uuid4()
        self.key = ApiKey.objects.create(
            business_owner_id=self.owner_id,
            created_by_id=self.owner_id,
            name="Business access endpoint test",
            environment="test",
            key_prefix="aer_test_example",
            key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            scopes=["quotes:read"],
            status="active",
        )

        self.url = reverse(
            "admin-business-api-access",
            kwargs={"business_owner_id": self.owner_id},
        )

    def update_access(self, enabled=False, **extra):
        return self.client.patch(
            self.url,
            data=json.dumps({
                "api_access_enabled": enabled,
                **extra,
            }),
            content_type="application/json",
        )

    def assert_no_changes(self):
        self.assertFalse(BusinessApiAccess.objects.exists())
        self.assertFalse(ApiAuditLog.objects.exists())
        self.assertFalse(AdminAuditIdentity.objects.exists())
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, "active")

    def test_anonymous_user_is_rejected(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.update_access().status_code, 401)
        self.assert_no_changes()

    def test_staff_without_superuser_permission_is_rejected(self):
        self.client.force_login(self.staff)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.update_access().status_code, 403)
        self.assert_no_changes()

    def test_inactive_admin_cannot_change_access(self):
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.client.force_login(self.admin)

        response = self.update_access()

        self.assertIn(response.status_code, (401, 403))
        self.assert_no_changes()

    def test_get_returns_default_without_creating_record(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["api_access_enabled"])
        self.assertIsNone(response.json()["updated_at"])
        self.assertIn("csrf_token", response.json())
        self.assertIn("no-store", response["Cache-Control"])
        self.assert_no_changes()

    def test_unknown_business_is_rejected(self):
        self.client.force_login(self.admin)
        unknown_url = reverse(
            "admin-business-api-access",
            kwargs={"business_owner_id": uuid.uuid4()},
        )

        response = self.client.patch(
            unknown_url,
            data=json.dumps({"api_access_enabled": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assert_no_changes()

    def test_patch_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.patch(
            self.url,
            data=json.dumps({"api_access_enabled": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assert_no_changes()

    def test_valid_csrf_request_disables_access_and_records_actor(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        initial = client.get(self.url)
        self.assertEqual(initial.status_code, 200)

        response = client.patch(
            self.url,
            data=json.dumps({
                "api_access_enabled": False,
                "reason": "  Security review  ",
            }),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=initial.json()["csrf_token"],
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        self.assertFalse(response.json()["api_access_enabled"])
        self.assertIn("no-store", response["Cache-Control"])

        access = BusinessApiAccess.objects.get(
            business_owner_id=self.owner_id,
        )
        identity = AdminAuditIdentity.objects.get(
            admin_user_id=str(self.admin.pk),
        )
        event = ApiAuditLog.objects.get(
            action="business.api_access_disabled",
        )

        self.assertFalse(access.api_access_enabled)
        self.assertEqual(access.updated_by, identity.id)
        self.assertEqual(event.actor_id, identity.id)
        self.assertEqual(event.actor_email, self.admin.email)
        self.assertEqual(event.business_owner_id, self.owner_id)
        self.assertEqual(event.target_id, self.owner_id)
        self.assertEqual(event.detail["reason"], "Security review")
        self.assertTrue(event.detail["previous_enabled"])
        self.assertFalse(event.detail["api_access_enabled"])

        self.key.refresh_from_db()
        self.assertEqual(self.key.status, "active")

    def test_repeating_same_value_does_not_duplicate_audit(self):
        self.client.force_login(self.admin)

        self.assertEqual(self.update_access(False).status_code, 200)
        response = self.update_access(False)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.assertEqual(ApiAuditLog.objects.count(), 1)

    def test_enabling_default_access_is_a_no_op(self):
        self.client.force_login(self.admin)

        response = self.update_access(True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.assert_no_changes()

    def test_reenable_records_transition_without_restoring_revoked_key(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.update_access(False).status_code, 200)

        self.key.status = "revoked"
        self.key.save(update_fields=["status"])

        response = self.update_access(True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        access = BusinessApiAccess.objects.get(
            business_owner_id=self.owner_id,
        )
        self.assertTrue(access.api_access_enabled)

        event = ApiAuditLog.objects.get(
            action="business.api_access_enabled",
        )
        self.assertFalse(event.detail["previous_enabled"])
        self.assertTrue(event.detail["api_access_enabled"])

        self.key.refresh_from_db()
        self.assertEqual(self.key.status, "revoked")

    def test_business_rate_limit_starts_in_next_window(self):
        self.client.force_login(self.admin)

        # The key has no requests yet when the administrator schedules the limit.
        with patch("developer.views.time", return_value=150):
            response = self.client.patch(
                self.url,
                data=json.dumps({"rate_limit_requests_per_minute": 1}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            settings = self.client.get(self.url).json()

        self.assertIsNone(settings["rate_limit_requests_per_minute"])
        self.assertEqual(settings["pending_rate_limit_requests_per_minute"], 1)
        self.assertIsNotNone(settings["rate_limit_effective_at"])
        event = ApiAuditLog.objects.get(action="business.api_rate_limit_updated")
        self.assertEqual(event.detail["effective_window"], 3)

        middleware = ApiRateLimitMiddleware(lambda request: JsonResponse({}))

        def request():
            partner_request = RequestFactory().get("/v1/errands")
            partner_request.api_key_id = self.key.pk
            partner_request.business_owner_id = str(self.owner_id)
            return middleware(partner_request)

        with patch("developer.rate_limit_middleware.time", return_value=179):
            self.assertEqual(request().status_code, 200)
            self.assertEqual(request().status_code, 200)

        with patch("developer.rate_limit_middleware.time", return_value=180):
            self.assertEqual(request().status_code, 200)
            rejected = request()
            self.assertEqual(rejected.status_code, 429)
            self.assertEqual(rejected["Retry-After"], "60")

        with patch("developer.views.time", return_value=180):
            settings = self.client.get(self.url).json()

        self.assertEqual(settings["rate_limit_requests_per_minute"], 1)
        self.assertIsNone(settings["rate_limit_effective_at"])

    def test_daily_creation_quota_can_be_set_and_reset(self):
        self.client.force_login(self.admin)

        for override in (10, None):
            with self.subTest(override=override):
                response = self.client.patch(
                    self.url,
                    data=json.dumps({"daily_creation_quota": override}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["api_access_enabled"])
                settings = self.client.get(self.url).json()
                self.assertEqual(settings["daily_creation_quota"], override)
                self.assertEqual(settings["default_daily_creation_quota"], 2000)

        self.assertEqual(
            ApiAuditLog.objects.filter(
                action="business.api_daily_creation_quota_updated",
            ).count(),
            2,
        )

    def test_invalid_payloads_are_rejected(self):
        self.client.force_login(self.admin)

        payloads = [
            [],
            {},
            {"api_access_enabled": "false"},
            {"api_access_enabled": 0},
            {"daily_creation_quota": False},
            {"daily_creation_quota": 0},
            {"daily_creation_quota": 1.5},
            {"daily_creation_quota": 2_147_483_648},
            {"rate_limit_requests_per_minute": False},
            {"rate_limit_requests_per_minute": 0},
            {"rate_limit_requests_per_minute": 1.5},
            {"rate_limit_requests_per_minute": 2_147_483_648},
            {"api_access_enabled": False, "reason": 123},
            {"api_access_enabled": False, "reason": "x" * 501},
            {
                "api_access_enabled": False,
                "actor_id": str(uuid.uuid4()),
            },
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.patch(
                    self.url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assert_no_changes()

    def test_audit_failure_rolls_back_new_access_record_and_identity(self):
        self.client.force_login(self.admin)

        with patch(
            "developer.views.log_audit",
            side_effect=RuntimeError("Simulated audit failure"),
        ):
            with self.assertRaisesMessage(
                RuntimeError, "Simulated audit failure"
            ):
                self.update_access(False)

        self.assert_no_changes()

    def test_audit_failure_keeps_existing_business_disabled(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.update_access(False).status_code, 200)

        before = BusinessApiAccess.objects.get(
            business_owner_id=self.owner_id,
        )
        original_updated_at = before.updated_at

        with patch(
            "developer.views.log_audit",
            side_effect=RuntimeError("Simulated audit failure"),
        ):
            with self.assertRaisesMessage(
                RuntimeError, "Simulated audit failure"
            ):
                self.update_access(True)

        before.refresh_from_db()
        self.assertFalse(before.api_access_enabled)
        self.assertEqual(before.updated_at, original_updated_at)
        self.assertEqual(ApiAuditLog.objects.count(), 1)