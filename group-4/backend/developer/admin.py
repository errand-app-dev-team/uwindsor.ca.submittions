from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from urllib.parse import urlencode
from django.utils import timezone
from .models import ApiKey, ApiAuditLog, ApiRequestLog


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    # Columns displayed in the list of API-key records.
    list_display = (
        "name",
        "business_owner_id",
        "key_prefix",
        "environment",
        "show_scopes",
        "show_key_status",
        "created_at",
        "expires_at",
        "last_used_at",
    )

    # Fields an administrator can search by.
    search_fields = ("name", "key_prefix")

    # Filters shown beside the list.
    list_filter = ("environment", "status")

    # Show recently created keys first.
    ordering = ("-created_at",)

    # These are the only fields shown when opening a record.
    # The full secret is not stored; the hash is not shown here.
    fields = (
        "id",
        "name",
        "business_owner_id",
        "key_prefix",
        "environment",
        "scopes",
        "status",
        "created_at",
        "expires_at",
        "last_used_at",
        "request_history_link",
        "audit_history_link",
    )

    # Every displayed field is read-only.
    readonly_fields = fields

    @admin.display(description="Permissions")
    def show_scopes(self, obj):
        # Join the saved permissions into text for the table.
        return ", ".join(obj.scopes) if obj.scopes else "None"

    @admin.display(description="Status")
    def show_key_status(self, obj):
        # Keep a revoked key labelled as revoked.
        if obj.status == "revoked":
            return "Revoked"

        # An active key can have passed its expiry time.
        if (
            obj.status == "active"
            and obj.expires_at
            and obj.expires_at <= timezone.now()
        ):
            return "Expired"

        # For other cases, show the saved status.
        return obj.get_status_display()



    @admin.display(description="Request history")
    def request_history_link(self, obj):
        # Find the Django admin page that lists API request logs.
        log_page = reverse("admin:developer_apirequestlog_changelist")

        # Filter the logs so we see requests for this API key.
        filters = urlencode({"api_key_id__exact": str(obj.id)})

        # Make a clickable link to the filtered page.
        return format_html(
            '<a href="{}?{}">View requests for this key</a>',
            log_page,
            filters,
        )

    @admin.display(description="Security history")
    def audit_history_link(self, obj):
        # Find the page that lists security audit events.
        audit_page = reverse("admin:developer_apiauditlog_changelist")

        # Show events whose target is this API key.
        filters = urlencode({"target_id__exact": str(obj.id)})

        # Create a clickable link to the filtered event list.
        return format_html(
            '<a href="{}?{}">View security events for this key</a>',
            audit_page,
            filters,
        )

    def has_add_permission(self, request):
        # Creating keys will be handled by a separate secure flow.
        return False

    def has_change_permission(self, request, obj=None):
        # Records cannot be changed from this admin page.
        return False

    def has_delete_permission(self, request, obj=None):
        # Records cannot be deleted from this admin page.
        return False

@admin.register(ApiAuditLog)
class ApiAuditLogAdmin(admin.ModelAdmin):
    # Show the main details of each security event.
    list_display = (
        "show_action",
        "business_owner_id",
        "actor_id",
        "target_id",
        "timestamp",
    )

    # Show the newest security events first.
    ordering = ("-timestamp",)

    @admin.display(description="Security event")
    def show_action(self, obj):
        # Read the event name saved in the database.
        action = obj.action

        # Give common events a more readable name.
        explanations = {
            "key.created": "API key created",
            "key.revoked": "API key revoked",
        }

        # If we don't recognise the event, show its original name.
        return explanations.get(action, action)

    # The detail page displays these fields without allowing edits.
    fields = (
        "action",
        "business_owner_id",
        "actor_id",
        "target_id",
        "timestamp",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        # Audit records should be created by the application.
        return False

    def has_change_permission(self, request, obj=None):
        # Existing audit records cannot be edited here.
        return False

    def has_delete_permission(self, request, obj=None):
        # Existing audit records cannot be deleted here.
        return False

@admin.register(ApiRequestLog)
class ApiRequestLogAdmin(admin.ModelAdmin):
    # Columns shown in the request-log table.
    list_display = (
        "created_at",
        "business_owner_id",
        "api_key_id",
        "method",
        "path",
        "show_result",
        "duration_ms",
        "show_error",
    )

    # Show the newest API requests first.
    ordering = ("-created_at",)

    @admin.display(description="Result")
    def show_result(self, obj):
        # obj is one saved API request log.
        status = obj.status

        # Explain common response codes in simple words.
        explanations = {
            200: "Success",
            201: "Created successfully",
            400: "Invalid request",
            401: "Authentication failed",
            403: "Permission denied",
            404: "Not found",
            429: "Too many requests",
            503: "Service unavailable",
        }

        # If a code is not in the list, still show the number.
        explanation = explanations.get(status, "Other response")

        return f"{explanation} ({status})"

    @admin.display(description="Error")
    def show_error(self, obj):
        # Read the error code saved in this request log.
        error_code = obj.error_code

        # A successful request may have no error code.
        if not error_code:
            return "No error recorded"

        # Explain known error codes in simpler words.
        explanations = {
            "validation_error": "Invalid or missing information",
            "insufficient_scope": "Key does not have permission",
            "invalid_api_key": "Invalid API key",
        }

        # Keep unfamiliar codes visible so an admin can investigate them.
        return explanations.get(error_code, error_code)

    # Let an admin filter the table by method or response status.
    list_filter = ("method", "status")

    # Show only these fields on a record's detail page.
    fields = (
        "created_at",
        "request_id",
        "method",
        "path",
        "status",
        "duration_ms",
        "error_code",
    )

    # An admin can inspect these details but cannot edit them.
    readonly_fields = fields

    def has_add_permission(self, request):
        # The application creates request logs.
        return False

    def has_change_permission(self, request, obj=None):
        # Existing logs cannot be edited here.
        return False

    def has_delete_permission(self, request, obj=None):
        # Existing logs cannot be deleted here.
        return False
