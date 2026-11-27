
"""Authentication and business ownership for the developer dashboard."""
from developer.models import BusinessMembership


def get_dashboard_identity(user):
    """Resolve the authenticated user's dashboard access."""

    if not user.is_authenticated or not user.is_active:
        return None

    if user.is_superuser:
        return {
            "role": "admin",
            "business_owner_id": None,
        }

    membership = (
        BusinessMembership.objects
        .select_related("business")
        .filter(user_id=str(user.pk), business__is_active=True)
        .first()
    )

    if membership is None:
        return None

    return {
        "role": "business",
        "business_owner_id": membership.business_id,
    }
