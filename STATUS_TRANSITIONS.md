# Status Transition Rules & RBAC Matrix — Module 07 (`STATUS_TRANSITIONS.md`)

All status transitions in Module 07 are enforced exclusively by `LifecycleEngine.transition` (`app/services/lifecycle_engine.py`).

---

## 1. Standard Forward & Re-Quotation Transitions

| Current Status | Allowed Target Status | Authorized Roles | Required Preconditions |
|---|---|---|---|
| `DRAFT` | `SUBMITTED` | `CUSTOMER` (owner), `ADMIN`, `OWNER`, `SYSTEM` | Order belongs to customer if role is `CUSTOMER`. |
| `SUBMITTED` | `UNDER_REVIEW` | `TAILOR`, `ADMIN`, `OWNER` | None. |
| `UNDER_REVIEW` | `QUOTE_PENDING` | `TAILOR`, `ADMIN`, `OWNER` | None. |
| `UNDER_REVIEW` | `AWAITING_CUSTOMER_CONFIRMATION` | `TAILOR`, `ADMIN`, `OWNER` | Valid, non-expired Module 05 `quotation_ref` attached. |
| `QUOTE_PENDING` | `AWAITING_CUSTOMER_CONFIRMATION` | `TAILOR`, `ADMIN`, `OWNER` | Valid, non-expired Module 05 `quotation_ref` attached. |
| `AWAITING_CUSTOMER_CONFIRMATION` | `QUOTE_PENDING` | `TAILOR`, `ADMIN`, `OWNER` | Used when quotation expires or needs revision. |
| `AWAITING_CUSTOMER_CONFIRMATION` | `CONFIRMED` | `CUSTOMER` (owner), `ADMIN`*, `OWNER`* | Valid quotation + validated measurement + valid design/fabric + atomic `OrderSnapshot` creation. (*Admin requires explicit `customer_confirmation_evidence`.) |
| `CONFIRMED` | `AWAITING_CUSTOMER_CONFIRMATION` | `ADMIN`, `OWNER` | Explicit `reason` required; resets `customer_price_confirmed=False` until customer reconfirms new quotation (creates Snapshot `vN+1`). |
| `CONFIRMED` | `MATERIAL_PREPARATION` | `TAILOR`, `ADMIN`, `OWNER` | Confirmed snapshot exists. |
| `MATERIAL_PREPARATION` | `CUTTING` | `TAILOR`, `ADMIN`, `OWNER` | No `MATERIAL_PREPARATION` task is `BLOCKED` or marked `material_ready=False`. |
| `CUTTING` | `STITCHING` | `TAILOR`, `ADMIN`, `OWNER` | None. |
| `STITCHING` | `FINISHING` | `TAILOR`, `ADMIN`, `OWNER` | None. |
| `FINISHING` | `QUALITY_CHECK` | `TAILOR`, `ADMIN`, `OWNER` | None (note: finishing tasks require all checklist items true to complete). |
| `QUALITY_CHECK` | `READY` | `TAILOR`, `ADMIN`, `OWNER` | `latest_inspection_result` must be `PASSED` or `PASSED_WITH_APPROVED_CORRECTION`. |
| `READY` | `DELIVERED` | `TAILOR`, `ADMIN`, `OWNER` | `delivery_method` and `delivery_reference` required. |
| `DELIVERED` | `COMPLETED` | `ADMIN`, `OWNER` | Verified `delivered_at` + `delivery_reference`, confirmed snapshot exists, zero open workflow tasks, and non-empty `completion_evidence`. |

---

## 2. Quality Failure & Approved Rework Transitions

When `QUALITY_CHECK` identifies defects:
- **Allowed Transitions:** `QUALITY_CHECK` → `CUTTING` | `STITCHING` | `FINISHING`
- **Authorized Roles:** `TAILOR`, `ADMIN`, `OWNER`
- **Required Conditions:** Non-empty `reason` describing rework instructions.
- **Side Effects:** Sets `latest_inspection_result = FAILED_REWORK_REQUIRED`, increments `order.rework_count`, creates a `WorkflowTask` (`is_rework=True`) for the target stage, and logs `QUALITY_REWORK_TRIGGERED`.

