
"""Session authentication endpoints for the business dashboard."""

import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from developer.models import BusinessAccount
from developer.services.dashboard_auth import get_dashboard_identity



@never_cache
@require_GET
def dashboard_session(request):
    """Return the authenticated dashboard user's identity."""
    identity = get_dashboard_identity(request.user)

    if identity is None:
        return JsonResponse({"authenticated": False}, status=401)

    user = request.user
    business_name = None

    # Resolve the registered business name for business accounts.
    if identity["role"] == "business":
        business = BusinessAccount.objects.filter(
            pk=identity["business_owner_id"]
        ).first()

        if business is not None:
            business_name = business.name

    return JsonResponse({
        "authenticated": True,
        "username": user.get_username(),
        "full_name": user.get_full_name().strip() or user.get_username(),
        "business_name": business_name,
        "role": identity["role"],
        "business_owner_id": (
            str(identity["business_owner_id"])
            if identity["business_owner_id"] is not None
            else None
        ),
    })


@never_cache
@require_GET
def dashboard_csrf(request):
    """Issue a CSRF cookie before submitting login credentials."""
    get_token(request)
    return JsonResponse({"success": True})


@never_cache
@require_POST
@csrf_protect
def dashboard_login(request):
    """Authenticate an administrator or registered business user."""
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "Invalid request."}, status=400)

    username = payload.get("username")
    password = payload.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"error": "Invalid credentials."}, status=400)

    user = authenticate(request, username=username, password=password)

    if user is None or get_dashboard_identity(user) is None:
        return JsonResponse(
            {"error": "Invalid credentials or dashboard access denied."},
            status=403,
        )

    login(request, user)

    identity = get_dashboard_identity(user)

    return JsonResponse({
        "authenticated": True,
        "username": user.get_username(),
        "role": identity["role"],
        "business_owner_id": (
            str(identity["business_owner_id"])
            if identity["business_owner_id"] is not None
            else None
        ),
    })


@never_cache
@require_POST
@csrf_protect
def dashboard_logout(request):
    """End the authenticated dashboard session."""
    logout(request)
    return JsonResponse({"success": True})
