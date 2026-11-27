
import socket
from unittest.mock import patch, Mock

from django.test import SimpleTestCase

from developer.services.webhook_http_service import (
    WebhookHTTPError,
    validate_webhook_url,
    secure_webhook_post,
)


class WebhookSecurityTests(SimpleTestCase):

    def test_reject_http_url(self):
        with self.assertRaises(WebhookHTTPError):
            validate_webhook_url(
                "http://example.com/webhook"
            )

    @patch(
        "developer.services.webhook_http_service.socket.getaddrinfo"
    )
    def test_reject_localhost(self, mock_dns):
        mock_dns.return_value = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1", 443),
            )
        ]

        with self.assertRaises(WebhookHTTPError):
            validate_webhook_url(
                "https://localhost/webhook"
            )

    @patch(
        "developer.services.webhook_http_service.socket.getaddrinfo"
    )
    def test_reject_private_ip(self, mock_dns):
        mock_dns.return_value = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("192.168.1.10", 443),
            )
        ]

        with self.assertRaises(WebhookHTTPError):
            validate_webhook_url(
                "https://internal.example.com/webhook"
            )

    @patch(
        "developer.services.webhook_http_service.socket.getaddrinfo"
    )
    def test_reject_mixed_dns_addresses(self, mock_dns):
        mock_dns.return_value = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("8.8.8.8", 443),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("10.0.0.5", 443),
            ),
        ]

        with self.assertRaises(WebhookHTTPError):
            validate_webhook_url(
                "https://example.com/webhook"
            )

    def test_reject_nonstandard_port(self):
        with self.assertRaises(WebhookHTTPError):
            validate_webhook_url(
                "https://example.com:8080/webhook"
            )

    def test_reject_redirects(self):
        with self.assertRaises(WebhookHTTPError):
            secure_webhook_post(
                "https://example.com/webhook",
                data=b"{}",
                allow_redirects=True,
            )

    def test_reject_invalid_timeout(self):
        with self.assertRaises(WebhookHTTPError):
            secure_webhook_post(
                "https://example.com/webhook",
                timeout=30,
            )

    @patch(
        "developer.services.webhook_http_service.socket.getaddrinfo"
    )
    def test_accept_public_https_destination(self, mock_dns):
        mock_dns.return_value = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("8.8.8.8", 443),
            )
        ]

        parsed, ip_address = validate_webhook_url(
            "https://example.com/webhook"
        )

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(ip_address, "8.8.8.8")
