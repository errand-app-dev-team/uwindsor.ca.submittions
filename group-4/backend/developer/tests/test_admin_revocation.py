import json
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from developer.models import AdminAuditIdentity, ApiAuditLog, ApiKey, ApiRequestLog
from developer.services.admin_identity import get_admin_audit_identity


class AdminRevocationTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_user(
            username="revocation_admin",
            email="admin@example.com",
            password="Test-password-123!",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        self.staff = User.objects.create_user(
            username="revocation_staff",
            password="Test-password-123!",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )

        self.owner_id = uuid.uuid4()

        self.key = ApiKey.objects.create(
            business_owner_id=self.owner_id,
            created_by_id=self.owner_id,
            name="Admin revocation test",
            environment="test",
            key_prefix="aer_test_example",
            key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            scopes=["quotes:read"],
            status="active",
        )

        self.url = reverse(
            "admin-revoke-key",
            kwargs={
                "business_owner_id": self.owner_id,
                "api_key_id": self.key.id,
            },
        )

    def test_overview_counts_only_live_non_replayed_bookings(self):
        live_key = ApiKey.objects.create(
            business_owner_id=self.owner_id,
            created_by_id=self.owner_id,
            name="Live booking count fixture",
            environment="live",
            key_prefix="aer_live_example",
            key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            scopes=["quotes:read"],
            status="active",
        )

        for key, replay in ((live_key, False), (self.key, False), (live_key, True)):
            ApiRequestLog.objects.create(
                request_id=str(uuid.uuid4()),
                api_key_id=key.id,
                business_owner_id=self.owner_id,
                method="POST",
                path="/v1/errands",
                status=201,
                duration_ms=10,
                ip="127.0.0.1",
                idempotenct_replay=replay,
            )

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin-dashboard-data"),
            {"business_owner_id": str(self.owner_id)},
        )

        self.assertEqual(response.status_code, 200, response.content)
        summary = response.json()["summary"]
        self.assertEqual(summary["requests_last_24h"], 3)
        self.assertEqual(summary["api_bookings_last_24h"], 1)

    def test_admin_key_list_is_scoped_and_returns_only_metadata(self):
        other_owner = uuid.uuid4()
        ApiKey.objects.create(
            business_owner_id=other_owner,
            created_by_id=other_owner,
            name="Another business key",
            environment="test",
            key_prefix="aer_test_other",
            key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            scopes=["quotes:read"],
            status="active",
        )
        self.client.force_login(self.admin)
        url = reverse("admin-list-business-keys", args=[self.owner_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["business_owner_id"], str(self.owner_id))
        self.assertEqual([key["id"] for key in body["keys"]], [str(self.key.id)])
        self.assertEqual(
            set(body["keys"][0]),
            {"id", "name", "prefix", "environment", "created_at", "last_used_at", "status"},
        )
        self.assertNotContains(response, self.key.key_hash)

    def test_admin_key_list_denies_anonymous_and_non_admin_users(self):
        url = reverse("admin-list-business-keys", args=[self.owner_id])
        self.assertEqual(self.client.get(url).status_code, 401)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)

    def post_revoke(self, payload=None, url=None):
        return self.client.post(
            url or self.url,
            data=json.dumps(
                {"reason": "Test completed"} if payload is None else payload
            ),
            content_type="application/json",
        )

    def assert_key_unchanged(self):
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, "active")
        self.assertIsNone(self.key.revoked_at)
        self.assertIsNone(self.key.revoked_by)
        self.assertFalse(
            ApiAuditLog.objects.filter(
                target_id=self.key.id,
                action="key.revoked",
            ).exists()
        )

    def test_anonymous_user_is_rejected(self):
        # The normal test client isolates the authentication check.
        # Separate tests below enforce CSRF.
        response = self.post_revoke()

        self.assertEqual(response.status_code, 401)
        self.assert_key_unchanged()

    def test_staff_without_superuser_permission_is_rejected(self):
        self.client.force_login(self.staff)

        response = self.post_revoke()

        self.assertEqual(response.status_code, 403)
        self.assert_key_unchanged()

    def test_inactive_administrator_is_rejected(self):
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.client.force_login(self.admin)

        response = self.post_revoke()

        # The authentication backend may treat inactive users as anonymous.
        self.assertIn(response.status_code, (401, 403))
        self.assert_key_unchanged()

    def test_get_cannot_revoke_key(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assert_key_unchanged()

    def test_wrong_business_is_rejected(self):
        self.client.force_login(self.admin)

        wrong_business_url = reverse(
            "admin-revoke-key",
            kwargs={
                "business_owner_id": uuid.uuid4(),
                "api_key_id": self.key.id,
            },
        )

        response = self.post_revoke(url=wrong_business_url)

        self.assertEqual(response.status_code, 404)
        self.assert_key_unchanged()
        self.assertFalse(AdminAuditIdentity.objects.exists())

    def test_missing_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)

        response = csrf_client.post(
            self.url,
            data=json.dumps({"reason": "Test completed"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assert_key_unchanged()

    def test_valid_csrf_request_revokes_and_records_admin_identity(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)

        overview = csrf_client.get(reverse("admin-dashboard-data"))
        self.assertEqual(overview.status_code, 200)

        response = csrf_client.post(
            self.url,
            data=json.dumps({"reason": "  Demonstration completed  "}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=overview.json()["csrf_token"],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "revoked")
        self.assertIn("no-store", response["Cache-Control"])

        identity = AdminAuditIdentity.objects.get(
            admin_user_id=str(self.admin.pk),
        )

        self.key.refresh_from_db()
        self.assertEqual(self.key.status, "revoked")
        self.assertIsNotNone(self.key.revoked_at)
        self.assertEqual(self.key.revoked_by, identity.id)

        event = ApiAuditLog.objects.get(
            target_id=self.key.id,
            action="key.revoked",
        )

        self.assertEqual(event.business_owner_id, self.owner_id)
        self.assertEqual(event.actor_id, identity.id)
        self.assertEqual(event.actor_email, self.admin.email)
        self.assertEqual(
            event.detail["reason"],
            "Demonstration completed",
        )
        self.assertNotIn(self.key.key_hash, json.dumps(event.detail))
        self.assertNotIn(
            self.key.key_hash,
            response.content.decode(),
        )

    def test_admin_identity_is_stable(self):
        first_id = get_admin_audit_identity(self.admin)
        second_id = get_admin_audit_identity(self.admin)

        self.assertEqual(first_id, second_id)
        self.assertEqual(
            AdminAuditIdentity.objects.filter(
                admin_user_id=str(self.admin.pk),
            ).count(),
            1,
        )

    def test_repeat_revocation_does_not_duplicate_audit_event(self):
        self.client.force_login(self.admin)

        first_response = self.post_revoke()
        self.assertEqual(first_response.status_code, 200)

        self.key.refresh_from_db()
        original_revoked_at = self.key.revoked_at

        second_response = self.post_revoke()
        self.assertEqual(second_response.status_code, 409)

        self.key.refresh_from_db()
        self.assertEqual(self.key.revoked_at, original_revoked_at)
        self.assertEqual(
            ApiAuditLog.objects.filter(
                target_id=self.key.id,
                action="key.revoked",
            ).count(),
            1,
        )

    def test_invalid_payloads_are_rejected_without_revocation(self):
        self.client.force_login(self.admin)

        invalid_payloads = [
            [],
            {"reason": 123},
            {"reason": "x" * 501},
            {"reason": "Test", "actor_id": str(uuid.uuid4())},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.post_revoke(payload=payload)

                self.assertEqual(response.status_code, 400)
                self.assert_key_unchanged()