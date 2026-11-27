
import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from developer.models import ApiIdempotencyRecord


class IdempotencyConflictError(Exception):
    pass


class IdempotencyInProgressError(Exception):
    pass


def generate_request_hash(data):
    # Use consistent JSON formatting so equivalent payloads have the same hash.
    normalized = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def claim_idempotency_key(business_owner_id, key, method, path, data):
    request_hash = generate_request_hash(data)

    lookup = {
        "business_owner_id": business_owner_id,
        "idempotency_key": key,
        "method": method,
        "path": path,
    }

    try:
        record = ApiIdempotencyRecord.objects.create(
            **lookup,
            request_hash=request_hash,
            status="processing",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        return record, False

    except IntegrityError:
        record = ApiIdempotencyRecord.objects.get(**lookup)

        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                "This idempotency key was already used with a different request."
            )

        if record.status == "processing":
            raise IdempotencyInProgressError(
                "A request with this idempotency key is already being processed."
            )

        return record, True


def complete_idempotency_record(record, response):
    record.response_status = response.status_code
    record.response_body = json.loads(response.content)
    record.status = "completed"

    record.save(
        update_fields=[
            "response_status",
            "response_body",
            "status",
        ]
    )


def release_idempotency_record(record):
    # Allow retries when an operation fails before completion.
    record.delete()
