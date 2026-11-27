
import time

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from developer.models import WebhookDelivery
from developer.services.webhook_sender_service import (
    process_webhook_delivery,
)
from developer.services.webhook_http_service import secure_webhook_post


class Command(BaseCommand):
    help = "Process queued webhook deliveries and scheduled retries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process one batch and exit.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=10,
            help="Polling interval in seconds.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=20,
            help="Maximum deliveries to process per batch.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        batch_size = options["batch_size"]

        if interval < 1 or batch_size < 1:
            raise ValueError("Interval and batch size must be positive.")

        self.stdout.write("Webhook worker started.")

        while True:
            now = timezone.now()

            eligible = (
                Q(status="pending")
                | Q(
                    status="retrying",
                    next_retry_at__lte=now,
                )
                | Q(
                    status="processing",
                    claim_expires_at__lte=now,
                )
            )

            deliveries = list(
                WebhookDelivery.objects.filter(eligible)
                .order_by("created_at")[:batch_size]
            )

            for delivery in deliveries:
                try:
                    result = process_webhook_delivery(
                        delivery.id,
                        http_post=secure_webhook_post,
                    )
                    self.stdout.write(str(result))
                except Exception as exc:
                    self.stderr.write(
                        f"Delivery {delivery.id}: {exc}"
                    )

            if options["once"]:
                break

            time.sleep(interval)
