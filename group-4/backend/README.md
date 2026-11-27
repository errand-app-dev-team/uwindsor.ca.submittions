# Aerrand Partner API

A secure B2B API infrastructure for external partner integrations and delivery management.

## Project Overview

The Aerrand Partner API provides a dedicated integration layer that enables external businesses and marketplace partners to interact securely with the Aerrand delivery platform.

The project is developed as part of COMP 8967 – Internship/Project I at the University of Windsor in collaboration with WEtech Alliance and Aerrand.

The system is designed to support delivery operations while protecting Aerrand's existing business logic, customer information, and internal platform infrastructure.

## Implemented Features

### API Key Management

- Secure API key generation and authentication.
- HMAC-SHA256 hashing of API keys.
- Test and live environment separation.
- Scoped API permissions.
- API key expiration and revocation.
- Business-level API access controls.
- API key usage tracking and audit logging.

### Delivery Management

- Delivery quote calculation and persistence.
- Quote expiration management.
- Delivery creation and retrieval.
- Delivery tracking and cancellation.
- Drop-off information management.
- Proof of delivery retrieval.
- Delivery booking history.
- Request payload validation.
- Delivery stacking support.
- Payment-state validation.
- Integration interfaces for Aerrand's existing delivery and pricing services.

### Security and Reliability

- Business-level tenant isolation.
- API key authentication middleware.
- Scope-based authorization.
- Redis-backed rate limiting.
- Business-specific rate limit configuration.
- Daily delivery creation quotas.
- Idempotent request processing.
- API request logging.
- Administrative audit records.
- Environment-based secret management.
- CSRF protection and session-based dashboard authentication.

### Webhook Management

- Webhook subscription management.
- Event-based notification dispatch.
- HMAC-SHA256 webhook signing.
- Encrypted webhook signing secrets.
- Webhook URL validation.
- Background webhook processing.
- Automatic retries with exponential backoff.
- Delivery claiming and concurrency protection.
- Webhook delivery history and failure tracking.

### Administrative Dashboard

The integrated administrative dashboard provides centralized visibility and management of partner API operations.

Features include:

- Administrator authentication.
- Business account management.
- Business-level API access controls.
- API key monitoring and revocation.
- Rate limit and quota management.
- API request trends and usage statistics.
- Delivery booking history.
- Webhook failure monitoring.
- Persistent backend notification infrastructure.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend development |
| Django | Application framework |
| Django REST Framework | REST API infrastructure |
| MongoDB | Data persistence |
| Django MongoDB Backend | Django and MongoDB integration |
| Redis | Distributed caching and rate limiting |
| React | Administrative dashboard |
| TypeScript | Frontend development |
| Vite | Frontend development and build tooling |
| Git and GitHub | Version control and collaboration |

## Repository Structure

```text
.
├── admin-dashboard/       # Administrative dashboard
├── aerrands/              # Delivery and quote management
│   ├── migrations/
│   ├── services/
│   ├── tests/
│   ├── models.py
│   ├── validators.py
│   ├── views.py
│   └── urls.py
├── config/                # Django project configuration
├── developer/             # API security and management
│   ├── management/
│   ├── migrations/
│   ├── services/
│   ├── tests/
│   ├── models.py
│   ├── middleware.py
│   └── urls.py
├── mongo_migrations/      # MongoDB-compatible Django migrations
├── tests/
├── .env.example
├── .gitignore
├── manage.py
├── requirements.txt
└── README.md
```

## Local Development Setup

### 1. Prerequisites

Ensure the following tools are installed:

- Python compatible with the dependencies in `requirements.txt`.
- MongoDB.
- Redis for distributed rate limiting and production configuration.
- Node.js and npm for the administrative dashboard.
- Git.

### 2. Create a Virtual Environment

From the directory containing `manage.py`:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

For Windows:

```bash
.venv\Scripts\activate
```

### 3. Install Backend Dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a local `.env` file using the following command:

```bash
python - <<'PY'
import os
import secrets

from cryptography.fernet import Fernet

with open(
    ".env",
    "x",
    opener=lambda path, flags: os.open(path, flags, 0o600),
) as file:
    file.write(
        f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n"
    )
    file.write(
        f"API_KEY_HASH_PEPPER={secrets.token_hex(32)}\n"
    )
    file.write(
        f"WEBHOOK_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n"
    )
    file.write("DJANGO_DEBUG=True\n")
    file.write("ENABLE_DEMO_QUOTES=False\n")

print("Local environment configuration created.")
PY
```

This command generates private development credentials and refuses to overwrite an existing `.env` file.

The available configuration variables include:

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django application security |
| `API_KEY_HASH_PEPPER` | Secure API key hashing |
| `WEBHOOK_ENCRYPTION_KEY` | Encryption of webhook signing secrets |
| `DJANGO_DEBUG` | Development mode configuration |
| `DJANGO_ALLOWED_HOSTS` | Permitted application hosts |
| `ENABLE_DEMO_QUOTES` | Enables simulated quote calculation |
| `REDIS_URL` | Redis connection configuration |
| `AERRAND_PRICING_ADAPTER_CLASS` | Existing Aerrand pricing integration |
| `EMAIL_HOST` | SMTP server configuration |
| `EMAIL_PORT` | SMTP server port |
| `EMAIL_HOST_USER` | SMTP authentication username |
| `EMAIL_HOST_PASSWORD` | SMTP authentication password |
| `DEFAULT_FROM_EMAIL` | Default sender address |

Keep generated secrets private and stable. Never commit the `.env` file or expose its contents.

Changing the API key hash pepper invalidates existing API key hash comparisons. Changing the webhook encryption key without migrating existing encrypted data may prevent stored webhook secrets from being decrypted.

