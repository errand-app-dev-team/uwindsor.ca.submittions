from django.db import models
import uuid

class ApiQuote(models.Model):
    id = models.CharField(
        primary_key=True,
        max_length=64,
    )

    business_owner_id = models.CharField(
        max_length=64,
        db_index=True,
    )

    api_key_id = models.CharField(
        max_length=64,
        db_index=True,
    )

    environment = models.CharField(
        max_length=10,
    )

    inputs_hash = models.CharField(
        max_length=64,
        db_index=True,
    )

    inputs = models.JSONField()

    route_km = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    breakdown = models.JSONField()

    total = models.CharField(
        max_length=32,
    )

    resolved_stops = models.JSONField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    expires_at = models.DateTimeField()

    class Meta:
        db_table = "api_quotes"


class ApiBooking(models.Model):
    """Stores a partner booking until it can be synchronized with Aerrand."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    business_owner_id = models.CharField(
        max_length=64,
        db_index=True,
    )

    api_key_id = models.CharField(
        max_length=64,
    )

    environment = models.CharField(
        max_length=10,
        db_index=True,
    )

    quote = models.ForeignKey(
        ApiQuote,
        on_delete=models.PROTECT,
        related_name="bookings",
    )

    batch_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
    )

    stop_index = models.PositiveSmallIntegerField(
        default=0,
    )

    batch_size = models.PositiveSmallIntegerField(
        default=1,
    )

    external_reference = models.CharField(
        max_length=128,
        null=True,
        blank=True,
    )

    delivery_code = models.CharField(
        max_length=6,
    )

    status = models.CharField(
        max_length=32,
        default="pending_payment",
        db_index=True,
    )

    payment_status = models.CharField(
        max_length=20,
        default="unpaid",
    )

    payment_method = models.CharField(
        max_length=32,
        default="invoice",
    )

    pickup = models.JSONField()

    dropoff = models.JSONField()

    vehicle_type = models.CharField(
        max_length=20,
    )

    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    pricing = models.JSONField(
        default=dict,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    tracking = models.JSONField(
        default=dict,
        blank=True,
    )

    proof_of_delivery = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "api_bookings"
        indexes = [
            models.Index(
                fields=["business_owner_id", "environment", "created_at"],
                name="api_booking_owner_idx",
            ),
            models.Index(
                fields=["batch_id", "stop_index"],
                name="api_booking_batch_idx",
            ),
        ]

    def __str__(self):
        return str(self.id)


class ApiBookingHistory(models.Model):
    """Confirmed API creations retained independently of idempotency expiry."""

    claim_id = models.CharField(max_length=64, unique=True)
    business_owner_id = models.UUIDField(db_index=True)
    environment = models.CharField(max_length=10)
    booking_id = models.TextField(blank=True)
    batch_id = models.TextField(blank=True)
    stop_ids = models.JSONField(default=list)
    external_reference = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
