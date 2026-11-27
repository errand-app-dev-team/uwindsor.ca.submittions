from developer.models import AdminAuditIdentity


def get_admin_audit_identity(user):
    """Resolve a dashboard user's persistent audit identity."""

    if not user.is_authenticated or not user.is_active:
        raise PermissionError("Authentication is required.")

    # Only users with dashboard access can perform audited actions.
    from developer.services.dashboard_auth import get_dashboard_identity

    if get_dashboard_identity(user) is None:
        raise PermissionError("Dashboard access is required.")

    # Preserve a stable audit identity for each Django user.
    identity, _ = AdminAuditIdentity.objects.get_or_create(
        admin_user_id=str(user.pk),
    )

    return identity.id
