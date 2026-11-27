"""Create persistent notifications for businesses and administrators."""

from django.db import transaction

from developer.models import Notification


@transaction.atomic
def create_notification(
    *,
    business_owner_id=None,
    admin_user_id=None,
    event_type,
    title,
    message,
    level="info",
    target_id=None,
    environment=None,
):
    """Store a notification for exactly one recipient."""

    if (business_owner_id is None) == (admin_user_id is None):
        raise ValueError(
            "Exactly one notification recipient must be provided."
        )

    return Notification.objects.create(
        business_owner_id=business_owner_id,
        admin_user_id=(
            str(admin_user_id)
            if admin_user_id is not None else None
        ),
        event_type=event_type,
        title=title,
        message=message,
        level=level,
        target_id=target_id,
        environment=environment,
    )


def notify_administrator(
    *,
    admin_user_id,
    event_type,
    title,
    message,
    level="info",
    target_id=None,
    environment=None,
):
    """Store a notification for an individual administrator."""

    return create_notification(
        admin_user_id=admin_user_id,
        event_type=event_type,
        title=title,
        message=message,
        level=level,
        target_id=target_id,
        environment=environment,
    )

def notify_key_created(api_key):
    """Notify a business when a new API key is created."""

    return create_notification(
        business_owner_id=api_key.business_owner_id,
        event_type="key.created",
        title="API key created",
        message=f'API key "{api_key.name}" has been created.',
        level="success",
        target_id=api_key.id,
        environment=api_key.environment,
    )


def notify_key_revoked(api_key):
    """Notify a business when an API key is revoked."""

    return create_notification(
        business_owner_id=api_key.business_owner_id,
        event_type="key.revoked",
        title="API key revoked",
        message=f'API key "{api_key.name}" has been revoked.',
        level="warning",
        target_id=api_key.id,
        environment=api_key.environment,
    )


def notify_key_updated(api_key):
    """Notify a business when its API key settings change."""

    return create_notification(
        business_owner_id=api_key.business_owner_id,
        event_type="key.updated",
        title="API key updated",
        message=f'API key "{api_key.name}" settings have been updated.',
        level="info",
        target_id=api_key.id,
        environment=api_key.environment,
    )


def notify_business_access_changed(business_access):
    """Notify a business when its API access is enabled or disabled."""

    enabled = business_access.api_access_enabled

    return create_notification(
        business_owner_id=business_access.business_owner_id,
        event_type=(
            "business.api_enabled"
            if enabled
            else "business.api_disabled"
        ),
        title="API access restored" if enabled else "API access disabled",
        message=(
            "Your business API access has been restored."
            if enabled
            else "Your business API access has been disabled."
        ),
        level="success" if enabled else "warning",
    )


def notify_business_limits_updated(business_access):
    """Notify a business when its API usage limits change."""

    return create_notification(
        business_owner_id=business_access.business_owner_id,
        event_type="business.limits_updated",
        title="API limits updated",
        message="Your business API usage limits have been updated.",
        level="info",
    )


def notify_webhook_created(subscription):
    """Notify a business when a webhook is registered."""

    return create_notification(
        business_owner_id=subscription.business_owner_id,
        event_type="webhook.created",
        title="Webhook registered",
        message="A new webhook subscription has been registered.",
        level="success",
        target_id=subscription.id,
        environment=subscription.environment,
    )


def notify_webhook_disabled(subscription):
    """Notify a business when a webhook is disabled."""

    return create_notification(
        business_owner_id=subscription.business_owner_id,
        event_type="webhook.disabled",
        title="Webhook disabled",
        message="A webhook subscription has been disabled.",
        level="warning",
        target_id=subscription.id,
        environment=subscription.environment,
    )