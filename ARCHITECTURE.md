# Architecture — Module 07: Tailoring Order Manager

## 1. System Position in the 8-Module Ecosystem

```text
  [01: custom-shirt-studio]  ---- Order Submission & Tracking ---->  +-----------------------------------+
  [02: fabric-catalog-system] <-- Fabric Ref Verification ---------  |                                   |
  [03: 2d-clothing-designer]  <-- Design Config Verification ------  |   MODULE 07:                      |
  [04: 3d-clothing-preview]   <-- Optional 3D Preview Ref ---------  |   TAILORING ORDER MANAGER         |
  [05: clothing-price-engine] <-- Official Quotation Verification -- |   (Order Lifecycle & Workflow)    |
  [06: measurement-guide]     <-- Validated Measurement Profile ---  |                                   |
  [08: admin-dashboard]      ---- Admin / Audit / Capacity APIs ---> +-----------------------------------+
```

Module 07 is strictly an **API-first backend service** owning the operational lifecycle of tailoring orders. It neither duplicates customer UI (Module 01) nor builds a duplicate central admin frontend (Module 08), and it never calculates official garment prices (Module 05).

---

## 2. Internal Layered Architecture

Module 07 follows strict unidirectional dependency flow:

`API Routers (app/api/v1)` → `Domain Services (app/services)` → `Models & Adapters (app/models, app/adapters)` → `Database / Upstream Protocols`

### Layer Breakdown

1. **Presentation & Transport Layer (`app/main.py`, `app/api/`, `app/schemas/`)**
   - FastAPI routers grouped by bounded concern (`orders`, `lifecycle`, `workflow`, `tracking`, `capacity`, `admin`).
   - Strict Pydantic v2 input schemas (`extra="forbid"`) rejecting unexpected or malformed fields before reaching business logic.
   - Privacy-aware response serializers (`app/api/serializers.py`) that strip `INTERNAL` notes, staff IDs, and raw customer body measurements for non-staff callers.
   - Sliding-window rate-limiting middleware and structured JSON exception handlers (`DomainError`, `RequestValidationError`, `SQLAlchemyError`).

2. **Security & Principal Layer (`app/core/security.py`, `app/core/config.py`)**
   - `AuthAdapter` protocol with `HmacBearerAuthAdapter` verifying signed `v1.<payload>.<sig>` Bearer tokens.
   - Development header fallback (`X-Actor-Id`, `X-Actor-Role`) strictly disabled whenever `APP_ENV=production`.
   - Keyed HMAC-SHA256 customer tracking tokens (`trk_...`) verified via `hmac.compare_digest`.

3. **Domain Service Layer (`app/services/`)**
   - `OrderService`: Atomic order creation, reference validation, `Idempotency-Key` replay, duplicate `submission_reference` protection, pre-confirmation updates, submission, customer confirmation, cancellation, and notes.
   - `LifecycleEngine`: **Single source of truth** for all status transitions, RBAC authorization per transition, hold/resume (`previous_hold_status`), quality inspection rework loops, single-step administrative corrections, and verified completion enforcement.
   - `SnapshotService`: Verifies Module 02, 03, 04, 05, and 06 records at confirmation time and writes versioned immutable `OrderSnapshot` records.
   - `WorkflowService`: Manages operational workshop tasks (`ORDER_REVIEW`, `MATERIAL_PREPARATION`, `CUTTING`, `STITCHING`, `FINISHING` checklists, `QUALITY_CHECK` pass/fail, delivery, completion).
   - `CapacityService`: Manages configurable workshop resource counts and non-binding workload warnings (`delivery_date_policy = "NO_AUTOMATIC_DELIVERY_PROMISE"`).
   - `TrackingService`: Enforces ownership or `tracking_token` verification and constructs sanitized chronological customer timelines.
   - `NotificationService`: Writes `NotificationEvent` records transactionally and dispatches via `NotificationProvider` (`MockNotificationProvider` in dev/test) without coupling external provider failures to core database transactions.

4. **Cross-Module Integration Adapter Layer (`app/adapters/`)**
   - Defines Python `Protocol` interfaces (`PricingAdapter`, `MeasurementAdapter`, `FabricCatalogAdapter`, `DesignConfigAdapter`, `PreviewReferenceAdapter`, `NotificationProvider`) and immutable dataclasses.
   - `AdapterRegistry` switches cleanly via `INTEGRATION_MODE=mock|http`.

5. **Persistence Layer (`app/db/`, `app/models/`, `migrations/`)**
   - SQLAlchemy 2.0 declarative models compatible with both **PostgreSQL** and **SQLite** (`PRAGMA foreign_keys=ON`, `busy_timeout=5000`).
   - Optimistic locking via `Order.version` (`__mapper_args__ = {"version_id_col": version}`).
   - ORM `before_update` and `before_delete` event hooks blocking any mutation or deletion of `OrderSnapshot` and `OrderEvent`.
   - Versioned schema management via Alembic (`migrations/versions/0001_initial_order_manager_schema.py`).