### 5. Configure MongoDB

Ensure MongoDB is installed and running.

The default local database configuration is:

```text
Host: localhost
Database: aerrand_partner_api
```

Database settings are defined in `config/settings.py`.

### 6. Configure Redis

For Redis-backed caching and rate limiting, add the following to the local `.env` file:

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

Ensure the Redis server is running.

Local development supports an in-memory cache fallback when Redis is not configured. Production configuration requires Redis.

### 7. Apply Database Migrations

```bash
python manage.py migrate
```

Verify the Django configuration:

```bash
python manage.py check
```

### 8. Create an Administrator

```bash
python manage.py createsuperuser
```

Follow the prompts to configure an administrator account.

### 9. Start the Backend Server

```bash
python manage.py runserver
```

The backend will be available at:

```text
http://127.0.0.1:8000
```

## Administrative Dashboard Setup

Open a separate terminal and navigate to the integrated administrative dashboard:

```bash
cd admin-dashboard
```

Install frontend dependencies:

```bash
npm ci
```

Start the development server:

```bash
npm run dev
```

The dashboard is normally available at:

```text
http://127.0.0.1:5173
```

Keep the Django backend running while using the dashboard.

To generate a frontend production build:

```bash
npm run build
```

## Partner API

The partner-facing REST API uses the `/v1` namespace.

### Delivery and Quote Operations

| Method | Endpoint | Description |
|---|---|---|
| POST | `/v1/quotes` | Request a delivery quote |
| GET | `/v1/quotes/{quote_id}` | Retrieve an existing quote |
| POST | `/v1/aerrands` | Create a delivery request |
| GET | `/v1/aerrands` | List delivery requests |
| GET | `/v1/aerrands/{aerrand_id}` | Retrieve delivery details |

Additional operations support delivery tracking, cancellation, drop-off management, and proof of delivery.

The complete route definitions are maintained in:

- `config/urls.py`
- `aerrands/urls.py`
- `developer/urls.py`

### API Authentication

Partner requests require a valid API key with the appropriate permissions.

API keys are associated with a business account and an environment. Authentication and authorization checks enforce business isolation and prevent unauthorized access to delivery records.

API key secrets are generated securely and stored as hashes rather than plaintext.

### Idempotency

Supported write operations use idempotency controls to prevent duplicate processing when a partner retries a request.

### Rate Limiting

API requests are subject to rate limits and applicable business-level restrictions. Redis supports shared rate limit state across application processes.

## Webhook Processing

Webhook subscriptions allow partners to receive event-based notifications associated with delivery operations.

The webhook infrastructure supports signed payloads, encrypted signing secrets, retry scheduling, concurrency protection, and delivery failure tracking.

Run the webhook processing command from the backend directory:

```bash
python manage.py process_webhooks
```

Production deployment should configure an appropriate background execution mechanism for webhook processing.

## Automated Testing

The project includes automated tests covering:

- API key generation, authentication, and revocation.
- Scoped permissions and tenant isolation.
- Rate limiting and request logging.
- Business API access controls.
- Quote validation and persistence.
- Delivery creation and retrieval.
- Delivery stacking and payment-state validation.
- Idempotent request processing.
- Webhook subscriptions, signing, delivery, and retries.
- Administrative operations.
- Persistent notifications.

Run the complete backend test suite:

```bash
python manage.py test
```

Run delivery-related tests:

```bash
python manage.py test aerrands
```

Run developer and security tests:

```bash
python manage.py test developer
```

Run webhook tests:

```bash
python manage.py test developer.tests.webhook
```

Ensure the required local database and environment configuration are available before running the tests.

## Integration with Aerrand

The Partner API separates external partner operations from Aerrand's existing internal delivery and pricing services through dedicated integration interfaces.

The integration design aims to:

- Reuse existing Aerrand business logic and delivery models.
- Avoid duplicating core platform functionality.
- Maintain server-side control over pricing.
- Preserve business and environment isolation.
- Support integration with existing delivery and payment workflows.

## Current Project Status

The Partner API infrastructure, security mechanisms, delivery interfaces, webhook processing, administrative dashboard, and automated testing framework have been implemented.

Remaining integration activities include:

- Connecting the existing Aerrand production pricing engine.
- Connecting and validating existing delivery execution services.
- Verifying prepaid wallet and payment workflows against the existing platform.
- Validating delivery lifecycle events and webhook dispatch against the integrated platform.
- Conducting end-to-end testing using Aerrand's staging environment and representative test data.
- Finalizing production deployment configuration.

Simulated quote calculation is available for controlled development and testing when explicitly enabled. It is not intended to replace Aerrand's production pricing logic.

## Security Considerations

- Never commit API keys, passwords, environment files, or private encryption keys.
- Disable Django debug mode in production.
- Configure trusted hosts and HTTPS for production deployment.
- Use Redis for distributed rate limiting.
- Restrict administrative access to authorized users.
- Maintain separate test and live environments.
- Protect webhook signing secrets and validate webhook destinations.
- Use secure environment-specific database and email configurations.

## Project Team

**Group 4**

Master of Applied Computing – University of Windsor

| Team Member |
|---|
| Rabindra Pangeni |
| Dipesh Adhikari |
| Peter Olusegun-Ebode |
| Sudina KC |

## Academic and Industry Collaboration

- **Course:** COMP 8967 – Internship/Project I
- **Institution:** University of Windsor
- **Program:** Master of Applied Computing
- **Project:** Project Pitch Competition
- **Industry Collaboration:** WEtech Alliance
- **Business Partner:** Aerrand
- **Business Challenge:** Aerrand Partner API Infrastructure

---

Developed by Group 4 to support secure, reliable, and scalable partner integrations with the Aerrand delivery platform.
