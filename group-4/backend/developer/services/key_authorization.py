
from django.http import JsonResponse


class ApiKeyAuthorizationError(Exception):
    """Raised when an API key lacks the required permission."""


def require_api_key_scope(request, required_scope):
    """Verify that the authenticated API key has the required scope."""

    scopes = getattr(request, "api_key_scopes", None)

    if scopes is None:
        raise ApiKeyAuthorizationError(
            "API-key authentication context is unavailable."
        )

    if not isinstance(scopes, (list, tuple, set)):
        raise ApiKeyAuthorizationError(
            "Invalid API-key permissions."
        )

    if required_scope not in scopes:
        raise ApiKeyAuthorizationError(
            f"API key does not have the required scope: {required_scope}"
        )

    return True


def scope_error_response(required_scope):
    """Return a consistent response when API-key access is denied."""

    return JsonResponse(
        {
            "error": {
                "code": "insufficient_scope",
                "message": "API key lacks the required permission.",
                "required_scope": required_scope,
            }
        },
        status=403,
    )
