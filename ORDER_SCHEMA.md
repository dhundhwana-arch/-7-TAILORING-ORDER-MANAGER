# Order Database Schema — Module 07 (`ORDER_SCHEMA.md`)

Module 07 uses an extensible relational schema managed by SQLAlchemy 2.0 (`app/models/entities.py`) and Alembic (`migrations/versions/0001_initial_order_manager_schema.py`).

All timestamps are timezone-aware UTC (`DateTime(timezone=True)`), and all monetary quantities use exact fixed-point `Numeric(12, 2)` (never binary floating-point). All child foreign keys enforce `ON DELETE RESTRICT` so historical order records cannot be accidentally cascaded away.

---

## 1. Entity-Relationship Overview

```text
orders (1) ──────< (N) order_items
  │
  ├──────────────< (N) order_snapshots      [APPEND-ONLY / IMMUTABLE]
  ├──────────────< (N) order_events         [APPEND-ONLY / IMMUTABLE]
  ├──────────────< (N) workflow_tasks
  ├──────────────< (N) order_notes          [INTERNAL vs CUSTOMER_VISIBLE]
  └──────────────< (N) notification_events

capacity_settings                           [Configurable operational settings]
```

---

## 2. Table Definitions

### 2.1 `orders`
Aggregate root representing a tailoring order.

| Column | Type | Nullable | Notes / Constraints |
|---|---|---|---|
| `id` | `Integer` | No | Primary Key (autoincrement) |
| `public_order_ref` | `String(64)` | No | `UNIQUE`, Indexed (`ORD-...`) |
| `customer_ref` | `String(64)` | No | Indexed (`CUS-...`) |
| `current_status` | `String(40)` | No | Indexed; defaults to `DRAFT` |
| `previous_hold_status` | `String(40)` | Yes | Preserves prior active stage while `ON_HOLD` |
| `hold_reason` | `Text` | Yes | Reason recorded when placed `ON_HOLD` |
| `order_source` | `String(64)` | No | Defaults to `MODULE_01_PLATFORM` |
| `submission_reference` | `String(128)` | Yes | Indexed; `UNIQUE(order_source, submission_reference)` |
| `idempotency_key` | `String(128)` | Yes | `UNIQUE(customer_ref, idempotency_key)` |
| `idempotency_fingerprint` | `String(64)` | Yes | Canonical secret-free SHA-256 request payload digest (never exposed via API) |
| `currency` | `String(8)` | No | Defaults to `INR` |
| `measurement_ref` | `String(64)` | No | Module 06 measurement profile reference |
| `quotation_ref` | `String(64)` | Yes | Module 05 official quotation reference |
| `quoted_amount` | `Numeric(12,2)` | Yes | Verified amount from Module 05 |
| `customer_price_confirmed` | `Boolean` | No | `True` only after customer confirmation |
| `customer_confirmed_at` | `DateTime(tz)` | Yes | Confirmation timestamp |
| `customer_confirmed_by` | `String(64)` | Yes | Actor who confirmed |
| `is_urgent` | `Boolean` | No | Indexed; requires `ADMIN`/`OWNER` authorization |
| `urgent_authorized_by` | `String(64)` | Yes | Authorizing admin actor |
| `customer_instructions` | `Text` | Yes | Customer tailoring instructions |
| `tracking_token_hash` | `String(128)` | No | Keyed HMAC-SHA256 digest (plaintext token never stored) |
| `latest_inspection_result` | `String(48)` | Yes | Latest `QUALITY_CHECK` outcome |
| `rework_count` | `Integer` | No | `CHECK (rework_count >= 0)` |
| `delivery_method` | `String(32)` | Yes | `COLLECTION` or `DELIVERY` |
| `delivery_reference` | `String(128)` | Yes | Verified receipt/handover reference |
| `delivery_recipient_ack` | `Text` | Yes | Optional recipient acknowledgment note |
| `delivered_at` | `DateTime(tz)` | Yes | Handover timestamp |
| `completion_evidence` | `Text` | Yes | Mandatory verified closure evidence |
| `completed_by` | `String(64)` | Yes | Admin actor closing order |
| `completed_at` | `DateTime(tz)` | Yes | Completion timestamp |
| `cancellation_reason` | `Text` | Yes | Reason for cancellation |
| `cancelled_by` | `String(64)` | Yes | Cancelling actor |
| `cancelled_at` | `DateTime(tz)` | Yes | Cancellation timestamp |
| `version` | `Integer` | No | Optimistic lock counter (`CHECK version >= 1`, `version_id_col`) |
| `created_at` | `DateTime(tz)` | No | Indexed; composite index `(current_status, created_at)` |
| `updated_at` | `DateTime(tz)` | No | Last modification UTC timestamp |

