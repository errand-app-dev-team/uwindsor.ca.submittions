
import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings

from developer.keys import hash_api_key
from developer.models import ApiAuditLog, ApiKey
from developer.services.key_generation import (
    KeyGenerationError,
    create_api_key,
    generate_raw_key,
)


@override_settings(API_KEY_HASH_PEPPER="test_only_pepper")
class ApiKeyGenerationTests(TestCase):

    def setUp(self):
        # Each test uses a separate business and creator identity.
        self.business_owner_id = uuid.uuid4()
        self.created_by_id = uuid.uuid4()

        self.key_data = {
            "business_owner_id": self.business_owner_id,
            "created_by_id": self.created_by_id,
            "name": "MVP Test Key",
            "environment": "test",
            "scopes": ["quotes:read", "aerrands:read"],
        }

    def test_generated_key_has_correct_prefix(self):
        raw_key = generate_raw_key("test")

        self.assertTrue(raw_key.startswith("aer_test_"))
        self.assertEqual(len(raw_key.removeprefix("aer_test_")), 43)

    def test_generated_keys_are_unique(self):
        first = generate_raw_key("test")
        second = generate_raw_key("test")

        self.assertNotEqual(first, second)

    def test_invalid_environment_is_rejected(self):
        with self.assertRaises(KeyGenerationError):
            generate_raw_key("production")

    def test_api_key_is_created_and_hashed(self):
        api_key, raw_key = create_api_key(**self.key_data)
        saved_key = ApiKey.objects.get(pk=api_key.id)

        # Only the HMAC hash and a short display prefix should be persisted.
        self.assertEqual(saved_key.key_hash, hash_api_key(raw_key))
        self.assertNotEqual(saved_key.key_hash, raw_key)
        self.assertEqual(saved_key.key_prefix, raw_key[:15])
        self.assertEqual(saved_key.status, "active")
        self.assertEqual(saved_key.environment, "test")
        self.assertEqual(
            saved_key.scopes,
            ["aerrands:read", "quotes:read"],
        )

    def test_creation_is_audited(self):
        api_key, raw_key = create_api_key(**self.key_data)

        audit = ApiAuditLog.objects.get(
            action="key.created",
            target_id=api_key.id,
        )

        # Audit records must not expose the generated secret or its hash.
        self.assertEqual(audit.business_owner_id, self.business_owner_id)
        self.assertNotIn(raw_key, str(audit.detail))
        self.assertNotIn(api_key.key_hash, str(audit.detail))

    def test_duplicate_key_name_is_rejected(self):
        create_api_key(**self.key_data)

        with self.assertRaises(KeyGenerationError):
            create_api_key(**self.key_data)

    def test_invalid_scope_is_rejected(self):
        self.key_data["scopes"] = ["admin:all"]

        with self.assertRaises(KeyGenerationError):
            create_api_key(**self.key_data)

    def test_missing_scopes_are_rejected(self):
        self.key_data["scopes"] = []

        with self.assertRaises(KeyGenerationError):
            create_api_key(**self.key_data)

    def test_invalid_expiration_is_rejected(self):
        self.key_data["expires_in_days"] = 400

        with self.assertRaises(KeyGenerationError):
            create_api_key(**self.key_data)

    def test_audit_failure_revokes_new_key(self):
        # Simulate audit storage failure to verify the key is disabled.
        with patch(
            "developer.services.key_generation.log_audit",
            side_effect=RuntimeError("Audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                create_api_key(**self.key_data)

        saved_key = ApiKey.objects.get(name="MVP Test Key")

        self.assertEqual(saved_key.status, "revoked")
        self.assertIsNotNone(saved_key.revoked_at)
