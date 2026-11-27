import uuid
from django.db import models


class ApiKey(models.Model):
    """
    Stores API key metadata, permissions, and security constraints.
    The raw plaintext key is NEVER stored here—only its HMAC-SHA256 hash.
    """
    # Allowed status states for an API key
    STATUS_CHOICES = [
        ('active', 'Active'),        # Key is fully functional
        ('rotating', 'Rotating'),    # Key is in grace period during rotation
        ('revoked', 'Revoked'),      # Key has been permanently disabled
    ]

    # Primary Identifier & Ownership Links
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  #generates a unique UUID key ID
    business_owner_id = models.UUIDField(db_index=True)  # Links the key to the business owner user account
    created_by_id = models.UUIDField() # Stores the user ID team member or admin who created the key.

    #Display information and hashed secret
    name = models.CharField(max_length=64)
    environment = models.CharField(max_length=10, choices=[('live','Live'),('test','Test')]) #specifies whether the key is for live or test usage.
    key_prefix = models.CharField(max_length=24) #stores the first few char of the key for UI display
    key_hash = models.CharField(max_length=64, unique=True, db_index=True) #stores the HMAC-SHA256 hash of the key for security

    #Permission and access control rules
    scopes = models.JSONField(default=list) #stores the list of allowed permissions for the key
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    expires_at = models.DateTimeField(null=True, blank=True)
    ip_allowlist = models.JSONField(default=list, blank=True)
    rate_limit_override = models.JSONField(null=True, blank=True)

    #Tracking
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.CharField(max_length=45, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.UUIDField(null=True, blank=True)
    rotated_from_id = models.UUIDField(null=True, blank=True) # Tracks original key ID if rotated

    class Meta:
        db_table = 'api_keys' # Stores these records in MongoBD inside the api_keys collection

#Tracks administrative key events for security compliance and auditing.
#Records key creations, revocations, and permission changes.
class ApiAuditLog(models.Model):
    action = models.CharField(max_length=65) # Describes the action taken (e.g., "key.created", "key.revoked")
    business_owner_id = models.UUIDField(db_index=True) # Links the log entry to the business owner account
    actor_id = models.UUIDField() # User ID of the person performing the action
    actor_email = models.EmailField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    target_id = models.UUIDField() # ID of the target resource (e.g., API key)
    ip = models.CharField(max_length=45) # IP address where the action originated
    user_agent = models.CharField(max_length= 255, blank = True) # Browser or client details for context
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_audit_log'

#Logs API traffic metadata for observability and security analysis.
# Does NOT store full request/response bodies to protect payload privacy.
class ApiRequestLog(models.Model):
    request_id = models.CharField(max_length=64) # Unique UUID assigned to the request
    api_key_id = models.UUIDField(db_index=True)
    business_owner_id = models.UUIDField(db_index=True)
    method = models.CharField(max_length=10) # HTTP method
    path = models.CharField(max_length=255) # Endpoint URI path requested
    status = models.IntegerField() # HTTP response status code
    duration_ms = models.IntegerField()
    ip = models.CharField(max_length=45)
    idempotency_key = models.CharField(max_length=64, null=True, blank=True) # Unique key to identify and deduplicate requests
    idempotenct_replay = models.BooleanField(default=False) # Whether this request is a replay of a previous one
    error_code = models.CharField(max_length=64, null=True, blank=True) # Captures failure reasons if the request fails.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table= 'api_request_logs'


class ApiIdempotencyRecord(models.Model):
    """Stores request state and responses to prevent duplicate API operations."""

    business_owner_id = models.UUIDField(db_index=True)
    idempotency_key = models.CharField(max_length=64)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)

    request_hash = models.CharField(max_length=64)

    status = models.CharField(
        max_length=20,
        default="processing",
    )

    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "api_idempotency_records"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "business_owner_id",
                    "idempotency_key",
                    "method",
                    "path",
                ],
                name="unique_partner_idempotency_request",
            )
        ]

    def __str__(self):
        return f"{self.business_owner_id} - {self.idempotency_key}"


