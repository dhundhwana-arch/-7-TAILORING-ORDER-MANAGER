# REST API Documentation — Module 07 (`API_DOCUMENTATION.md`)

This document specifies **implemented APIs only** (28 endpoints across `/health` and `/api/v1/*`). Live OpenAPI 3.1 schema is served at `/openapi.json` and `/docs`.

---

## 1. Authentication & Headers

All `/api/v1/*` endpoints (except `/api/v1/tracking/{order_reference}`, which accepts either a Bearer token OR `X-Tracking-Token`) require authentication:

- **Primary Header:** `Authorization: Bearer v1.<base64url_payload>.<base64url_hmac_sig>`
- **Local/Test Development Headers (only when `AUTH_DEV_HEADER_ENABLED=true` and `APP_ENV != production`):**
  - `X-Actor-Id: <actor_id>` (e.g., `CUS-001`, `STF-TAILOR-01`, `STF-ADMIN-01`)
  - `X-Actor-Role: CUSTOMER | TAILOR | ADMIN | OWNER | SYSTEM`
- **Idempotency Header (Order Creation):** `Idempotency-Key: <unique-client-key>`
- **Tracking Token Header / Query:** `X-Tracking-Token: trk_...` or `?tracking_token=trk_...`

---

## 2. Standard Error & Pagination Envelopes

### Error Response (`400`, `401`, `403`, `404`, `409`, `422`, `429`, `500`, `502`)
```json
{
  "error_code": "CONCURRENCY_CONFLICT",
  "message": "Order version conflict: expected version 1, but current version is 2.",
  "details": {
    "expected_version": 1,
    "actual_version": 2
  }
}
```

### Paginated Response
```json
{
  "items": [],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "pages": 3
}
```

---

## 3. Endpoint Reference

### 3.1 System
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `GET` | `/health` | None | Public | Service health, version, environment, and integration mode. |

### 3.2 Orders (`/api/v1/orders`)
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `POST` | `/api/v1/orders` | Required | `CUSTOMER`, `ADMIN`, `OWNER`, `SYSTEM` | Create order (`201 Created` with one-time `tracking_token`, or `200 OK` on `Idempotency-Key` replay). Enters `DRAFT` or `SUBMITTED` — never `CONFIRMED`. |
| `GET` | `/api/v1/orders` | Required | All authenticated | Paginated list (`CUSTOMER` automatically restricted to own `customer_ref`). Query params: `status`, `customer_ref`, `search`, `is_urgent`, `page`, `page_size`. |
| `GET` | `/api/v1/orders/{order_id}` | Required | Owner `CUSTOMER` or Staff | Retrieve order by internal ID or `public_order_ref`. `INTERNAL` notes stripped for customers. |
| `PATCH` | `/api/v1/orders/{order_id}` | Required | Owner `CUSTOMER` or Staff | Pre-confirmation attribute updates (`quotation_ref` staff-only, `measurement_ref`, `customer_instructions`, `is_urgent` admin-only, `expected_version`). Protected after confirmation. |
| `POST` | `/api/v1/orders/{order_id}/submit` | Required | Owner `CUSTOMER`, `ADMIN`, `OWNER`, `SYSTEM` | Transition `DRAFT -> SUBMITTED`. |
| `POST` | `/api/v1/orders/{order_id}/confirm` | Required | Owner `CUSTOMER`, `ADMIN`, `OWNER` | Confirm accepted quotation (`accepted_quotation_ref`) from `AWAITING_CUSTOMER_CONFIRMATION -> CONFIRMED`, creating immutable `OrderSnapshot`. |
| `POST` | `/api/v1/orders/{order_id}/cancel` | Required | Owner `CUSTOMER` (pre-confirmation) or `ADMIN`/`OWNER` | Cancel order with mandatory `reason`. |
| `POST` | `/api/v1/orders/{order_id}/notes` | Required | `TAILOR`, `ADMIN`, `OWNER` | Add `INTERNAL` or `CUSTOMER_VISIBLE` note (`201 Created`). |

#### Example: `POST /api/v1/orders`
```json
{
  "customer_ref": "CUS-001",
  "measurement_ref": "MEA-001",
  "quotation_ref": "QUO-001",
  "currency": "INR",
  "order_source": "MODULE_01_PLATFORM",
  "submission_reference": "SUB-2026-0001",
  "customer_instructions": "Regular comfort fit.",
  "submit_immediately": true,
  "items": [
    {
      "garment_type": "shirt",
      "quantity": 1,
      "design_ref": "DSG-001",
      "fabric_source": "CUSTOMER_SUPPLIED",
      "fabric_ref": "CUST-CLOTH-001",
      "preview_3d_ref": "PRV-001",
      "customization_data": {}
    }
  ]
}
```

