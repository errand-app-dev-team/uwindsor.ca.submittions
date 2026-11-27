
import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from developer.services.key_authentication import (
    ApiKeyAuthenticationError,
    authenticate_api_key,
)
from developer.services.key_generation import create_api_key


@override_settings(
    API_KEY_HASH_PEPPER="test_only_pepper",
    API_KEYS_ENABLED=True,
)
class ApiKeyAuthenticationTests(TestCase):

    def setUp(self):
        self.api_key, self.raw_key = create_api_key(
            business_owner_id=uuid.uuid4(),
            created_by_id=uuid.uuid4(),
            name="Authentication Test Key",
            environment="test",
            scopes=["quotes:read", "aerrands:read"],
        )

    def test_valid_api_key_authenticates(self):
        authenticated_key = authenticate_api_key(self.raw_key)

        self.assertEqual(authenticated_key.id, self.api_key.id)
        self.assertEqual(
            authenticated_key.business_owner_id,
            self.api_key.business_owner_id,
        )

    def test_invalid_api_key_is_rejected(self):
        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key("aer_test_invalidkey")

    def test_missing_api_key_is_rejected(self):
        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key("")

    def test_invalid_key_prefix_is_rejected(self):
        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key("invalid_prefix_12345")

    def test_revoked_api_key_is_rejected(self):
        # A revoked credential must no longer authenticate.
        self.api_key.status = "revoked"
        self.api_key.revoked_at = timezone.now()
        self.api_key.save(update_fields=["status", "revoked_at"])

        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key(self.raw_key)

    def test_expired_api_key_is_rejected(self):
        # Expiration must be enforced even when the key remains active.
        self.api_key.expires_at = timezone.now() - timedelta(minutes=1)
        self.api_key.save(update_fields=["expires_at"])

        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key(self.raw_key)

    def test_rotating_api_key_is_rejected(self):
        self.api_key.status = "rotating"
        self.api_key.save(update_fields=["status"])

        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key(self.raw_key)

    @override_settings(API_KEYS_ENABLED=False)
    def test_disabled_authentication_rejects_key(self):
        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key(self.raw_key)

    def test_excessively_long_key_is_rejected(self):
        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key("aer_test_" + "x" * 300)

    def test_environment_mismatch_is_rejected(self):
        # A test credential cannot be accepted as a live credential.
        self.api_key.environment = "live"
        self.api_key.save(update_fields=["environment"])

        with self.assertRaises(ApiKeyAuthenticationError):
            authenticate_api_key(self.raw_key)
