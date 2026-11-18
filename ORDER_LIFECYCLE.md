# Order Lifecycle Architecture — Module 07 (`ORDER_LIFECYCLE.md`)

> **Governance Notice:** The 16 lifecycle statuses below are **proposed and implemented** in `app/core/enums.py` and `app/services/lifecycle_engine.py` based on the Custom Shirt Studio master specification. They remain centrally configurable pending final project-owner sign-off across Module 01 and Module 08.

---

## 1. End-to-End Tailoring Flow

```text
  DRAFT
    │ (submit)
    ▼
  SUBMITTED
    │ (tailor/admin starts review)
    ▼
  UNDER_REVIEW ──────► QUOTE_PENDING
    │                        │
    ▼                        ▼
  AWAITING_CUSTOMER_CONFIRMATION  ◄─── (re-quotation / price change loop)
    │ (customer confirms valid Module 05 quote -> creates immutable Snapshot vN)
    ▼
  CONFIRMED
    │
    ▼
  MATERIAL_PREPARATION  (blocks CUTTING if cloth/material is missing)
    │
    ▼
  CUTTING ◄──────────────────────────┐
    │                                │
    ▼                                │ (FAILED_REWORK_REQUIRED)
  STITCHING ◄────────────────────────┤
    │                                │
    ▼                                │
  FINISHING ◄────────────────────────┘
    │ (buttons, cuffs, thread_checks, ironing verified)
    ▼
  QUALITY_CHECK  (requires PASSED or PASSED_WITH_APPROVED_CORRECTION)
    │
    ▼
  READY
    │ (verified collection or delivery recorded)
    ▼
  DELIVERED
    │ (admin verifies completion evidence & zero open tasks)
    ▼
  COMPLETED

  Cross-cutting states:
  • ON_HOLD   (temporary pause from any active operational stage; resumes to exact prior stage)
  • CANCELLED (terminal cancellation subject to pre/post-confirmation authorization rules)
```

---

## 2. Stage Definitions

| Status | Category | Definition |
|---|---|---|
| `DRAFT` | Pre-Submission | Saved order draft not yet submitted for workshop review. |
| `SUBMITTED` | Intake | Order submitted by customer/platform; awaiting workshop review. **Never treated as confirmed production.** |
| `UNDER_REVIEW` | Intake | Workshop inspects garment specs, Module 03 design, Module 06 measurement status, and fabric details. |
| `QUOTE_PENDING` | Pricing | Workshop has requested an official quotation or revision from Module 05. |
| `AWAITING_CUSTOMER_CONFIRMATION` | Pricing | Valid Module 05 quotation attached and presented to the customer for explicit confirmation. |
| `CONFIRMED` | Production Queue | Customer accepted quotation; validated measurement, design, fabric, and quotation locked in an immutable `OrderSnapshot`. |
| `MATERIAL_PREPARATION` | Workshop | Checking customer-supplied cloth or Module 02 inventory fabric readiness before cutting. |
| `CUTTING` | Workshop | Pattern layout and fabric cutting on cutting table. |
| `STITCHING` | Workshop | Main sewing and overlock assembly. |
| `FINISHING` | Workshop | Button attachment, cuff finishing, loose-thread inspection, and ironing/pressing. |
| `QUALITY_CHECK` | Verification | Final garment inspection against the confirmed `OrderSnapshot`. |
| `READY` | Handover | Garment passed quality inspection and is ready for workshop collection or dispatch. |
| `DELIVERED` | Handover | Garment collected by or delivered to customer with recorded handover reference and timestamp. |
| `COMPLETED` | Terminal | Order formally closed by `ADMIN`/`OWNER` after verifying delivery, snapshot integrity, zero open tasks, and completion evidence. |
| `ON_HOLD` | Exception | Order temporarily paused with mandatory reason and saved `previous_hold_status`. |
| `CANCELLED` | Terminal | Order cancelled with recorded actor, timestamp, and mandatory reason. |

---

## 3. Enforced Operational Safeguards

1. **Submission ≠ Confirmation:** `POST /api/v1/orders` creates orders in `DRAFT` or `SUBMITTED` only — never `CONFIRMED`.
2. **Confirmation Gate:** Entering `CONFIRMED` atomically verifies:
   - Non-expired valid Module 05 quotation matching order currency.
   - Customer's own `VALIDATED` & `APPROVED` Module 06 measurement profile.
   - Valid Module 03 design and usable Module 02 / customer-supplied fabric for every item.
   - Explicit customer price confirmation (`accepted_quotation_ref`).
   - Creation of immutable `OrderSnapshot` (`v1`, or `v2+` on reconfirmation).
3. **Material Readiness Gate:** Advancing `MATERIAL_PREPARATION -> CUTTING` is blocked (`422 MATERIAL_NOT_READY`) if any material preparation task has `material_ready=False` or `task_status=BLOCKED`.
4. **Quality Check Gate:** Advancing `QUALITY_CHECK -> READY` is blocked (`422 QUALITY_CHECK_NOT_PASSED`) unless `latest_inspection_result` is `PASSED` or `PASSED_WITH_APPROVED_CORRECTION`. Failed inspections trigger controlled rework back to `CUTTING`, `STITCHING`, or `FINISHING`.
5. **Completion Gate:** An order cannot be marked `COMPLETED` merely because stitching/finishing or `QUALITY_CHECK` finished. It must first reach `DELIVERED` with `delivery_method` + `delivery_reference` + `delivered_at`, have zero unfinished workflow tasks, possess an immutable `OrderSnapshot`, and include explicit `completion_evidence` submitted by `ADMIN` or `OWNER`.
