
from django.urls import path

from . import views
from .services.dashboard_auth_views import (
    dashboard_csrf,
    dashboard_login,
    dashboard_logout,
    dashboard_session,
)

from developer.notification_views import (
    dashboard_notifications,
    mark_notification_read,
    mark_all_notifications_read,
)

# Developer dashboard endpoints
dashboard_urlpatterns = [
    path(
        "businesses/<uuid:business_owner_id>/api-keys/",
        views.admin_list_business_keys,
        name="admin-list-business-keys",
    ),
    path(
        "overview/",
        views.admin_dashboard_data,
        name="admin-dashboard-data",
    ),
    path(
        "businesses/<uuid:business_owner_id>/keys/<uuid:api_key_id>/revoke/",
        views.admin_revoke_key,
        name="admin-revoke-key",
    ),
    path(
        "businesses/<uuid:business_owner_id>/api-access/",
        views.admin_business_api_access,
        name="admin-business-api-access",
    ),
    path(
        "keys/create/",
        views.admin_create_key,
        name="admin-create-key",
    ),

    # Dashboard authentication
    path(
        "dashboard-auth/csrf/",
        dashboard_csrf,
        name="dashboard-csrf",
    ),
    path(
        "dashboard-auth/login/",
        dashboard_login,
        name="dashboard-login",
    ),
    path(
        "dashboard-auth/logout/",
        dashboard_logout,
        name="dashboard-logout",
    ),
    path(
        "dashboard-auth/session/",
        dashboard_session,
        name="dashboard-session",
    ),

    # Active business directory for administrator selection
    path(
        "businesses/",
        views.dashboard_businesses,
        name="dashboard-businesses",
    ),

    path(
        "dashboard/notifications/",
        dashboard_notifications,
        name="dashboard_notifications",
    ),
    path(
        "dashboard/notifications/read-all/",
        mark_all_notifications_read,
        name="mark_all_notifications_read",
    ),
    path(
        "dashboard/notifications/<uuid:notification_id>/read/",
        mark_notification_read,
        name="mark_notification_read",
    ),
]

# Webhook subscription management endpoints
webhook_urlpatterns = [
    path(
        "webhooks",
        views.webhooks_collection,
        name="webhooks-collection",
    ),
    path(
        "webhooks/<uuid:subscription_id>/disable",
        views.disable_webhook,
        name="disable-webhook",
    ),
]