---

## 3. Hold (`ON_HOLD`) & Resume Rules

- **Entering `ON_HOLD`:**
  - Allowed from: `SUBMITTED`, `UNDER_REVIEW`, `QUOTE_PENDING`, `AWAITING_CUSTOMER_CONFIRMATION`, `CONFIRMED`, `MATERIAL_PREPARATION`, `CUTTING`, `STITCHING`, `FINISHING`, `QUALITY_CHECK`, `READY`.
  - Forbidden from: `DRAFT`, `DELIVERED`, `COMPLETED`, `CANCELLED`, `ON_HOLD`.
  - Authorized Roles: `TAILOR`, `ADMIN`, `OWNER`.
  - Preconditions: Non-empty `reason`. Saves `previous_hold_status`.
- **Resuming from `ON_HOLD`:**
  - Authorized Roles: `TAILOR`, `ADMIN`, `OWNER`.
  - Allowed Target: Must match `order.previous_hold_status` (or `UNDER_REVIEW` when directed by `ADMIN`/`OWNER`). Arbitrary stage jumps out of `ON_HOLD` are rejected with `422 INVALID_RESUME_TARGET`.

---

## 4. Cancellation Rules (`-> CANCELLED`)

| Current State Group | Authorized Roles | Preconditions |
|---|---|---|
| Pre-Confirmation (`DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `QUOTE_PENDING`, `AWAITING_CUSTOMER_CONFIRMATION`) | `CUSTOMER` (owner), `ADMIN`, `OWNER` | Non-empty `reason`. |
| Confirmed / Active Workshop / Held (`CONFIRMED` .. `READY`, `ON_HOLD`) | `ADMIN`, `OWNER` **only** | Non-empty `reason`. (`CUSTOMER` and `TAILOR` receive `403 FORBIDDEN`.) |
| Handover / Terminal (`DELIVERED`, `COMPLETED`, `CANCELLED`) | **None (Forbidden)** | Rejected with `422 INVALID_CANCELLATION_STATE` / `TERMINAL_STATE_IMMUTABLE`. |

---

## 5. Controlled Exceptional Administrative Corrections

To allow recovery from accidental single-click operator mistakes without allowing arbitrary state mutation:
- Flag: `is_admin_correction: true` on `POST /api/v1/orders/{order_id}/transitions`
- Authorized Roles: `ADMIN`, `OWNER` only (`403` for `TAILOR`/`CUSTOMER`).
- Permitted single-step rollbacks only:
  - `MATERIAL_PREPARATION -> CONFIRMED`
  - `CUTTING -> MATERIAL_PREPARATION`
  - `STITCHING -> CUTTING`
  - `FINISHING -> STITCHING`
  - `READY -> QUALITY_CHECK`
  - `DELIVERED -> READY`
- Mandatory audit `reason` (`>= 8` characters); recorded as `event_type = "ADMIN_STAGE_CORRECTION"`.
- Cannot bypass `CONFIRMED` snapshot creation or jump forward into `COMPLETED`.

---

## 6. Invalid Transitions (Examples Explicitly Rejected)

- Any self-transition `X -> X` (`422 NO_OP_TRANSITION`)
- Any transition out of `COMPLETED` or `CANCELLED` (`422 TERMINAL_STATE_IMMUTABLE`)
- `DRAFT -> CONFIRMED`, `SUBMITTED -> CONFIRMED`, `UNDER_REVIEW -> CONFIRMED` (`422 INVALID_STATUS_TRANSITION`)
- `SUBMITTED -> CUTTING` / `STITCHING` (skipping review & confirmation)
- `QUALITY_CHECK -> COMPLETED` or `READY -> COMPLETED` (skipping delivery verification)
- Stale concurrent writes where `expected_version != order.version` (`409 CONCURRENCY_CONFLICT`)
