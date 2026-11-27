
import time

from django.core.cache import cache


DEFAULT_RATE_LIMIT = 60
WINDOW_SECONDS = 60


def check_rate_limit(api_key_id, limit=DEFAULT_RATE_LIMIT, *, now=None):
    """Check the number of requests allowed per API key per minute."""

    now = int(time.time() if now is None else now)
    current_window = now // WINDOW_SECONDS
    cache_key = f"api_rate_limit:{api_key_id}:{current_window}"

    # Add the counter only when the current window is new.
    if cache.add(cache_key, 1, timeout=WINDOW_SECONDS * 2):
        count = 1
    else:
        count = cache.incr(cache_key)

    retry_after = WINDOW_SECONDS - (now % WINDOW_SECONDS)

    return count <= limit, retry_after
