"""Persist the database to disk after any request that changed it.

Only active when PERSIST_DB=1 (the file-backed mode). For read-only requests, or
other run modes, it does nothing. Failures to save never break the request.
"""
import os


class PersistMiddleware:
    _WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if os.environ.get("PERSIST_DB") == "1" and request.method in self._WRITE_METHODS:
            try:
                from . import persistence
                persistence.save()
            except Exception:  # noqa: BLE001 — never let a save error break the response
                pass
        return response
