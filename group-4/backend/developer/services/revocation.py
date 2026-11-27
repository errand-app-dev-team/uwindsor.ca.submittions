from django.utils import timezone

from developer.models import ApiKey
from developer.services.audit import log_audit
from developer.services.notifications import notify_key_revoked


class RevocationError(Exception):
    """Base class for revoke failures."""


class KeyNotFoundError(RevocationError):
    pass


class KeyAlreadyRevokedError(RevocationError):
    pass


def revoke_api_key(*, api_key_id, business_owner_id, revoked_by_id,
                   actor_email="", ip=None, user_agent="", reason=""):
    """
    Revoke a key immediately and permanently.

    The lookup includes business_owner_id, so one business can never
    revoke (or even detect) another business's key: it just looks missing.
    The caller (the view) decides whether the actor is allowed to revoke.
    """
    try:
        api_key = ApiKey.objects.get(pk=api_key_id, business_owner_id=business_owner_id)
    except ApiKey.DoesNotExist:
        raise KeyNotFoundError("API key not found.")

    if api_key.status == "revoked":
        raise KeyAlreadyRevokedError("API key is already revoked.")

    api_key.status = "revoked"
    api_key.revoked_at = timezone.now()
    api_key.revoked_by = revoked_by_id
    api_key.save(update_fields=["status", "revoked_at", "revoked_by"])

    log_audit(
        action="key.revoked",
        business_owner_id=business_owner_id,
        actor_id=revoked_by_id,
        actor_email=actor_email,
        target_id=api_key.id,
        ip=ip,
        user_agent=user_agent,
        detail={"name": api_key.name, "environment": api_key.environment,
                "reason": reason},
    )
    # Notify the affected business about the revoked API key.
    notify_key_revoked(api_key)
    return api_key