import json
import logging
import time
import uuid

from developer.models import ApiRequestLog


logger = logging.getLogger(__name__)


class ApiRequestLoggingMiddleware:
    """Record partner API request metadata for monitoring and debugging."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/v1/"):
            return self.get_response(request)

        start_time = time.monotonic()
        response = self.get_response(request)
        duration_ms = int((time.monotonic() - start_time) * 1000)

        business_owner_id = getattr(request, "business_owner_id", None)
        api_key_id = getattr(request, "api_key_id", None)

        # Only record requests with an authenticated partner identity.
        if not business_owner_id or not api_key_id:
            return response

        error_code = None

        if response.status_code >= 400:
            try:
                body = json.loads(response.content)
                if isinstance(body, dict):
                    error = body.get("error")

                    # Support both nested and string-based API errors.
                    if isinstance(error, dict):
                        error_code = error.get("code")
                    elif isinstance(error, str):
                        error_code = error
            except (ValueError, UnicodeDecodeError, AttributeError, TypeError):
                pass

        idempotency_key = request.headers.get("Idempotency-Key")

        try:
            ApiRequestLog.objects.create(
                request_id=str(uuid.uuid4()),
                api_key_id=api_key_id,
                business_owner_id=business_owner_id,
                method=request.method,
                path=request.path[:255],
                status=response.status_code,
                duration_ms=duration_ms,
                ip=request.META.get("REMOTE_ADDR", "")[:45],
                idempotency_key=(
                    idempotency_key[:64] if idempotency_key else None
                ),
                idempotenct_replay=(
                    response.get("Idempotency-Replayed") == "true"
                ),
                error_code=(
                    str(error_code)[:64] if error_code else None
                ),
            )
        except Exception:
            # A logging failure must not interrupt the API response.
            logger.exception("Failed to save API request log")

        return response
