# SkillHub

**A mobile-first, two-sided service marketplace connecting verified tradespeople with customers in urban Cameroon.**

SkillHub lets service seekers discover, book, and pay verified artisans — plumbers, electricians, cleaners, carpenters, and more - through a trusted platform with escrow payments, a dispute resolution system, and a structured review and rating engine.

This repository contains the **Django REST API backend**.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [API Modules](#api-modules)
- [Prerequisites](#prerequisites)
- [Development Setup (Hybrid Mode)](#development-setup-hybrid-mode)
- [Full Docker Setup](#full-docker-setup)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
- [Background Tasks](#background-tasks)
- [Event System](#event-system)
- [Database Management](#database-management)
- [Deployment](#deployment)
- [Contributing](#contributing)

---

## Tech Stack

| Layer                  | Technology                                      |
| ---------------------- | ----------------------------------------------- |
| **Language**           | Python 3.11+                                    |
| **Web Framework**      | Django 4.2 LTS + Django REST Framework 3.15     |
| **Database**           | PostgreSQL 15+                                  |
| **Cache**              | Redis 7                                         |
| **Message Broker**     | RabbitMQ 3.13                                   |
| **Task Queue**         | Celery 5.4 + Celery Beat                        |
| **Event Bus**          | pika (AMQP direct)                              |
| **Authentication**     | JWT (SimpleJWT) + Google OAuth 2.0              |
| **Push Notifications** | Firebase Cloud Messaging (FCM)                  |
| **Email**              | Amazon SES (production) / MailHog (development) |
| **File Storage**       | Amazon S3 + CloudFront                          |
| **API Docs**           | OpenAPI 3.0 (drf-spectacular)                   |
| **Error Tracking**     | Sentry                                          |
| **Containerisation**   | Docker + Docker Compose                         |

---

## Architecture Overview

The backend follows a modular Django application structure where each domain is a self-contained app. Communication between modules happens through a **domain event system** rather than direct imports.

```
Mobile/Web App
    │
    ▼  HTTP / JWT
Django REST API (runserver / gunicorn)
    │
    ├── PostgreSQL  ←→  all models and queries
    ├── Redis       ←→  cache, Celery results, PIN verification tokens
    │
    └── publish_event() via pika
              │
              ▼
       RabbitMQ — skillhub.events exchange
              │
              ▼
       skillhub.notifications queue
              │
              ▼
       consume_notifications (management command)
              │
              ├── creates Notification DB records
              └── enqueues Celery tasks
                        │
                        ▼
               Celery Worker
                   ├── FCM push notifications
                   ├── SMTP email
                   └── escrow lifecycle tasks
```

**RabbitMQ serves two separate roles:**

- **Domain event bus** — pika publishes events from views and services into a topic exchange. A single `consume` process reads every event and routes it to the correct handler (push/email).
- **Celery task broker** — Celery uses RabbitMQ internally to queue and distribute background tasks across three queues: `default`, `notifications`, `payments`.

---

## Project Structure

```
boloconnect/
├── apps/
│   ├── accounts/          User auth, profiles,portfolio, KYC verification
│   ├── appointments/      Booking lifecycle, provider availability
│   ├── categories/        Service categories (hierarchical)
│   ├── disputes/          Dispute creation, evidence, admin resolution
│   ├── notifications/     Event publishing, push/email delivery, consumer
│   ├── payments/          Wallet, escrow, PIN, webhooks
│   └── reviews/           Ratings, summaries, admin moderation
│
├── docker/
│   ├── entrypoint.sh      Container startup (hybrid-aware waits)
│   ├── rabbitmq/
│   │   ├── definitions.json    RabbitMQ exchange + queue pre-declaration
│   │   └── rabbitmq.conf
│   ├── nginx/
│   │   └── nginx.conf
│   └── postgres/
│       └── init.sql
│
├── docker-compose.yml    Full Docker — all services
├── Makefile                   Developer workflow commands
├── requirements.txt
├── .env                       Local dev environment (not committed)
├── .env.docker                Full Docker environment (safe to commit)
└── EVENT_FLOW.md              Detailed event system documentation
```

---

## API Modules

| App             | Responsibility                                                                  | Key Models                                                                 |
| --------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `accounts`      | Registration, login, Google OAuth, email verification, KYC, profiles            | `User`, `SeekerProfile`, `ProviderProfile`, `KYCDocument`                  |
| `appointments`  | booking lifecycle (10 states), availability, reminders                          | `Appointment`, `ProviderAvailability`, `AppointmentStatusLog`              |
| `payments`      | Wallet PIN, wallet balance, escrow hold/release/refund, gateway webhooks        | `WalletPin`, `Wallet`, `Transaction`, `EscrowAccount`, `WithdrawalRequest` |
| `reviews`       | Dimension ratings, weighted averages, provider summaries, admin moderation      | `Review`, `ProviderReviewSummary`, `ReviewAuditLog`                        |
| `disputes`      | Dispute creation, evidence upload, admin adjudication, 7-year audit log         | `Dispute`, `DisputeEvidence`, `DisputeAuditLog`                            |
| `notifications` | Event publishing (pika), push/email dispatch (Celery), in-app notification feed | `Notification`, `EmailLog`                                                 |
| `categories`    | Service category hierarchy, provider category assignment                        | `Category`, `ProviderCategory`                                             |

---

## Prerequisites

**For hybrid development (recommended):**

- Python 3.11+
- PostgreSQL 15+ running locally
- Docker Desktop (for Redis, RabbitMQ)
- A Firebase project with a service account JSON (for push notifications)

**For full Docker:**

- Docker Desktop only

---

## Development Setup (Hybrid Mode)

In hybrid mode, Django and PostgreSQL run on your local machine. Redis, RabbitMQ, and MailHog run in Docker and expose their standard ports to `localhost`. This is the fastest setup for active development — no rebuilds on code changes.

### 1. Clone the repository

```bash
git https://github.com/LeonardAzah/skillhub.git
```

### 2. Create a virtual environment

```bash
pipenv sync
```

### 3. Set up the local database

```bash
# Create the database and user
make db-create

# Or manually:
createdb  skillhub_db
psql -c "CREATE USER skillhub WITH PASSWORD 'skillhub_dev_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE skillhub_db TO skillhub;"
```

### 4. Configure environment

The `.env` file is pre-configured for hybrid mode with all addresses pointing to `localhost`. Copy it and adjust if needed:

```bash
cp .env .env.local
```

> **Note:** `.env` is in `.gitignore` and will never be committed. `.env.docker` (for full Docker mode) is safe to commit and contains no secrets.

### 5. Apply migrations and seed data

```bash
make migrate
make seed-categories    # seeds 10 root + 35 sub-categories
```

### 6. (Optional) Configure Firebase

Download your Firebase service account JSON from the Firebase console and set the path in `.env`:

```
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-credentials.json
```

Without this, push notifications will be logged to the console but not delivered.

---

## Full Docker Setup

Runs every service in a container. Use for integration testing or when you want a production-like environment locally.

```bash
# Start everything
make full-up

# View logs for all services
make full-logs

# Run migrations inside the container
make full-migrate

# Stop everything
make full-down
```

Uses `docker-compose.yml` with `.env.docker` (service names as hostnames).

---

## Environment Variables

All variables are read from `.env` via `python-decouple`. None have hard-coded defaults in production.

### Django core

| Variable        | Example                    | Description                                        |
| --------------- | -------------------------- | -------------------------------------------------- |
| `SECRET_KEY`    | `your-50-char-secret`      | Django secret key — must be unique per environment |
| `DEBUG`         | `False`                    | Set `False` in production                          |
| `ALLOWED_HOSTS` | `api.skillhub.com`         | Comma-separated allowed hosts                      |
| `FRONTEND_URL`  | `https://app.skillhub.com` | Mobile/Web app base URL                            |
| `LOG_LEVEL`     | `INFO`                     | Logging level: DEBUG, INFO, WARNING, ERROR         |

### Database

| Variable      | Example                         | Description                                        |
| ------------- | ------------------------------- | -------------------------------------------------- |
| `DB_ENGINE`   | `django.db.backends.postgresql` | Database backend                                   |
| `DB_NAME`     | `skillhub_db`                   | Database name                                      |
| `DB_USER`     | `skillhub`                      | Database user                                      |
| `DB_PASSWORD` | `your-password`                 | Database password                                  |
| `DB_HOST`     | `localhost`                     | `localhost` for hybrid, `postgres` for full Docker |
| `DB_PORT`     | `5432`                          | PostgreSQL port                                    |

### Redis

| Variable                | Example                    | Description                     |
| ----------------------- | -------------------------- | ------------------------------- |
| `REDIS_URL`             | `redis://localhost:6379/0` | Rate limiting                   |
| `ORDERS_REDIS_URL`      | `redis://localhost:6379/1` | Cache backend base              |
| `REDIS_PASSWORD`        | _(empty in dev)_           | Redis AUTH password             |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery stores task results here |

### RabbitMQ

| Variable            | Example                                 | Description                  |
| ------------------- | --------------------------------------- | ---------------------------- |
| `RABBITMQ_URL`      | `amqp://guest:guest@localhost:5672/%2F` | Used by pika (event bus)     |
| `CELERY_BROKER_URL` | `amqp://guest:guest@localhost:5672/%2F` | Used by Celery (task broker) |
| `RABBITMQ_USER`     | `skillhub`                              | RabbitMQ username            |
| `RABBITMQ_PASS`     | `your-password`                         | RabbitMQ password            |
| `RABBITMQ_VHOST`    | `skillhub`                              | RabbitMQ virtual host        |

### Email

| Variable              | Example                              | Description                                  |
| --------------------- | ------------------------------------ | -------------------------------------------- |
| `EMAIL_HOST`          | `email-smtp.us-east-1.amazonaws.com` | SMTP host (`smtp.gmail.com` for development) |
| `EMAIL_PORT`          | `587`                                | SMTP port (`1025` for MailHog)               |
| `EMAIL_USE_TLS`       | `True`                               | Enable STARTTLS                              |
| `EMAIL_HOST_USER`     | `AKIAIOSFODNN7EXAMPLE`               | SMTP username                                |
| `EMAIL_HOST_PASSWORD` | `your-smtp-password`                 | SMTP password                                |
| `DEFAULT_FROM_EMAIL`  | `noreply@skillhub.com`               | Sender address                               |

### AWS (production)

| Variable                  | Description                                                 |
| ------------------------- | ----------------------------------------------------------- |
| `USE_S3`                  | `True` to serve media from S3, `False` for local filesystem |
| `AWS_ACCESS_KEY_ID`       | IAM access key                                              |
| `AWS_SECRET_ACCESS_KEY`   | IAM secret key                                              |
| `AWS_STORAGE_BUCKET_NAME` | S3 bucket for media files                                   |
| `AWS_S3_REGION_NAME`      | S3 region                                                   |
| `AWS_S3_CUSTOM_DOMAIN`    | CloudFront distribution domain                              |

### Third-party services

| Variable                    | Description                                   |
| --------------------------- | --------------------------------------------- |
| `GOOGLE_OAUTH2_CLIENT_ID`   | Google OAuth 2.0 client ID                    |
| `FIREBASE_CREDENTIALS_PATH` | Path to Firebase service account JSON         |
| `FAPSHI_WEBHOOK_URL`        | HMAC secret for verifying gateway webhooks    |
| `FAPSHI_API_USER`           | Fapshi api user to integrate a fapshi account |
| `FAPSHI_API_KEY`            | Fapshi api key to integrate a fapshi account  |

---

## Running the Application

Open four terminal windows with the virtual environment activated.

### Terminal 1 — Django development server

```bash
make serve
```

API available at `http://localhost:8000/api/v1/`  
Swagger UI at `http://localhost:8000/api/docs/`  
Django Admin at `http://localhost:8000/admin/`

### Terminal 2 — Celery worker

```bash
make worker
```

Processes the `default`, `notifications`, and `payments` queues. Handles push notifications, emails, and escrow lifecycle tasks.

### Terminal 3 — Notification consumer

```bash
make consumer
```

Reads domain events from RabbitMQ and dispatches them to push/email handlers. This is the single consumer for the entire application.

### Terminal 4 (optional) — Celery Beat

```bash
make beat
```

Required only if you want periodic tasks (appointment expiry, auto-release, review reminders) to fire automatically.

---

## API Reference

Base URL: `http://localhost:8000/api/v1/`

Interactive documentation: `http://localhost:8000/api/docs/`

### Authentication

| Method | Endpoint                               | Description                        |
| ------ | -------------------------------------- | ---------------------------------- |
| `POST` | `/auth/register`                       | Create account                     |
| `POST` | `/auth/login`                          | Login, returns JWT                 |
| `POST` | `/auth/google`                         | Google OAuth token exchange        |
| `POST` | `/auth/token/refresh`                  | Rotate access token                |
| `POST` | `/auth/logout`                         | Blacklist refresh token            |
| `GET`  | `/auth/verify-email/{token}`           | Confirm email address              |
| `POST` | `/auth/password/reset`                 | Request password reset             |
| `POST` | `/auth/password/reset/confirm/{token}` | Set new password                   |
| `GET`  | `/auth/me`                             | Current user info                  |
| `POST` | `/auth/onboarding`                     | Set account type (seeker/provider) |

### Profiles

| Method        | Endpoint                 | Description                 |
| ------------- | ------------------------ | --------------------------- |
| `GET`         | `/profile/providers`     | View all verified providers |
| `GET / PATCH` | `/profile/seeker`        | Seeker profile              |
| `GET`         | `/profile/provider/{id}` | Provider public profile     |
| `GET / PATCH` | `/profile/provider`      | Own provider profile        |
| `POST`        | `/profile/verify`        | Submit KYC documents        |
| `GET`         | `/profile/verify/status` | KYC status                  |

### Wallet PIN

The wallet PIN is a 4-digit code that authorises all financial actions. Set it once, then verify it before booking or withdrawing.

| Method | Endpoint                      | Description                                    |
| ------ | ----------------------------- | ---------------------------------------------- |
| `POST` | `/payments/wallet/pin/set`    | Set or change PIN                              |
| `POST` | `/payments/wallet/pin/verify` | Verify PIN → issues timed authorisation tokens |
| `GET`  | `/payments/wallet/pin/status` | PIN set? Locked? Active tokens?                |

### Wallet & Payments

| Method | Endpoint                                   | Description                           |
| ------ | ------------------------------------------ | ------------------------------------- |
| `GET`  | `/payments/wallet`                         | Balance and stats                     |
| `POST` | `/payments/wallet/cashin`                  | Initiate top-up (returns gateway URL) |
| `POST` | `/payments/wallet/cashout`                 | Request withdrawal (PIN required)     |
| `GET`  | `/payments/wallet/transactions`            | Transaction history                   |
| `GET`  | `/payments/wallet/transactions/{id}`       | Transaction detail                    |
| `GET`  | `/payments/wallet/escrow/{appointment_id}` | Escrow status                         |
| `POST` | `/payments/webhook`                        | Payment gateway callback              |

### Provider Discovery

| Method   | Endpoint                                    | Description                         |
| -------- | ------------------------------------------- | ----------------------------------- |
| `GET`    | `/appointments/providers/{id}/availability` | Available time slots (next 30 days) |
| `POST`   | `appointments/availability/{id}`            | Provider: block a time slot         |
| `DELETE` | `/appointments/availability/{id}`           | Provider: remove block              |

### Appointments

PIN must be verified via `/wallet/pin/verify/` before creating a booking.

| Method | Endpoint                      | Description                         |
| ------ | ----------------------------- | ----------------------------------- |
| `POST` | `/appointments`               | Create booking (PIN token required) |
| `GET`  | `/appointments`               | Own appointments                    |
| `GET`  | `/appointments/{id}`          | Appointment detail                  |
| `POST` | `/appointments/{id}/accept`   | Provider accepts                    |
| `POST` | `/appointments/{id}/reject`   | Provider rejects                    |
| `POST` | `/appointments/{id}/start`    | Provider starts job                 |
| `POST` | `/appointments/{id}/complete` | Provider completes + uploads proof  |
| `POST` | `/appointments/{id}/confirm`  | Seeker confirms → escrow released   |
| `POST` | `/appointments/{id}/cancel`   | Either party cancels                |
| `POST` | `/appointments/{id}/dispute`  | Seeker raises dispute               |

### Reviews

| Method        | Endpoint                          | Description                                         |
| ------------- | --------------------------------- | --------------------------------------------------- |
| `POST`        | `/reviews`                        | Submit review (seeker, CONFIRMED appointments only) |
| `GET`         | `/reviews`                        | Own review history                                  |
| `GET / PATCH` | `/reviews/{id}`                   | Review detail / edit (24h window)                   |
| `POST`        | `/reviews/{id}/response`          | Provider public response (30-day window)            |
| `GET`         | `/providers/{id}/reviews`         | Provider review list (paginated, sortable)          |
| `GET`         | `/providers/{id}/reviews/summary` | Aggregate stats + star histogram                    |

### Disputes

| Method | Endpoint                   | Description                   |
| ------ | -------------------------- | ----------------------------- |
| `GET`  | `/disputes`                | Own disputes                  |
| `GET`  | `/disputes/{id}`           | Dispute detail                |
| `POST` | `/disputes/{id}/statement` | Submit written statement      |
| `POST` | `/disputes/{id}/evidence`  | Upload evidence file (S3 URL) |

---

## Background Tasks

Celery Beat fires these tasks automatically on schedule:

| Schedule        | Task                                       | Description                                               |
| --------------- | ------------------------------------------ | --------------------------------------------------------- |
| Every 5 min     | `appointments.auto_release_escrow`         | COMPLETED → AUTO_RELEASED after 48h of seeker inaction    |
| Every 10 min    | `appointments.expire_pending_appointments` | PENDING → EXPIRED if provider does not respond within 24h |
| Every 30 min    | `appointments.send_appointment_reminders`  | Push reminders to both parties at T-24h and T-2h          |
| Every 6 h       | `reviews.send_review_reminders`            | Remind seekers to review at T+3 and T+10 days             |
| Daily 03:00 UTC | `accounts.prune_stale_device_tokens`       | Deactivate FCM tokens unused for 90+ days                 |

---

## Event System

Every significant action emits a domain event via `publish_event()`. A single `consume_notifications` process reads all events and routes them to the correct push and email handlers.

```
view/service calls publish_event(EventType.X, payload)
    └─► pika → RabbitMQ utils.events exchange
                └─► skillhub.notifications queue
                        └─► consume
                                └─► handlers.dispatch()
                                        ├─► Notification DB record
                                        ├─► send_push_notification (FCM) via Celery
                                        └─► send_email_notification (SMTP) via Celery
```

If RabbitMQ is unavailable, `publisher.py` falls back to a Celery task that calls `dispatch()` directly — no events are silently lost.

See [`EVENT_FLOW.md`](./EVENT_FLOW.md) for the complete per-module event reference.

---

## Database Management

```bash
make migrate            # apply all pending migrations
make makemigrations     # generate migrations for model changes
make db-reset           # drop + recreate + migrate (dev only — destroys all data)
make psql               # open psql shell to local database
```

---

## Useful Development Tools

```bash
make shell              # Django shell (ipython)
make redis-cli          # Connect to the Docker Redis instance
make redis-flush        # Clear all Redis keys (cache + sessions)
make rabbitmq-ui        # Open RabbitMQ management UI in browser
make rabbitmq-queues    # Show queue depths and consumer counts
make seed-categories    # Re-seed the service categories
make infra-status       # Check Docker infrastructure container status
```

---

## Deployment

The application is designed to deploy on **AWS ECS Fargate** behind an **Application Load Balancer**.

**Infrastructure required:**

- Amazon RDS PostgreSQL (Multi-AZ)
- Amazon ElastiCache Redis
- Amazon MQ for RabbitMQ (or self-managed on EC2)
- Amazon S3 (two buckets: private for KYC, media for portfolios)
- Amazon SES (verified sending domain)
- Amazon CloudFront (CDN for media)
- AWS Secrets Manager (all credentials)

**Container images:**

- `web` — gunicorn Django API
- `celery` — Celery worker (`--queues=default,notifications,payments`)
- `celery-beat` — Celery Beat scheduler
- `consumer` — `python manage.py consume`

**Deployment checklist:**

- [ ] Set `DEBUG=False` and `SECRET_KEY` to a cryptographically random value
- [ ] Set `ALLOWED_HOSTS` to your API domain
- [ ] Point `DATABASE_URL` to RDS
- [ ] Configure SES with verified domain + DKIM/SPF records
- [ ] Upload Firebase credentials to Secrets Manager
- [ ] Set `PAYMENT_WEBHOOK_SECRET` and configure gateway callback URL
- [ ] Enable `USE_S3=True` and configure both S3 buckets

---

## License

Proprietary — all rights reserved. See `LICENSE` for details.
