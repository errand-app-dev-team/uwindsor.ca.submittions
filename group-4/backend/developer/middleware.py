
from django.http import JsonResponse

from developer.models import BusinessApiAccess
from developer.services.key_authentication import (
    ApiKeyAuthenticationError,
    authenticate_api_key,
)
from developer.services.key_authorization import scope_error_response
from developer.services.key_usage import record_key_usage


class ApiKeyAuthenticationMiddleware:
    """Authenticate and authorize requests to partner API endpoints."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip("/") or "/"

        # Apply authentication only to supported partner API endpoints.
        if not (
            path == "/v1/quotes"
            or path.startswith("/v1/quotes/")
            or path == "/v1/errands"
            or path.startswith("/v1/errands/")
            or path == "/v1/webhooks"
            or path.startswith("/v1/webhooks/")
        ):
            return self.get_response(request)

        # Bearer authentication takes priority over the legacy API-key header.
        authorization = request.headers.get("Authorization")

        if authorization is not None:
            parts = authorization.split()

            if len(parts) != 2 or parts[0].lower() != "bearer":
                return JsonResponse(
                    {
                        "error": {
                            "code": "invalid_api_key",
                            "message": "A valid Bearer API key is required.",
                        }
                    },
                    status=401,
                )

            raw_key = parts[1]
        else:
            raw_key = request.headers.get("X-API-Key")

        if not raw_key:
            return JsonResponse(
                {
                    "error": {
                        "code": "invalid_api_key",
                        "message": "A valid API key is required.",
                    }
                },
                status=401,
            )

        try:
            api_key = authenticate_api_key(raw_key)
        except ApiKeyAuthenticationError:
            return JsonResponse(
                {
                    "error": {
                        "code": "invalid_api_key",
                        "message": "API key is invalid, expired, or inactive.",
                    }
                },
                status=401,
            )

        request.business_owner_id = str(api_key.business_owner_id)
        request.api_key_id = str(api_key.id)
        request.api_environment = api_key.environment
        request.api_key_scopes = api_key.scopes

        # Block requests when API access is disabled for the business.
        if BusinessApiAccess.objects.filter(
            business_owner_id=api_key.business_owner_id,
            api_access_enabled=False,
        ).exists():
            return JsonResponse(
                {
                    "error": {
                        "code": "business_api_access_disabled",
                        "message": "API access is disabled for this business.",
                    }
                },
                status=403,
            )

        method = request.method
        required_scope = None

        if path == "/v1/quotes":
            if method == "POST":
                required_scope = "quotes:read"

        elif path.startswith("/v1/quotes/"):
            if method == "GET":
                required_scope = "quotes:read"

        elif path == "/v1/errands":
            if method == "POST":
                required_scope = "aerrands:write"
            elif method == "GET":
                required_scope = "aerrands:read"

        elif path.startswith("/v1/errands/"):
            if method == "POST" and path.endswith("/cancel"):
                required_scope = "aerrands:cancel"
            elif method == "GET":
                required_scope = "aerrands:read"
            elif method == "PATCH" and "/dropoffs/" in path:
                required_scope = "aerrands:write"

        # Webhook subscription permissions.
        elif path == "/v1/webhooks":
            if method in ("GET", "POST"):
                required_scope = "webhooks:manage"

        elif path.startswith("/v1/webhooks/"):
            if method == "POST" and path.endswith("/disable"):
                required_scope = "webhooks:manage"

        if required_scope and required_scope not in request.api_key_scopes:
            return scope_error_response(required_scope)

        record_key_usage(
            api_key_id=api_key.id,
            client_ip=request.META.get("REMOTE_ADDR"),
        )

        return self.get_response(request)
