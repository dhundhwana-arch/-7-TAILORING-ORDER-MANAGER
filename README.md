# CUSTOM SHIRT STUDIO — Module 07/08: Tailoring Order Manager

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#installation)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688.svg)](#api-documentation)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Repository:** `dhundhwana-arch/-7-TAILORING-ORDER-MANAGER`  
**Project Owner:** DIVYESH BAMBHANIYA  
**Ecosystem Role:** Operational Tailoring Order Lifecycle & Workshop Workflow Backbone (Module 07 of 08)

---

## 1. Project Introduction & Module Responsibility

**CUSTOM SHIRT STUDIO** is an open-source custom clothing design and tailoring platform built around eight independent, interconnected modules. It serves a real small family tailoring workshop in **Dhundhwana, Khambha taluka, Amreli district, Gujarat**.

**Module 07 (`tailoring-order-manager` / `-7-TAILORING-ORDER-MANAGER`)** owns the **complete tailoring order lifecycle** from initial submission through review, official price quotation verification, customer confirmation, immutable snapshotting, workshop production stages (material preparation, cutting, stitching, finishing, quality inspection, rework), delivery/collection recording, and verified order completion.

### Strict Ownership Boundaries
- **Module 07 owns:** Order records, controlled lifecycle transitions, immutable confirmation snapshots, chronological audit trail, workshop tasks, configurable capacity awareness, sanitized customer tracking, and admin order/audit APIs.
- **Module 07 does NOT:** Calculate official prices independently (owned by **Module 05**), validate raw body measurements independently (owned by **Module 06**), duplicate fabric catalogue management (**Module 02**), render 2D/3D clothing previews (**Modules 03 & 04**), or promise automatic delivery dates.

---

## 2. Core Features

- **Controlled 16-State Lifecycle Engine:** Centralized state machine (`LifecycleEngine`) enforcing role permissions, business preconditions, hold/resume (`ON_HOLD`), quality-failure rework loops, cancellation rules, and verified completion conditions.
- **Immutable Versioned Confirmation Snapshots:** Preserves confirmed Module 05 quotation, Module 06 measurement profile version, Module 03 design configuration, and Module 02 / customer-supplied fabric details at confirmation time (`OrderSnapshot`). Protected at both service and SQLAlchemy ORM event layers against `UPDATE` and `DELETE`.
- **Append-Only Audit Trail:** Every lifecycle transition, update, task change, and note generates an immutable `OrderEvent` with actor ID, actor role, reason, and UTC timestamp.
- **Optimistic Concurrency Control:** Prevents lost updates across simultaneous requests/sessions using `Order.version` (`version_id_col`) and optional `expected_version` checks (`409 CONCURRENCY_CONFLICT`).
- **Idempotent Order Creation & Duplicate Submission Protection:** Supports `Idempotency-Key` headers/fields and `(order_source, submission_reference)` uniqueness constraints.
- **Realistic Tailoring Workflow Management:** Tracks `ORDER_REVIEW`, `MATERIAL_PREPARATION` (blocking `CUTTING` when cloth is missing), `CUTTING`, `STITCHING`, `FINISHING` (configurable checklist: buttons, cuffs, thread checks, ironing), and `QUALITY_CHECK` (`PASSED`, `PASSED_WITH_APPROVED_CORRECTION`, `FAILED_REWORK_REQUIRED`). Staff assignment is optional and never auto-invented.
- **Configurable Capacity & Workload Awareness:** Tracks workshop equipment availability and stage backlogs, surfacing warnings and resource conflicts for human review while enforcing `NO_AUTOMATIC_DELIVERY_PROMISE`.
- **Privacy-Safe Customer Tracking:** Requires owning customer authentication, staff authentication, or a cryptographic `tracking_token` (order reference alone never grants access). Strips internal notes, staff identifiers, and raw private body measurements.
- **Extensible Notification Outbox:** Persists `NotificationEvent` records decoupled from delivery providers (`MockNotificationProvider` used in development — zero real SMS/Email/WhatsApp sent).

---

## 3. Architecture Overview

```text
app/
├── main.py                  # FastAPI app factory, rate-limit middleware, safe error handlers
├── core/                    # Settings, enums, domain exceptions, HMAC auth & tracking tokens
├── db/                      # SQLAlchemy 2.0 engine, SQLite FK/WAL setup, session management
├── models/                  # Relational entities + ORM immutability & optimistic locking
├── adapters/                # Replaceable interfaces + mock/HTTP adapters for Modules 02-06
├── services/                # Order, Lifecycle, Snapshot, Workflow, Capacity, Tracking, Notification
├── schemas/                 # Pydantic v2 strict request/response contracts
└── api/v1/                  # REST routers: orders, lifecycle, workflow, tracking, capacity, admin
migrations/                  # Alembic schema migrations (`0001_initial`)
tests/                       # Comprehensive Pytest integration, security, and concurrency suite
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [ORDER_SCHEMA.md](ORDER_SCHEMA.md) for detailed design documentation.

---

## 4. Installation

### Prerequisites
- Python `3.11+`
- SQLite `3.35+` (bundled with Python for local dev/testing) or PostgreSQL `14+` for production deployment

### Setup
```bash
git clone https://github.com/dhundhwana-arch/-7-TAILORING-ORDER-MANAGER.git
cd -7-TAILORING-ORDER-MANAGER

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Configuration & Environment Variables

