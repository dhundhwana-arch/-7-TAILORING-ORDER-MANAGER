# PHASE 01 — REPOSITORY AUDIT & ARCHITECTURE PLAN

**Project:** CUSTOM SHIRT STUDIO  
**Module:** 07/08 — TAILORING ORDER MANAGER  
**Repository:** `dhundhwana-arch/-7-TAILORING-ORDER-MANAGER` (`https://github.com/dhundhwana-arch/-7-TAILORING-ORDER-MANAGER`)  
**Default Target Branch:** `main` (`d83caf53242005bbcc4e964658e8b5749a109d0e`)  
**Development Branch:** `arena/77121da8-7-tailoring-order-manager`  
**Audit Date:** 2026-11-18 (UTC)  

---

## 1. Repository Audit Report

| Inspection Item | Verified Result |
|---|---|
| Repository URL | `https://github.com/dhundhwana-arch/-7-TAILORING-ORDER-MANAGER.git` |
| Repository Owner | `dhundhwana-arch` (Project Owner: Divyesh Bambhaniya) |
| Naming Note | Master prompt refers to `tailoring-order-manager`; actual GitHub repository slug is `-7-TAILORING-ORDER-MANAGER` |
| Default Branch | `main` |
| Current Working Branch | `arena/77121da8-7-tailoring-order-manager` (branched cleanly from `main` at `d83caf53242005bbcc4e964658e8b5749a109d0e`) |
| GitHub Permissions | `ADMIN` (`gh repo view` verified) — commits, branch push, and PR creation are supported; merging into `main` is withheld pending owner approval |
| Open / Closed Pull Requests | `0` (`[]`) |
| Remote Branches on `origin` | `main` only prior to this development branch |
| Existing Files | `LICENSE` (1,072 bytes, MIT License, Copyright (c) 2026 `dhundhwana-arch`), `README.md` (28 bytes: `# -7-TAILORING-ORDER-MANAGER`) |
| Git Commit History | Single commit `d83caf53242005bbcc4e964658e8b5749a109d0e` (`Initial commit`, 2026-11-16 09:44:45 +0530, 2 files, 22 insertions) |
| Runtime Environment | Python 3.11.2, `venv`, SQLite 3.40.1, Node.js v22.22.3 |

---

## 2. Existing Functionality Report

- **Existing Source Code:** None. No backend, frontend, scripts, or configuration files exist in `main`.
- **Existing Database Schema / Migrations:** None.
- **Existing API Endpoints:** None.
- **Existing Automated Tests:** None.
- **Existing Dependencies:** None.
- **Existing Security Issues in Code:** None in repo (greenfield repository), though authentication, RBAC, customer isolation, optimistic locking, and secret-free configuration must be designed from the ground up.
- **Preserved Work:** `LICENSE` (MIT License) is preserved verbatim without modification.

---

## 3. Cross-Module Ecosystem Inspection (`dhundhwana-arch`)

All sibling repositories under `dhundhwana-arch` were inspected via the GitHub API on 2026-11-18:

| Module | Actual GitHub Repository | `main` Branch State | Unmerged Development Branch | Contract Status |
|---|---|---|---|---|
| 01 | `dhundhwana-arch/custom-shirt-studio` | `LICENSE`, `README.md` only | None | **UNVERIFIED / PROPOSED** |
| 02 | `dhundhwana-arch/fabric-catalog-system` | `LICENSE`, `README.md` only | `arena/9fb44bec-fabric-catalog-system` (Python/FastAPI/SQLAlchemy) | **DRAFT INSPECTED** (`FAB-NNN`, `FVAR-NNN`, `sourcing_method`, `/api/v1/fabrics/by-code/{id}`, `/api/v1/variants/by-code/{id}`) — not yet merged to `main` |
| 03 | `dhundhwana-arch/-3-2D-CLOTHING-DESIGNER` | `LICENSE`, `README.md` only | `arena/bbe947ab-3-2d-clothing-designer` (TypeScript/React) | **DRAFT INSPECTED** (`DSG-...`, `schema_version: "1.0.0"`, `product_type`, `fabric.fabric_id`, `components` with `collar`, `sleeves`, `cuffs`, `pockets`, `buttons`, `thread`, `fit`, `color_hex`) — not yet merged to `main` |
| 04 | `dhundhwana-arch/-4-CLOTHING-PREVIEW` | `LICENSE`, `README.md` only | None | **UNVERIFIED / PROPOSED** |
| 05 | `dhundhwana-arch/clothing-price-engine` | `LICENSE`, `README.md` only | None | **UNVERIFIED / PROPOSED** |
| 06 | `dhundhwana-arch/-6-MEASUREMENT-GUIDE` | `LICENSE`, `README.md` only | None | **UNVERIFIED / PROPOSED** |
| 07 | `dhundhwana-arch/-7-TAILORING-ORDER-MANAGER` | `LICENSE`, `README.md` only | `arena/77121da8-7-tailoring-order-manager` (this branch) | **OWNER OF ORDER LIFECYCLE** |
| 08 | `dhundhwana-arch/-8-DASHBOARD-` | `LICENSE`, `README.md` only | None | **UNVERIFIED / PROPOSED** (consumes Module 07 Admin APIs) |

