from datetime import datetime, time, timedelta, timezone
from math import ceil
from uuid import UUID

from django.db.models import F
from django.utils.timezone import now

from developer.models import BusinessApiAccess, BusinessDailyCreationUsage


DEFAULT_DAILY_CREATION_QUOTA = 2000


class DailyCreationQuotaExceeded(Exception):
    def __init__(self, retry_after):
        super().__init__("Daily aerrand creation quota exceeded.")
        self.retry_after = retry_after


def reserve_daily_creation(business_owner_id):
    """Reserve one business-wide creation slot before contacting the adapter."""
    business_owner_id = UUID(str(business_owner_id))
    limit = (
        BusinessApiAccess.objects.filter(business_owner_id=business_owner_id)
        .values_list("daily_creation_quota", flat=True)
        .first()
    )
    if limit is None:
        limit = DEFAULT_DAILY_CREATION_QUOTA

    current_time = now().astimezone(timezone.utc)
    day = current_time.date()
    usage_id = f"{business_owner_id}:{day.isoformat()}"

    BusinessDailyCreationUsage.objects.get_or_create(pk=usage_id)
    # Compare and increment on the same document so concurrent requests share the cap.
    reserved = BusinessDailyCreationUsage.objects.filter(
        pk=usage_id, used__lt=limit,
    ).update(used=F("used") + 1)

    if not reserved:
        reset_at = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)
        raise DailyCreationQuotaExceeded(max(1, ceil((reset_at - current_time).total_seconds())))

    return usage_id


def release_daily_creation(usage_id):
    """Return a reserved slot when the booking definitively did not occur."""
    BusinessDailyCreationUsage.objects.filter(
        pk=usage_id, used__gt=0,
    ).update(used=F("used") - 1)
