from django.urls import path, include
from django.contrib import admin

from developer.urls import dashboard_urlpatterns, webhook_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),

    # Developer dashboard endpoints
    path("dashboard-api/", include(dashboard_urlpatterns)),

    # Aerrand Partner API endpoints
    path("v1/", include("aerrands.urls")),

    # Webhook subscription management endpoints
    path("v1/", include(webhook_urlpatterns)),
]
