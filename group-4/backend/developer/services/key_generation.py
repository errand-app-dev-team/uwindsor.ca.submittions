
import secrets
import uuid
from datetime import timedelta

from django.utils import timezone

from developer.keys import hash_api_key
from developer.models import ApiKey
from developer.services.audit import log_audit
from developer.services.notifications import notify_key_created


VALID_ENVIRONMENTS = {"test", "live"}

VALID_SCOPES = {
    "quotes:read",
    "aerrands:read",
    "aerrands:write",
    "aerrands:cancel",
    "wallet:read",
    "webhooks:manage",
    "webhooks:read",
    "webhooks:write",
}
MAX_ACTIVE_KEYS = 10


class KeyGenerationError(ValueError):
    """Raised when API-key creation requirements are not satisfied."""


def generate_raw_key(environment: str) -> str:
    """Generate a cryptographically secure API key with 256 bits of randomness."""
    if environment not in VALID_ENVIRONMENTS:
        raise KeyGenerationError("Environment must be test or live.")

    return f"aer_{environment}_{secrets.token_urlsafe(32)}"


def create_api_key(
    *,
    business_owner_id,
    created_by_id,
    name,
    environment,
    scopes,
    expires_in_days=None,
    actor_email="",
    ip=None,
    user_agent="",
):
    """Create an API key and return its plaintext value only once."""

    try:
        business_owner_id = uuid.UUID(str(business_owner_id))
        created_by_id = uuid.UUID(str(created_by_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise KeyGenerationError(
            "Valid business owner and creator IDs are required."
        ) from error

    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
        raise KeyGenerationError(
            "Name must contain between 1 and 64 characters."
        )

    name = name.strip()

    if environment not in VALID_ENVIRONMENTS:
        raise KeyGenerationError(
            "Environment must be test or live."
        )

    if not isinstance(scopes, (list, tuple, set)) or not scopes:
        raise KeyGenerationError(
            "At least one API-key scope is required."
        )

    if not all(isinstance(scope, str) for scope in scopes):
        raise KeyGenerationError(
            "All API-key scopes must be strings."
        )

    selected_scopes = sorted(set(scopes))

    if not set(selected_scopes).issubset(VALID_SCOPES):
        raise KeyGenerationError(
            "One or more requested API-key scopes are invalid."
        )

    if expires_in_days is not None:
        if (
            type(expires_in_days) is not int
            or not 1 <= expires_in_days <= 365
        ):
            raise KeyGenerationError(
                "Expiration must be between 1 and 365 days."
            )

    existing_keys = ApiKey.objects.filter(
        business_owner_id=business_owner_id,
        environment=environment,
    )

    if existing_keys.filter(name=name).exists():
        raise KeyGenerationError(
            "An API key with this name already exists."
        )

    if existing_keys.filter(status="active").count() >= MAX_ACTIVE_KEYS:
        raise KeyGenerationError(
            "Maximum active API-key limit reached for this environment."
        )

    raw_key = generate_raw_key(environment)

    key_prefix = raw_key[:len(f"aer_{environment}_") + 6]

    expires_at = (
        timezone.now() + timedelta(days=expires_in_days)
        if expires_in_days is not None
        else None
    )

    # Store only the hashed secret and its non-sensitive metadata.
    api_key = ApiKey.objects.create(
        business_owner_id=business_owner_id,
        created_by_id=created_by_id,
        name=name,
        environment=environment,
        key_prefix=key_prefix,
        key_hash=hash_api_key(raw_key),
        scopes=selected_scopes,
        status="active",
        expires_at=expires_at,
    )

    try:
        log_audit(
            action="key.created",
            business_owner_id=business_owner_id,
            actor_id=created_by_id,
            actor_email=actor_email,
            target_id=api_key.id,
            ip=ip,
            user_agent=user_agent,
            detail={
                "name": name,
                "environment": environment,
                "scopes": selected_scopes,
            },
        )
    except Exception:
        # Disable the key if its creation cannot be audited.
        api_key.status = "revoked"
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["status", "revoked_at"])
        raise

    # Notify the business about its newly created API key.
    notify_key_created(api_key)

    return api_key, raw_key
