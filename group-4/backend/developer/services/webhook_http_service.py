
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit


MAX_PAYLOAD_BYTES = 256 * 1024


class WebhookHTTPError(Exception):
    """Raised when a webhook destination or HTTP request is unsafe."""


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a verified IP while preserving hostname TLS verification."""

    def __init__(self, hostname, ip_address, timeout):
        super().__init__(
            hostname,
            port=443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self.ip_address = ip_address

    def connect(self):
        raw_socket = socket.create_connection(
            (self.ip_address, 443),
            timeout=self.timeout,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


def validate_webhook_url(url):
    """Validate the destination and resolve its public IP addresses."""

    parsed = urlsplit(url)

    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise WebhookHTTPError("Invalid HTTPS webhook URL.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise WebhookHTTPError("Invalid webhook port.") from exc

    if port not in (None, 443):
        raise WebhookHTTPError("Webhook destination must use port 443.")

    hostname = parsed.hostname

    try:
        addresses = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise WebhookHTTPError("Webhook hostname could not be resolved.") from exc

    if not addresses:
        raise WebhookHTTPError("Webhook hostname has no IP addresses.")

    public_addresses = []

    for result in addresses:
        ip = ipaddress.ip_address(result[4][0])

        if not ip.is_global:
            raise WebhookHTTPError(
                "Webhook destination resolves to a non-public IP address."
            )

        public_addresses.append(str(ip))

    return parsed, public_addresses[0]


def secure_webhook_post(
    url,
    data=None,
    headers=None,
    timeout=5,
    allow_redirects=False,
):
    """Send a signed webhook to a validated public HTTPS destination."""

    if allow_redirects:
        raise WebhookHTTPError("Webhook redirects are not allowed.")

    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 10:
        raise WebhookHTTPError("Invalid webhook timeout.")

    parsed, ip_address = validate_webhook_url(url)

    body = data if data is not None else b""

    if isinstance(body, str):
        body = body.encode("utf-8")

    if not isinstance(body, bytes):
        raise WebhookHTTPError("Webhook payload must be bytes or text.")

    if len(body) > MAX_PAYLOAD_BYTES:
        raise WebhookHTTPError("Webhook payload is too large.")

    request_headers = dict(headers or {})
    request_headers["Content-Type"] = "application/json"

    # Prevent caller-controlled routing and framing headers.
    for key in request_headers:
        if key.lower() in (
            "host",
            "content-length",
            "transfer-encoding",
            "connection",
        ):
            raise WebhookHTTPError("Restricted webhook HTTP header.")

    path = parsed.path or "/"

    if parsed.query:
        path += "?" + parsed.query

    connection = PinnedHTTPSConnection(
        parsed.hostname,
        ip_address,
        timeout,
    )

    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers=request_headers,
        )

        response = connection.getresponse()
        response.read(4096)

        return WebhookHTTPResponse(response.status)

    finally:
        connection.close()


class WebhookHTTPResponse:
    """Minimal HTTP response compatible with webhook status handling."""

    def __init__(self, status_code):
        self.status_code = status_code
