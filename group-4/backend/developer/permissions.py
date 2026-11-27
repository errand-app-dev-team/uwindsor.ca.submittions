from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import BasePermission

class HasApiScope(BasePermission):
    def has_permission(self, request, view):
        required_scope = getattr(view, 'required_scope', None)

        if not isinstance(required_scope,str) or not required_scope:
            raise ImproperlyConfigured(
                "This endpoint must declare a required_scope."

            )

        #Authentication will place the verified key record here.
        api_key = request.auth

        if api_key is None:
            raise NotAuthenticated("An API key is required.")

        scopes = getattr(api_key, 'scopes', None)

        if not isinstance(scopes, list) or required_scope not in scopes:
            raise PermissionDenied(
                detail={
                    "error": {
                        "code": "insufficient_scope",
                        "message": "This API key does not have the required permissions.",
                        "required_scope": required_scope,
                    }
                }
            )
        return True
