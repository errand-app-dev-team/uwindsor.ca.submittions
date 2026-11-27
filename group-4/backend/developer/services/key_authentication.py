
import hmac

from django.conf import settings
from django.utils import timezone

from developer.keys import hash_api_key
from developer.models import ApiKey


class ApiKeyAuthenticationError(Exception):
    """Raised when API-key authentication fails."""


def authenticate_api_key(raw_key: str) -> ApiKey:
    """Authenticate a partner API key and return its database record."""

    if not getattr(settings, "API_KEYS_ENABLED", False):
        raise ApiKeyAuthenticationError(
            "API-key authentication is currently disabled."
        )

    if not isinstance(raw_key, str) or not raw_key:
        raise ApiKeyAuthenticationError(
            "A valid API key is required."
        )

    if len(raw_key) > 256:
        raise ApiKeyAuthenticationError(
            "Invalid API key."
        )

    # Validate the key format before performing a database lookup.
    if not raw_key.startswith(("aer_test_", "aer_live_")):
        raise ApiKeyAuthenticationError(
            "Invalid API key."
        )

    key_hash = hash_api_key(raw_key)

    try:
        api_key = ApiKey.objects.get(key_hash=key_hash)
    except ApiKey.DoesNotExist as error:
        raise ApiKeyAuthenticationError(
            "Invalid API key."
        ) from error

    # Compare the stored hash before accepting the credential.
    if not hmac.compare_digest(api_key.key_hash, key_hash):
        raise ApiKeyAuthenticationError(
            "Invalid API key."
        )

    if api_key.status != "active":
        raise ApiKeyAuthenticationError(
            "API key is inactive or revoked."
        )

    if api_key.expires_at and api_key.expires_at <= timezone.now():
        raise ApiKeyAuthenticationError(
            "API key has expired."
        )

    expected_prefix = f"aer_{api_key.environment}_"

    if not raw_key.startswith(expected_prefix):
        raise ApiKeyAuthenticationError(
            "API-key environment mismatch."
        )

    return api_key
