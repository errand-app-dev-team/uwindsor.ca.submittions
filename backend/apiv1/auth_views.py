"""Sign-up / sign-in endpoints for company accounts (Nikhil).

Kept in their own file so the main views stay untouched. On success both endpoints issue
a working API key for that company, so the rest of the portal (deliveries, wallet, …) works
exactly as before — now gated behind a login, and showing that company's saved data.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import auth
from .errors import error_response
from .views import _issue_key


@api_view(["POST"])
@permission_classes([AllowAny])
def signup(request):
    body = request.data or {}
    public, err = auth.signup(body.get("company"), body.get("email"), body.get("password"))
    if err:
        return error_response("signup_failed", err, 400)
    key, _owner = _issue_key(public["company"])
    return Response(
        {"company": public["company"], "email": public["email"], "key": key,
         "business": public["company"]},
        status=201,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    body = request.data or {}
    public, err = auth.login(body.get("company"), body.get("password"))
    if err:
        return error_response("login_failed", err, 401)
    key, _owner = _issue_key(public["company"])
    return Response(
        {"company": public["company"], "email": public["email"], "key": key,
         "business": public["company"]}
    )
