from developer.models import ApiAuditLog

# The audit log must never hold key material.
FORBIDDEN_DETAIL_KEYS = {"key", "raw_key", "api_key", "key_hash"}


def log_audit(*, action, business_owner_id, actor_id=None, actor_email="",
              target_id=None, ip=None, user_agent="", detail=None):
    """Write one audit row (for example action='key.revoked')."""
    detail = detail or {}
    if FORBIDDEN_DETAIL_KEYS & set(detail):
        raise ValueError("Audit detail must not contain key material.")

    return ApiAuditLog.objects.create(
        action=action,
        business_owner_id=business_owner_id,
        actor_id=actor_id,
        actor_email=actor_email,
        target_id=target_id,
        ip=ip or "0.0.0.0",  # model requires an IP; 0.0.0.0 means "unknown"
        user_agent=user_agent,
        detail=detail,
    )