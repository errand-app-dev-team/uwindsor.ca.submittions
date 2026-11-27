import json
import uuid
from unittest.mock import Mock

from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings

from developer.middleware import ApiKeyAuthenticationMiddleware
from developer.models import BusinessApiAccess
from developer.services.key_generation import create_api_key


@override_settings(
    API_KEY_HASH_PEPPER="test_only_pepper",
    API_KEYS_ENABLED=True,
)
class BusinessApiAccessTests(TestCase):
    def setUp(self):
        self.owner_id = uuid.uuid4()
        self.factory = RequestFactory()

        self.key, self.raw_key = self.make_key(
            self.owner_id, "test"
        )
        self.live_key, self.live_raw_key = self.make_key(
            self.owner_id, "live"
        )

        self.downstream = Mock(
            return_value=JsonResponse({"reached_view": True})
        )
        self.middleware = ApiKeyAuthenticationMiddleware(
            self.downstream
        )

    def make_key(self, owner_id, environment):
        return create_api_key(
            business_owner_id=owner_id,
            created_by_id=uuid.uuid4(),
            name=f"{environment} access test",
            environment=environment,
            scopes=["quotes:read", "aerrands:read"],
        )

    def request(self, raw_key, path="/v1/quotes", method="post"):
        make_request = getattr(self.factory, method)
        request = make_request(
            path,
            HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        )
        return self.middleware(request)

    def disable_business(self):
        return BusinessApiAccess.objects.create(
            business_owner_id=self.owner_id,
            api_access_enabled=False,
        )

    def test_missing_settings_preserve_existing_access(self):
        response = self.request(self.raw_key)

        self.assertEqual(response.status_code, 200)
        self.downstream.assert_called_once()

    def test_explicitly_enabled_business_can_access_api(self):
        BusinessApiAccess.objects.create(
            business_owner_id=self.owner_id,
            api_access_enabled=True,
        )

        response = self.request(self.raw_key)

        self.assertEqual(response.status_code, 200)
        self.downstream.assert_called_once()

    def test_disabled_business_blocks_test_and_live_keys(self):
        self.disable_business()

        for raw_key in (self.raw_key, self.live_raw_key):
            with self.subTest(environment=raw_key.split("_")[1]):
                response = self.request(raw_key)

                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    json.loads(response.content)["error"]["code"],
                    "business_api_access_disabled",
                )

        self.downstream.assert_not_called()

        for key in (self.key, self.live_key):
            key.refresh_from_db()
            self.assertEqual(key.status, "active")
            self.assertIsNone(key.revoked_at)

    def test_disabled_business_cannot_access_errands(self):
        self.disable_business()

        response = self.request(
            self.raw_key,
            path="/v1/errands",
            method="get",
        )

        self.assertEqual(response.status_code, 403)
        self.downstream.assert_not_called()

    def test_disabling_one_business_does_not_block_another(self):
        self.disable_business()
        other_key, other_raw_key = self.make_key(
            uuid.uuid4(), "test"
        )

        response = self.request(other_raw_key)

        self.assertEqual(response.status_code, 200)
        self.downstream.assert_called_once()
        other_key.refresh_from_db()
        self.assertEqual(other_key.status, "active")

    def test_reenabling_restores_access_for_valid_key(self):
        access = self.disable_business()

        self.assertEqual(
            self.request(self.raw_key).status_code,
            403,
        )
        self.downstream.assert_not_called()

        access.api_access_enabled = True
        access.save(
            update_fields=["api_access_enabled", "updated_at"]
        )

        self.assertEqual(
            self.request(self.raw_key).status_code,
            200,
        )
        self.downstream.assert_called_once()

    def test_reenabling_does_not_restore_revoked_key(self):
        access = self.disable_business()

        self.key.status = "revoked"
        self.key.save(update_fields=["status"])

        access.api_access_enabled = True
        access.save(
            update_fields=["api_access_enabled", "updated_at"]
        )

        response = self.request(self.raw_key)

        self.assertEqual(response.status_code, 401)
        self.downstream.assert_not_called()