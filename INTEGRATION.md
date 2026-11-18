# Cross-Module Integration Guide — Module 07 (`INTEGRATION.md`)

This document records **verified vs unverified** integration contracts across the eight modules of **CUSTOM SHIRT STUDIO** as inspected in the `dhundhwana-arch` GitHub organization on 2026-11-18.

---

## 1. Contract Verification Matrix

| Module | GitHub Repository | `main` Branch State | Unmerged Branch State | Contract Status in Module 07 |
|---|---|---|---|---|
| **01** | `dhundhwana-arch/custom-shirt-studio` | `LICENSE`, `README.md` only | None | **PROPOSED INBOUND CONTRACT** (`POST /api/v1/orders`, `GET /api/v1/tracking/{order_reference}`) |
| **02** | `dhundhwana-arch/fabric-catalog-system` | `LICENSE`, `README.md` only | `arena/9fb44bec-fabric-catalog-system` | **DRAFT INSPECTED & ALIGNED** (`FAB-NNN`, `FVAR-NNN`, `GET /api/v1/fabrics/by-code/{id}` + `CUSTOMER_SUPPLIED` mode) |
| **03** | `dhundhwana-arch/-3-2D-CLOTHING-DESIGNER` | `LICENSE`, `README.md` only | `arena/bbe947ab-3-2d-clothing-designer` | **DRAFT INSPECTED & ALIGNED** (`DSG-...`, `schema_version: "1.0.0"`, `components` dictionary) |
| **04** | `dhundhwana-arch/-4-CLOTHING-PREVIEW` | `LICENSE`, `README.md` only | None | **UNVERIFIED / REPLACEABLE ADAPTER** (`PreviewReferenceAdapter`) |
| **05** | `dhundhwana-arch/clothing-price-engine` | `LICENSE`, `README.md` only | None | **UNVERIFIED / REPLACEABLE ADAPTER** (`PricingAdapter` — Module 07 never computes prices) |
| **06** | `dhundhwana-arch/-6-MEASUREMENT-GUIDE` | `LICENSE`, `README.md` only | None | **UNVERIFIED / REPLACEABLE ADAPTER** (`MeasurementAdapter`) |
| **08** | `dhundhwana-arch/-8-DASHBOARD-` | `LICENSE`, `README.md` only | None | **READY OUTBOUND ADMIN REST CONTRACT** (`/api/v1/admin/*`, `/api/v1/capacity/*`, `/api/v1/workflow/*`) |

---

## 2. Upstream Adapter Contracts (`app/adapters/contracts.py`)

### 2.1 Module 05 — Clothing Price Engine (`PricingAdapter`)
- **Ownership:** Module 05 calculates official prices; Module 07 **never** calculates garment prices.
- **Consumed Fields (`QuotationRecord`):**
  - `quotation_id: str` (e.g., `QUO-001`)
  - `quoted_amount: Decimal` (`Numeric(12, 2)`)
  - `currency: str` (`INR`)
  - `price_breakdown: dict[str, Any]`
  - `quotation_status: str` (`VALID` / `APPROVED` / `EXPIRED` / `REVOKED`)
  - `pricing_config_version: str`
  - `quotation_timestamp: datetime`
  - `valid_until: datetime | None`
- **Required Information Needed from Module 05 Team:**
  1. Final HTTP GET endpoint path (e.g., `GET /api/v1/quotations/{quotation_id}`).
  2. Service-to-service authentication header format.
  3. Enumeration of official `quotation_status` values.

### 2.2 Module 06 — Measurement Guide (`MeasurementAdapter`)
- **Ownership:** Module 06 validates customer measurements; Module 07 consumes verified profile versions and locks a copy inside `OrderSnapshot` on confirmation.
- **Consumed Fields (`MeasurementRecord`):**
  - `measurement_id: str` (`MEA-001`)
  - `customer_ref: str` (`CUS-001` — verified against `order.customer_ref`)
  - `profile_version: int`
  - `validation_status: str` (must be `VALIDATED` before order confirmation)
  - `approval_status: str` (`APPROVED` / `VERIFIED`)
  - `measurements: dict[str, Any]`
  - `recorded_at: datetime`
- **Required Information Needed from Module 06 Team:**
  1. Final HTTP GET endpoint for immutable measurement version lookup.
  2. Service-to-service access token scope for retrieving measurement values for confirmed orders.

### 2.3 Module 02 — Fabric Catalog System (`FabricCatalogAdapter`)
- **Aligned with Draft Branch `arena/9fb44bec-fabric-catalog-system`:**
  - Supports both `FabricSource.CUSTOMER_SUPPLIED` (matching Dhundhwana's current operational model where customers bring their own cloth) and `FabricSource.BUSINESS_INVENTORY` (`FAB-NNN` + `FVAR-NNN` via `GET /api/v1/fabrics/by-code/{fabric_id}`).
  - Rejects `OUT_OF_STOCK` or inactive catalogue fabrics.
  - Note: Inventory reservation (`PUT /api/v1/inventory/{variant_pk}`) is deferred until Module 02 merges its order-service Bearer token contract onto `main`.

### 2.4 Module 03 & Module 04 — Design & 3D Preview (`DesignConfigAdapter`, `PreviewReferenceAdapter`)
- **Aligned with Module 03 Draft Branch `arena/bbe947ab-3-2d-clothing-designer`:**
  - Preserves `design_id` (`DSG-...`), `schema_version` (`1.0.0`), `garment_type`, and `components` (`collar`, `sleeves`, `cuffs`, `pockets`, `buttons`, `thread`, `fit`, `color_hex`) without assuming every optional component key is present on non-shirt garments.
  - Preserves optional `preview_3d_ref` (`PRV-...`) from Module 04 when supplied.

---

## 3. Downstream Contract for Module 08 (`small-business-admin-dashboard`)

Module 08 should integrate against these implemented endpoints:
- **Order Listing & Search:** `GET /api/v1/admin/orders?status=...&search=...&is_urgent=...&page=1&page_size=20`
- **Full Order Aggregate View:** `GET /api/v1/admin/orders/{order_id}`
- **Authorized Status Transitions:** `POST /api/v1/orders/{order_id}/transitions` (always pass `expected_version` from the loaded order to prevent concurrent overwrite!)
- **Internal & Customer-Visible Notes:** `POST /api/v1/orders/{order_id}/notes`
- **Workshop Task Management:** `GET /api/v1/orders/{order_id}/workflow`, `POST /api/v1/workflow/tasks`, `PATCH /api/v1/workflow/tasks/{task_id}`
- **Handover & Closure:** `POST /api/v1/orders/{order_id}/deliver`, `POST /api/v1/orders/{order_id}/complete`
- **Capacity & Workload Warnings:** `GET /api/v1/capacity`, `GET /api/v1/capacity/workload`, `PATCH /api/v1/capacity/settings`
- **Audit & Notification Logs:** `GET /api/v1/admin/audit`, `GET /api/v1/admin/notifications`