**Integration Boundary Decision:**
- Because none of Modules 01–06 or 08 have merged contracts on `main`, Module 07 implements **clean, replaceable Python Protocol/ABC adapter interfaces** (`PricingAdapter`, `MeasurementAdapter`, `FabricCatalogAdapter`, `DesignConfigAdapter`, `PreviewReferenceAdapter`, `AuthAdapter`, `NotificationProvider`).
- Module 02 and Module 03 adapters accept both generic references and the draft schemas observed in their active Arena branches (`FAB-NNN`/`FVAR-NNN` including customer-supplied fabric mode, and `DSG-...` `schema_version` `1.0.0` component dictionaries) without hardcoding unapproved rigid constraints.
- Mock/in-memory fixture adapters are strictly isolated behind configuration (`INTEGRATION_MODE=mock` for development/testing vs HTTP/external adapters when sibling services are deployed) and clearly labeled.

---

## 4. Proposed Technical Architecture

Consistent with Module 02 (`fabric-catalog-system`) and Section 20 of the specification:
- **Language & Framework:** Python 3.11 + FastAPI + Pydantic v2.
- **Persistence & ORM:** SQLAlchemy 2.0 (typed declarative models) supporting **PostgreSQL** in production (`DATABASE_URL=postgresql+psycopg://...`) and **SQLite** with foreign-key enforcement (`PRAGMA foreign_keys=ON`) for zero-dependency local execution and automated integration tests.
- **Database Migrations:** Alembic migration configuration and initial baseline migration script (`migrations/`), plus deterministic schema initialization helper for test suites.
- **Architecture Layers:**
  1. `app/core/` — Configuration (`pydantic-settings`), structured logging, domain exceptions, security/authentication adapter & RBAC dependencies, rate limiter.
  2. `app/models/` — Relational SQLAlchemy 2.0 entities with constraints, indexes, foreign keys, and optimistic locking (`version`).
  3. `app/schemas/` — Versioned Pydantic v2 request/response schemas and pagination envelopes.
  4. `app/adapters/` — Replaceable integration boundaries for Module 02 (Fabric), Module 03 (2D Design), Module 04 (3D Preview), Module 05 (Price Engine), Module 06 (Measurement Guide), Authentication, and Notification delivery.
  5. `app/services/` — Transaction-safe domain services:
     - `OrderService` (creation, validation, idempotency, submission, customer confirmation)
     - `LifecycleService` (centralized transition engine, optimistic locking, hold/resume, rework, cancellation, completion evidence checks)
     - `SnapshotService` (immutable versioned confirmation snapshots of price, measurement, design, and fabric)
     - `WorkflowService` (tailoring stages: review, material preparation, cutting, stitching, finishing subtasks, quality inspection, rework, delivery/completion)
     - `CapacityService` (configurable workshop resources, non-guaranteed reference capacity, workload counters, warning & conflict indicators — never auto-promising delivery dates)
     - `TrackingService` (customer-isolated order tracking & sanitized timeline without internal notes or private measurements)
     - `NotificationService` (transactional notification event persistence + pluggable mock provider, zero real messages sent)
  6. `app/api/v1/` — Versioned REST routers (`orders`, `lifecycle`, `workflow`, `tracking`, `capacity`, `admin`, `notifications`, `health`).

---

## 5. Proposed Database Design