Copy `.env.example` to `.env` and adjust values for your environment:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development`, `testing`, `staging`, or `production` |
| `DATABASE_URL` | `sqlite:///./tailoring_orders.db` | SQLAlchemy database URL (`postgresql+psycopg://...` in production) |
| `AUTH_SECRET_KEY` | *(dev placeholder)* | **Required >=32 chars in production** for HMAC-SHA256 Bearer tokens |
| `TRACKING_TOKEN_SECRET` | *(dev placeholder)* | **Required >=32 chars in production** for keyed customer tracking token hashes |
| `AUTH_DEV_HEADER_ENABLED` | `true` | Allows `X-Actor-Id` / `X-Actor-Role` in local dev/test; **rejected in `production`** |
| `RATE_LIMIT_ENABLED` | `true` | Enables per-client sliding-window rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `120` | General API rate limit per minute |
| `TRACKING_RATE_LIMIT_PER_MINUTE` | `30` | Stricter rate limit for `/api/v1/tracking/{order_reference}` |
| `INTEGRATION_MODE` | `mock` | `mock` (synthetic test adapters) or `http` (live sibling services) |
| `NOTIFICATION_PROVIDER` | `mock` | `mock` (in-memory test capture) or `disabled` (never sends real external messages) |

---

## 6. Database Migrations & Running the Server

Apply Alembic database migrations:
```bash
.venv/bin/alembic upgrade head
```

Start the FastAPI server (bound to `0.0.0.0` for container/preview compatibility):
```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8007 --reload
```

Interactive OpenAPI documentation is served automatically at:
- Swagger UI: `http://localhost:8007/docs`
- ReDoc: `http://localhost:8007/redoc`
- Health Check: `http://localhost:8007/health`

---

## 7. Running Automated Tests

```bash
.venv/bin/pytest -v --cov=app --cov-report=term-missing
```

See [TESTING.md](TESTING.md) for full test coverage breakdown across Categories A–K.

---

## 8. Documentation Index

- [AUDIT_REPORT.md](AUDIT_REPORT.md) — Phase 01 repository & cross-module ecosystem audit
- [ARCHITECTURE.md](ARCHITECTURE.md) — Internal layered architecture & adapter boundaries
- [ORDER_SCHEMA.md](ORDER_SCHEMA.md) — Relational database tables, constraints, indexes, and snapshots
- [ORDER_LIFECYCLE.md](ORDER_LIFECYCLE.md) — Proposed 16-stage lifecycle definitions & operational rules
- [STATUS_TRANSITIONS.md](STATUS_TRANSITIONS.md) — Valid/invalid transitions, RBAC matrix, hold/resume, rework, completion
- [API_DOCUMENTATION.md](API_DOCUMENTATION.md) — Complete REST API reference for all 28 implemented endpoints
- [INTEGRATION.md](INTEGRATION.md) — Verified vs unverified cross-module contracts & Module 08 handoff
- [SECURITY.md](SECURITY.md) — Authentication, RBAC, privacy isolation, and security limitations
- [TESTING.md](TESTING.md) — Reproducible test commands and verified Pytest results
- [CHANGELOG.md](CHANGELOG.md) — Release and milestone log
- [CONTRIBUTING.md](CONTRIBUTING.md) — Development workflow and contribution guidelines

---

## 9. Known Limitations

1. **Upstream Sibling Contracts Pending Merge to `main`:** Inspection of `dhundhwana-arch` repositories showed that Modules 01, 04, 05, 06, and 08 currently have only `README.md` and `LICENSE` on `main`, while Module 02 (`fabric-catalog-system`) and Module 03 (`-3-2D-CLOTHING-DESIGNER`) have draft contracts on unmerged Arena development branches. Module 07 isolates all external calls behind replaceable `Protocol` adapters (`INTEGRATION_MODE=mock` by default).
2. **Proposed Lifecycle & RBAC Matrix:** The 16 lifecycle statuses and 4 human roles (`CUSTOMER`, `TAILOR`, `ADMIN`, `OWNER`) are implemented centrally and documented as proposed pending final sign-off across Modules 01 and 08.
3. **In-Memory Rate Limiter:** Sliding-window rate limiting runs per-process in memory; multi-worker production deployments should place Redis or an API gateway rate limiter in front of the service.
4. **Mock Notifications Only:** External SMS/Email/WhatsApp providers are intentionally unconfigured during development so zero real customer messages can be sent accidentally.

---

## License

Preserved under the repository's existing [MIT License](LICENSE) (`Copyright (c) 2026 dhundhwana-arch`).
