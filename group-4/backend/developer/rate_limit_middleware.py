
from time import time

from django.http import JsonResponse

from developer.models import ApiKey, BusinessApiAccess
from developer.services.rate_limit_service import (
    DEFAULT_RATE_LIMIT,
    WINDOW_SECONDS,
    check_rate_limit,
)


class ApiRateLimitMiddleware:
    """Enforce per-API-key request limits for partner API endpoints."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Apply rate limiting only to partner API endpoints.
        if not request.path.startswith("/v1/"):
            return self.get_response(request)

        api_key_id = getattr(request, "api_key_id", None)

        # Authentication middleware handles requests without an API key.
        if not api_key_id:
            return self.get_response(request)

        limit = DEFAULT_RATE_LIMIT

        # Use the API key's custom limit when one is configured.
        override = (
            ApiKey.objects.filter(pk=api_key_id)
            .values_list("rate_limit_override", flat=True)
            .first()
        )

        custom_limit = (
            override.get("requests_per_minute")
            if isinstance(override, dict) else None
        )
        has_key_override = type(custom_limit) is int and custom_limit > 0
        if has_key_override:
            limit = custom_limit

        # A valid key-level override takes precedence over the business default.
        business_access = None
        business_owner_id = getattr(request, "business_owner_id", None)
        if not has_key_override and business_owner_id:
            business_access = BusinessApiAccess.objects.filter(
                business_owner_id=business_owner_id,
            ).first()

        if business_access is None:
            allowed, retry_after = check_rate_limit(api_key_id, limit=limit)
        else:
            now = int(time())
            business_limit = business_access.rate_limit_for_window(
                now // WINDOW_SECONDS,
            )
            allowed, retry_after = check_rate_limit(
                api_key_id,
                limit=business_limit or DEFAULT_RATE_LIMIT,
                now=now,
            )

        if not allowed:
            response = JsonResponse(
                {
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": "Too many requests. Please try again later.",
                    }
                },
                status=429,
            )
            response["Retry-After"] = str(retry_after)
            return response

        return self.get_response(request)