class AdminAuditIdentity(models.Model):
    """Link a Django admin account to a stable UUID for security logs."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    admin_user_id = models.CharField(
        max_length=64,
        unique=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_audit_identities"


class BusinessApiAccess(models.Model):
    """Store partner API access settings for a business."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    business_owner_id = models.UUIDField(unique=True)
    api_access_enabled = models.BooleanField(default=True)
    rate_limit_requests_per_minute = models.PositiveIntegerField(null=True, blank=True)
    pending_rate_limit_requests_per_minute = models.PositiveIntegerField(null=True, blank=True)
    daily_creation_quota = models.PositiveIntegerField(null=True, blank=True)
    rate_limit_effective_window = models.PositiveBigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.UUIDField(null=True, blank=True)

    def rate_limit_for_window(self, window):
        if (
            self.rate_limit_effective_window is not None
            and window >= self.rate_limit_effective_window
        ):
            return self.pending_rate_limit_requests_per_minute
        return self.rate_limit_requests_per_minute

    class Meta:
        db_table = "business_api_access"


class BusinessDailyCreationUsage(models.Model):
    """Track reserved and completed creations for a business on a UTC day."""

    id = models.CharField(primary_key=True, max_length=47)
    used = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "business_daily_creation_usage"


class WebhookSubscription(models.Model):
    """Store webhook subscriptions registered by partner businesses."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    business_owner_id = models.UUIDField(db_index=True)

    environment = models.CharField(
        max_length=10,
        choices=[("live", "Live"), ("test", "Test")],
    )

    # HTTPS endpoint that receives webhook notifications.
    endpoint_url = models.URLField(max_length=2048)

    # Delivery events selected by the partner business.
    subscribed_events = models.JSONField(default=list)

    # Store the signing secret in encrypted form.
    signing_secret_encrypted = models.TextField()

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "api_webhook_subscriptions"
        indexes = [
            models.Index(
                fields=["business_owner_id", "environment"],
            ),
        ]


class WebhookDelivery(models.Model):
    """Track webhook delivery attempts and retry status."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    subscription = models.ForeignKey(
        "WebhookSubscription",
        on_delete=models.CASCADE,
        related_name="deliveries",
    )

    event_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()

    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("delivered", "Delivered"),
            ("retrying", "Retrying"),
            ("failed", "Failed"),
        ],
        default="pending",
    )

    attempt_count = models.PositiveIntegerField(default=0)

    response_status_code = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    last_error = models.TextField(blank=True, default="")
    next_retry_at = models.DateTimeField(null=True, blank=True)

    # Identify which worker currently owns the delivery.
    claim_token = models.UUIDField(null=True, blank=True)

    # Allow abandoned claims to expire after a worker crashes.
    claim_expires_at = models.DateTimeField(null=True, blank=True)

    delivered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "api_webhook_deliveries"
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["event_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "event_id"],
                name="unique_webhook_subscription_event",
            ),
        ]



class BusinessAccount(models.Model):
    """Store a business identity used across dashboard and API operations."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    name = models.CharField(max_length=200)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "business_accounts"

    def __str__(self):
        return f"{self.name} ({self.email})"


class BusinessMembership(models.Model):
    """Associate an authenticated Django user with a business."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    user_id = models.CharField(max_length=64, unique=True)
    business = models.ForeignKey(
        BusinessAccount,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "business_memberships"

    def __str__(self):
        return f"{self.user_id} - {self.business.name}"

class Notification(models.Model):
    """Store persistent dashboard notifications for businesses and administrators."""

    LEVEL_CHOICES = [
        ("info", "Information"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("error", "Error"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # Business notifications are scoped to the assigned business.
    business_owner_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
    )

    # Administrator notifications are scoped to an individual dashboard user.
    admin_user_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
    )

    event_type = models.CharField(max_length=100)

    title = models.CharField(max_length=150)
    message = models.TextField()

    level = models.CharField(
        max_length=10,
        choices=LEVEL_CHOICES,
        default="info",
    )

    # Optional reference to the affected resource.
    target_id = models.UUIDField(null=True, blank=True)

    environment = models.CharField(
        max_length=10,
        choices=[("live", "Live"), ("test", "Test")],
        null=True,
        blank=True,
    )

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_notifications"
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["business_owner_id", "-created_at"],
                name="notif_business_created_idx",
            ),
            models.Index(
                fields=["business_owner_id", "is_read"],
                name="notif_business_read_idx",
            ),
            models.Index(
                fields=["admin_user_id", "-created_at"],
                name="notif_admin_created_idx",
            ),
            models.Index(
                fields=["admin_user_id", "is_read"],
                name="notif_admin_read_idx",
            ),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.title}"