Core relational tables (all timestamps UTC ISO-8601, monetary amounts `Numeric(12, 2)` — never binary floats):
1. `orders` — `id` (PK), `public_order_ref` (`ORD-...`, unique, indexed), `idempotency_key` (unique per customer/source, nullable), `submission_reference` (indexed), `customer_ref` (indexed), `current_status` (indexed), `previous_hold_status` (for deterministic `ON_HOLD` resume), `order_source`, `currency`, `is_urgent` (only when authorized), `measurement_ref`, `quotation_ref`, `quoted_amount`, `customer_instructions`, `tracking_token_hash` (HMAC/SHA-256 hash for secondary tracking verification), `quality_status`, `delivery_method`, `delivery_reference`, `delivered_at`, `completion_evidence`, `completed_at`, `cancelled_at`, `cancellation_reason`, `cancelled_by`, `version` (optimistic locking integer, starts at `1`), `created_at`, `updated_at`.
2. `order_items` — `id` (PK), `order_id` (FK `orders.id`), `line_number`, `garment_type` (`shirt`, `pant`, `shirt_and_pant_set`, `kurta`, etc.), `quantity` (`CHECK quantity > 0`), `design_ref`, `design_version`, `fabric_ref`, `fabric_variant_ref`, `fabric_source` (`CUSTOMER_SUPPLIED` | `BUSINESS_INVENTORY`), `preview_3d_ref`, `customization_data` (JSON), `item_notes`.
3. `order_snapshots` — Append-only immutable snapshots (`id`, `order_id` FK, `snapshot_version`, `snapshot_type`, `design_snapshot` JSON, `fabric_snapshot` JSON, `measurement_snapshot` JSON, `quotation_snapshot` JSON, `confirmed_amount`, `currency`, `confirmed_by`, `created_at`, unique `(order_id, snapshot_version)`). Protected at service and ORM event layer against `UPDATE` and `DELETE`.
4. `order_events` — Append-only audit log (`id`, `event_ref`, `order_id` FK, `event_type`, `previous_status`, `new_status`, `actor_id`, `actor_role`, `reason`, `customer_visible` boolean, `customer_message`, `metadata_json`, `created_at`). Protected against mutation/deletion.
5. `workflow_tasks` — Operational tasks (`id`, `task_ref`, `order_id` FK, `stage`, `task_type`, `task_status`, `assigned_staff_ref` nullable, `is_rework` boolean, `checklist_json` for finishing/inspection items, `inspection_result` nullable, `missing_materials_notes`, `notes`, `started_at`, `completed_at`, `created_at`, `updated_at`).
6. `order_notes` — Separated visibility (`id`, `order_id` FK, `visibility` (`INTERNAL` | `CUSTOMER_VISIBLE`), `author_id`, `author_role`, `content`, `created_at`). Customer endpoints strictly filter `visibility == 'CUSTOMER_VISIBLE'`.
7. `capacity_settings` — Configurable workshop resource profile (`id`, `config_key` unique, `sewing_machines_count`, `overlock_machines_count`, `irons_count`, `cutting_tables_count`, `reference_sets_per_day`, `max_active_production_orders_warning`, `max_stage_orders_warning`, `operating_notes`, `is_guaranteed_capacity` always `False` unless explicitly verified, `updated_by`, `updated_at`). No hardcoded unchangeable business limits.
8. `notification_events` — Outbox/event log (`id`, `notification_ref`, `order_id` FK, `event_type`, `channel`, `recipient_ref`, `payload_json`, `delivery_status` (`PENDING`, `SENT_MOCK`, `FAILED`, `SKIPPED`), `provider_name`, `error_message`, `created_at`, `processed_at`).

---

## 6. Lifecycle & Transition Design (Proposed, Centralized)

