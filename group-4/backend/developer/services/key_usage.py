from datetime import timedelta
from ipaddress import ip_address

from django.db.models import Q
from django.utils import timezone

from developer.models import ApiKey


def record_key_usage(*, api_key_id, client_ip=None):
    """Update key usage at most once every 60 seconds."""
    now = timezone.now()
    cutoff = now - timedelta(seconds=60)

    try:
        normalized_ip = str(ip_address(client_ip)) if client_ip else None
    except ValueError:
        normalized_ip = None

    return ApiKey.objects.filter(
        pk=api_key_id,
    ).filter(
        Q(last_used_at__isnull=True)
        | Q(last_used_at__lte=cutoff)
    ).update(
        last_used_at=now,
        last_used_ip=normalized_ip,
    )