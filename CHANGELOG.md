# Changelog

All notable changes to **Module 07 — Tailoring Order Manager** (`dhundhwana-arch/-7-TAILORING-ORDER-MANAGER`) are documented in this file.

## [0.1.1] — 2026-11-18

### Fixed
- **Idempotency-Key Payload Verification (`app/services/order_service.py`):** Added deterministic, secret-free SHA-256 request payload fingerprinting (`orders.idempotency_fingerprint`) across all semantically relevant creation fields. Reusing an `Idempotency-Key` with any modified field now returns `409 IDEMPOTENCY_KEY_REUSED` across both pre-checks and concurrent `IntegrityError` recovery while keeping `idempotency_fingerprint` unexposed in API responses and preserving backward compatibility for pre-migration rows.

### Added
- **Alembic Migration (`0002_idempotency_fingerprint`):** Backward-compatible batch schema migration adding `orders.idempotency_fingerprint`.
- **Idempotency Regression Suite (`tests/test_idempotency_regression.py`):** 7 new automated regression tests (total suite now **41 passed, 0 failed**).
- **GitHub Actions CI (`.github/workflows/ci.yml`):** Automated Python 3.11 CI running bytecode checks, SQLite & PostgreSQL 16 Alembic upgrade/downgrade roundtrips, and the full Pytest coverage suite.

## [0.1.0] — 2026-11-18

### Added
- **Phase 01 Audit (`AUDIT_REPORT.md`):** Verified repository state, Git history, permissions, and sibling repositories across `dhundhwana-arch`.
- **Relational Data Model & Alembic Migration (`0001_initial`):** Created `orders`, `order_items`, `order_snapshots`, `order_events`, `workflow_tasks`, `order_notes`, `capacity_settings`, and `notification_events` tables with foreign keys (`ON DELETE RESTRICT`), check constraints, indexes, optimistic locking (`Order.version`), and ORM immutability guards on snapshots and audit events.
- **Order Creation & Submission (`OrderService`):** Implemented request validation, reference verification, customer-supplied vs Module 02 catalogue fabric handling, duplicate `submission_reference` protection, and `Idempotency-Key` support.
- **Centralized Lifecycle Engine (`LifecycleEngine`):** Implemented 16 proposed lifecycle statuses, role-based transition permissions, `ON_HOLD` / resume tracking, quality check failure rework loops, pre/post-confirmation cancellation controls, single-step administrative corrections, and strict verified completion requirements.
- **Immutable Snapshot System (`SnapshotService`):** Implemented versioned confirmation snapshots preserving Module 05 quotations, Module 06 validated measurement profiles, Module 03 designs, and Module 02 / customer-supplied fabrics.
- **Cross-Module Adapters (`app/adapters/`):** Added typed replaceable `Protocol` contracts, synthetic mock fixture adapters, Module 02 draft HTTP adapter, and explicit fail-safe HTTP stubs for unverified upstream modules.
- **Tailoring Workflow (`WorkflowService`):** Added order readiness review, material preparation readiness checks, cutting, stitching, configurable finishing checklists (`buttons`, `cuffs`, `thread_checks`, `ironing`), quality inspection recording, delivery recording, and order completion.
- **Workload & Capacity Awareness (`CapacityService`):** Added configurable workshop equipment availability, live stage workload summaries, capacity warnings, and resource contention indicators while enforcing `NO_AUTOMATIC_DELIVERY_PROMISE`.
- **Privacy-Safe Customer Tracking (`TrackingService`):** Added authenticated and `tracking_token`-verified order tracking with chronological timelines and strict stripping of internal notes and private measurements.
- **Admin & Module 08 Integration Endpoints (`/api/v1/admin`):** Added paginated order search/filtering, full order detail inspection, cross-order audit log retrieval, and notification outbox inspection.
- **Security & Testing:** Added HMAC-SHA256 Bearer auth adapter, production secret validation, sliding-window rate limiting, and 34 automated Pytest integration/concurrency/security tests (91% code coverage).