**Implemented Proposed States (16 states):**
`DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `QUOTE_PENDING`, `AWAITING_CUSTOMER_CONFIRMATION`, `CONFIRMED`, `MATERIAL_PREPARATION`, `CUTTING`, `STITCHING`, `FINISHING`, `QUALITY_CHECK`, `READY`, `DELIVERED`, `COMPLETED`, `CANCELLED`, `ON_HOLD`.

**Key Enforcement Rules:**
- Submitting an order moves `DRAFT -> SUBMITTED` (or creates directly in `SUBMITTED` if submitted from Module 01), **never** straight to `CONFIRMED`.
- Entering `CONFIRMED` requires: (a) verified valid non-expired quotation from Module 05 adapter, (b) verified validated measurement profile from Module 06 adapter, (c) verified design & fabric references (or customer-supplied fabric declaration), (d) explicit customer price confirmation, and (e) atomic creation of an immutable `OrderSnapshot`.
- `QUALITY_CHECK` failure cannot transition to `READY`; it records inspection failure and transitions back to `CUTTING`, `STITCHING`, or `FINISHING` as authorized rework with rework `WorkflowTask` creation.
- `ON_HOLD` records `previous_hold_status` + mandatory hold reason, and resumes cleanly to that prior active stage (or `UNDER_REVIEW` if re-evaluation is required).
- `CANCELLED` is allowed cleanly prior to production (`DRAFT` through `AWAITING_CUSTOMER_CONFIRMATION`); once confirmed or in production (`CONFIRMED` through `READY`), cancellation requires `ADMIN`/`OWNER` authorization and explicit reason; `DELIVERED` and `COMPLETED` orders cannot be cancelled.
- `COMPLETED` cannot be reached from `QUALITY_CHECK` or `READY`; the order must first be `DELIVERED` with recorded delivery/collection timestamp and reference, and `COMPLETED` requires explicit completion verification evidence.
- Concurrent updates are guarded by optimistic locking (`expected_version` / ORM `version` check returning HTTP `409 Conflict` on stale writes).

---

## 7. Security Review Plan

- Pluggable `AuthAdapter` supporting signed HMAC Bearer tokens (`Authorization: Bearer ...`) and structured development/test principal headers ONLY when `AUTH_DEV_HEADER_ENABLED=true` (disabled in `production` mode).
- Proposed RBAC matrix across `CUSTOMER`, `TAILOR`, `ADMIN`, `OWNER`, and `SYSTEM` (for trusted service-to-service Module 01 order submission), documented as proposed until Module 01/08 auth is finalized.
- Strict ownership checks: `CUSTOMER` can only read/confirm/cancel-pre-production their own `customer_ref` orders; `GET /api/v1/tracking/{order_reference}` requires either an authenticated owning customer/staff principal OR a cryptographic `tracking_token` issued at order creation (order ID alone is **never** sufficient).
- Customer responses strip `INTERNAL` notes, staff assignments, raw private measurement values, and other customers' metadata.
- Rate-limiting middleware on public/tracking and mutation endpoints (configurable via env).

---

## 8. Development Roadmap (Phases 02–15)

1. **Phase 02:** Project structure, dependencies, SQLAlchemy 2.0 models, Alembic migration setup.
2. **Phase 03:** Order creation, validation, idempotency, submission endpoints.
3. **Phase 04:** Centralized lifecycle engine, RBAC permissions, hold/resume, rework, cancellation, optimistic locking.
4. **Phase 05:** Immutable versioned confirmation snapshot system & Module 02/03/04/05/06 adapters.
5. **Phase 06:** Tailoring workflow task service & quality check / rework / completion evidence rules.
6. **Phase 07:** Configurable capacity settings, workload summaries, non-binding capacity warnings & conflict indicators.
7. **Phase 08:** Customer order tracking & sanitized timeline API.
8. **Phase 09:** Admin search/filtering, internal notes, audit history, completion operations.
9. **Phase 10:** Notification event outbox + mock notification provider.
10. **Phase 11–12:** Security review & comprehensive automated Pytest suite covering categories A–K.
11. **Phase 13–15:** Complete documentation suite (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `ORDER_SCHEMA.md`, `ORDER_LIFECYCLE.md`, `STATUS_TRANSITIONS.md`, `API_DOCUMENTATION.md`, `INTEGRATION.md`, `SECURITY.md`, `TESTING.md`), Git commit/push verification, PR preparation, and Final Status Report.

---

## 9. Risks & Unresolved Project-Owner Decisions

1. **Upstream/Downstream Contracts Not Yet Merged to `main`:** Modules 01–06 and 08 have no finalized contracts on `main`. Mitigated via strict adapter interfaces and documented `PROPOSED` schemas.
2. **Proposed Lifecycle States & Role Matrix:** The 16 lifecycle statuses and 4 roles (`CUSTOMER`, `TAILOR`, `ADMIN`, `OWNER`) are implemented as configurable, centralized definitions documented as pending formal project-owner sign-off.
3. **Customer-Supplied vs Catalogue Fabric:** Real business context states customers in Dhundhwana currently supply their own fabric, while Module 02 builds a fabric catalogue. Module 07 supports **both** `CUSTOMER_SUPPLIED` (with customer fabric description/reference) and `BUSINESS_INVENTORY` (`FAB-NNN` / `FVAR-NNN` verified via Module 02 adapter).
4. **No Delivery Date Promises:** Per strict business rules, Module 07 never computes or promises automatic delivery dates from machine counts or reference daily output (`~2 shirt-and-pant sets/day`); it surfaces transparent workload counts and configurable capacity warnings for human review.