### 2.2 `order_items`
Supports one or multiple garments per order (`shirt`, `pant`, `shirt_and_pant_set`, etc.).

| Column | Type | Nullable | Notes / Constraints |
|---|---|---|---|
| `id` | `Integer` | No | Primary Key |
| `order_id` | `Integer` | No | FK → `orders.id` (`ON DELETE RESTRICT`), Indexed |
| `line_number` | `Integer` | No | `UNIQUE(order_id, line_number)`, `CHECK >= 1` |
| `garment_type` | `String(48)` | No | e.g., `shirt`, `shirt_and_pant_set` |
| `quantity` | `Integer` | No | `CHECK (quantity >= 1)` |
| `design_ref` | `String(64)` | No | Module 03 design ID (`DSG-...`) |
| `design_version` | `String(32)` | Yes | Module 03 schema version (`1.0.0`) |
| `fabric_source` | `String(32)` | No | `CUSTOMER_SUPPLIED` or `BUSINESS_INVENTORY` |
| `fabric_ref` | `String(64)` | No | Customer cloth ref or Module 02 `FAB-NNN` |
| `fabric_variant_ref` | `String(64)` | Yes | Module 02 `FVAR-NNN` where applicable |
| `preview_3d_ref` | `String(64)` | Yes | Optional Module 04 preview ID |
| `customization_data` | `JSON` | No | Additional item-level customization options |
| `item_notes` | `Text` | Yes | Garment-specific tailoring notes |

### 2.3 `order_snapshots` (Immutable)
Preserves confirmed quotation, measurement version, design configuration, and fabric data at confirmation time. Protected by ORM `before_update` and `before_delete` listeners raising `ImmutableRecordError`.

- Unique constraint: `(order_id, snapshot_version)` (`snapshot_version = 1, 2, ...`).
- Columns: `id`, `order_id` (FK), `snapshot_version`, `snapshot_type` (`ORDER_CONFIRMATION` | `REQUOTATION_RECONFIRMATION`), `design_snapshot` (`JSON`), `fabric_snapshot` (`JSON`), `measurement_snapshot` (`JSON`), `quotation_snapshot` (`JSON`), `confirmed_amount` (`Numeric(12,2)`), `currency`, `confirmed_by`, `confirmed_role`, `created_at`.

### 2.4 `order_events` (Immutable Audit Trail)
Append-only chronological log of every lifecycle transition and operational action. Protected by ORM `before_update` and `before_delete` listeners.

- Columns: `id`, `event_ref` (`UNIQUE`), `order_id` (FK), `event_type`, `previous_status`, `new_status`, `actor_id`, `actor_role`, `reason`, `customer_visible`, `customer_message`, `metadata_json`, `created_at`.
- Indexes: `event_ref`, `order_id`, `event_type`, `created_at`, `(order_id, created_at)`.

### 2.5 `workflow_tasks`
Tracks workshop execution across `ORDER_REVIEW`, `MATERIAL_PREPARATION`, `CUTTING`, `STITCHING`, `FINISHING`, and `QUALITY_CHECK`.

- Columns: `id`, `task_ref` (`UNIQUE`), `order_id` (FK), `stage`, `task_name`, `task_status`, `assigned_staff_ref` (nullable — never auto-invented), `is_rework`, `checklist_json`, `material_ready`, `missing_material_info`, `inspection_result`, `approved_corrections`, `rework_requirements`, `notes`, `started_at`, `completed_at`, `created_by`, `created_at`, `updated_at`.

### 2.6 `order_notes`
Separates `INTERNAL` workshop memos from `CUSTOMER_VISIBLE` progress notes.
- Columns: `id`, `order_id` (FK), `visibility` (`INTERNAL` | `CUSTOMER_VISIBLE`), `author_id`, `author_role`, `content`, `created_at`.

### 2.7 `capacity_settings`
Stores configurable workshop equipment counts (`sewing_machines_count`, `available_sewing_machines`, `overlock_machines_count`, `irons_count`, `cutting_tables_count`), contextual `reference_sets_per_day`, `is_guaranteed_capacity` (`False`), and warning thresholds (`max_active_production_orders_warning`, `max_stage_orders_warning`, `max_urgent_orders_warning`). Check constraints enforce `0 <= available <= total`.

### 2.8 `notification_events`
Transactional outbox recording notification events (`notification_ref`, `order_id`, `event_type`, `channel`, `recipient_ref`, `payload_json`, `delivery_status`, `provider_name`, `error_message`, `created_at`, `processed_at`).

---

## 3. Database Migrations

Run migrations with Alembic:
```bash
# Apply latest schema
DATABASE_URL="sqlite:///./tailoring_orders.db" .venv/bin/alembic upgrade head

# Roll back schema (non-production only)
DATABASE_URL="sqlite:///./tailoring_orders.db" .venv/bin/alembic downgrade base
```