### 3.3 Lifecycle & Snapshots (`/api/v1/orders/{order_id}/...`)
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/orders/{order_id}/status` | Required | Owner `CUSTOMER` or Staff | Current status, customer label, hold state, version. |
| `GET` | `/api/v1/orders/{order_id}/history` | Required | Owner `CUSTOMER` or Staff | Chronological event list (sanitized to `customer_visible` events for `CUSTOMER`). |
| `GET` | `/api/v1/orders/{order_id}/snapshots` | Required | Owner `CUSTOMER` or Staff | Immutable confirmation snapshots (raw measurement dimensions redacted for `CUSTOMER`, full for Staff). |
| `POST` | `/api/v1/orders/{order_id}/transitions` | Required | Role-checked per transition | Execute centralized lifecycle transition (`target_status`, `reason`, `expected_version`, `is_admin_correction`, `metadata`). |

### 3.4 Tailoring Workflow (`/api/v1/workflow` & `/api/v1/orders/{order_id}/...`)
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/orders/{order_id}/workflow` | Required | `TAILOR`, `ADMIN`, `OWNER` | Full workflow summary, readiness review, rework count, and tasks for an order. |
| `POST` | `/api/v1/orders/{order_id}/review` | Required | `TAILOR`, `ADMIN`, `OWNER` | Execute readiness inspection across design, fabric, measurement, and quotation references. |
| `POST` | `/api/v1/orders/{order_id}/deliver` | Required | `TAILOR`, `ADMIN`, `OWNER` | Record collection/delivery (`delivery_method`, `delivery_reference`, `delivery_recipient_ack`) -> `DELIVERED`. |
| `POST` | `/api/v1/orders/{order_id}/complete` | Required | `ADMIN`, `OWNER` | Verify completion conditions & `completion_evidence` -> `COMPLETED`. |
| `GET` | `/api/v1/workflow/tasks` | Required | `TAILOR`, `ADMIN`, `OWNER` | Paginated workflow tasks filterable by `order_reference`, `stage`, `task_status`. |
| `POST` | `/api/v1/workflow/tasks` | Required | `TAILOR`, `ADMIN`, `OWNER` | Create workshop task (`201 Created`). `FINISHING` tasks receive default `buttons`, `cuffs`, `thread_checks`, `ironing` checklist. |
| `PATCH` | `/api/v1/workflow/tasks/{task_id}` | Required | `TAILOR`, `ADMIN`, `OWNER` | Update task status, optional staff assignment, checklist items, material readiness, or quality `inspection_result`. |

### 3.5 Customer Tracking (`/api/v1/tracking`)
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/tracking/{order_reference}` | Owning Bearer token, Staff token, **OR** `X-Tracking-Token` | Owner `CUSTOMER`, Staff, or Token Holder | Privacy-safe customer tracking view with completed/pending stages, customer updates, and timeline. Bare `order_reference` without credentials returns `401`. |

### 3.6 Capacity & Workload (`/api/v1/capacity`)
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/capacity` | Required | `TAILOR`, `ADMIN`, `OWNER` | View configured workshop equipment availability and thresholds (`is_guaranteed_capacity: false`). |
| `GET` | `/api/v1/capacity/workload` | Required | `TAILOR`, `ADMIN`, `OWNER` | Live workload counts by stage, active garment units, `capacity_warnings`, and `scheduling_conflicts` (`NO_AUTOMATIC_DELIVERY_PROMISE`). |
| `PATCH` | `/api/v1/capacity/settings` | Required | `ADMIN`, `OWNER` | Configure workshop machine counts, available counts, reference daily sets, and warning thresholds. |

### 3.7 Administration (`/api/v1/admin` — Module 08 Contract)
| Method | Path | Auth | Roles | Purpose |
|---|---|---|---|---|
| `GET` | `/api/v1/admin/orders` | Required | `ADMIN`, `OWNER` | Search and filter all orders (`status`, `customer_ref`, `search`, `is_urgent`, `page`, `page_size`). |
| `GET` | `/api/v1/admin/orders/{order_id}` | Required | `ADMIN`, `OWNER` | Complete administrative aggregate view (order, internal+public notes, full snapshots, workflow tasks, audit events, notifications). |
| `GET` | `/api/v1/admin/audit` | Required | `ADMIN`, `OWNER` | Paginated cross-order immutable audit history (`order_reference`, `event_type`, `actor_id`). |
| `GET` | `/api/v1/admin/notifications` | Required | `ADMIN`, `OWNER` | Paginated notification outbox inspection (`order_reference`, `delivery_status`). |
