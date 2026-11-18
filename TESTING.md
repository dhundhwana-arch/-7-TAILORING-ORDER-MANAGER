# Automated Testing Guide & Verified Results — Module 07 (`TESTING.md`)

## 1. Reproducible Execution Instructions

```bash
# 1. Create and activate virtual environment (if not already created)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Run the full automated test suite with coverage report
.venv/bin/pytest -v --cov=app --cov-report=term-missing
```

All tests run hermetically against temporary per-test SQLite databases (`tmp_path`) with `PRAGMA foreign_keys=ON` and synthetic mock fixtures (`CUS-001`, `DSG-001`, `FAB-001`, `MEA-001`, `QUO-001` — zero real customer PII and zero external network calls).

---

## 2. Verified Test Execution Summary

**Command Executed:**
```bash
.venv/bin/pytest -v --cov=app --cov-report=term-missing
```

| Metric | Verified Result |
|---|---|
| **Total Tests** | **34** |
| **Passed** | **34** |
| **Failed** | **0** |
| **Skipped** | **0** |
| **Not Executed / Blocked** | **0** |
| **Measured Line Coverage (`app/`)** | **91%** (`2,334` statements, `213` missed — primarily live `httpx` network branches in `http_adapters.py` awaiting deployed sibling services) |

---

## 3. Test Coverage Matrix by Requirement Category (Section 24)

| Category | Test Module | Verified Scenarios |
|---|---|---|
| **A. Order Creation** | `tests/test_order_creation.py` (10 tests) | Draft & immediate submission (`SUBMITTED`, never `CONFIRMED`), multi-item & catalogue fabric (`FAB-001`), missing `customer_ref` / `design_ref` / `measurement_ref`, missing `quotation_ref` gate, invalid quantities (`0`, `-3`, `101`), invalid/malicious identifiers, duplicate `submission_reference` (`409`), `Idempotency-Key` replay (`200`). |
| **B. Lifecycle** | `tests/test_lifecycle.py` (5 tests) + `tests/test_admin_and_endpoints.py` | Full 13-step progression `DRAFT -> ... -> COMPLETED`, invalid transitions (`422`), unauthorized transitions (`403`), pre/post-confirmation cancellation permissions, `ON_HOLD` + mandatory reason + deterministic resume, premature completion blocks, `QUALITY_CHECK` failure (`FAILED_REWORK_REQUIRED`) + rework task loop, controlled single-step `is_admin_correction`. |
| **C. Price Snapshots** | `tests/test_snapshots_and_integrations.py` | Valid quotation acceptance, missing/nonexistent/expired/revoked quotation rejection, customer confirmation, confirmed snapshot immutability when Module 05 updates `QUO-001` price/version later, explicit re-quotation + customer reconfirmation creating Snapshot `v2` while preserving `v1`. |
| **D. Measurement Snapshots** | `tests/test_snapshots_and_integrations.py` | Validated measurement acceptance, unvalidated measurement flagged in Order Review and blocked at confirmation (`422`), customer mismatch protection, confirmed measurement `profile_version=1` preserved when Module 06 advances to `profile_version=2`, ORM `ImmutableRecordError` on `UPDATE`/`DELETE`. |
| **E. Design & Fabric** | `tests/test_snapshots_and_integrations.py` | Valid `DSG-001` & `FAB-001` (`BUSINESS_INVENTORY` + `CUSTOMER_SUPPLIED`) & `PRV-001`, invalid design (`DSG-INVALID`), out-of-stock fabric (`FAB-OUT`), missing 3D preview (`PRV-MISSING`), simulated adapter outage (`502`), unverified live HTTP adapter fail-safe checks. |
| **F. Audit History** | `tests/test_audit_and_concurrency.py` | Event creation on transitions, actor ID & role recording, UTC timestamps, rollback consistency (failed transition writes zero events), ORM `ImmutableRecordError` blocking `OrderEvent` update/delete. |
| **G. Concurrency** | `tests/test_audit_and_concurrency.py` | Stale `expected_version` (`409`), simultaneous two-session ORM optimistic lock conflict (`StaleDataError` -> `ConcurrencyConflictError`), 4-thread concurrent duplicate `submission_reference` (`1 x 201`, `3 x 409`), 4-thread concurrent `Idempotency-Key` replay resolving to 1 order. |
| **H. Privacy & Security** | `tests/test_security_and_privacy.py` + `tests/test_admin_and_endpoints.py` | Customer views own order, `403` on other customer's order, `INTERNAL` notes stripped from customer order/history/tracking, bare `order_reference` rejected (`401`) on `/tracking`, forged `tracking_token` rejected (`403`), valid `tracking_token` accepted with zero measurement leakage, expired/tampered Bearer token rejected (`401`), `production` weak-secret startup block, sliding-window rate limit (`429`). |
| **I. Capacity & Workflow** | `tests/test_workflow_and_capacity.py` | Missing capacity config warning, `PATCH /api/v1/capacity/settings` validation, workload stage counts, `ACTIVE_PRODUCTION_THRESHOLD_EXCEEDED`, `URGENT_WORKLOAD_HIGH`, `IRON_UNAVAILABLE` conflict, `NO_AUTOMATIC_DELIVERY_PROMISE`, material missing block preventing `CUTTING`, finishing checklist (`buttons`, `cuffs`, `thread_checks`, `ironing`) enforcement. |
| **J. Notifications** | `tests/test_notifications_and_api.py` | Event generation, `MockNotificationProvider` (`SENT_MOCK`), simulated provider failure recorded as `FAILED` without rolling back order transition, zero real external deliveries. |
| **K. API & Migrations** | `tests/test_notifications_and_api.py` | Health endpoint, `extra="forbid"` validation, `404` handling, pagination math, masked `500 DATABASE_ERROR` on `SQLAlchemyError`, full Alembic `upgrade head` -> `downgrade base` -> `upgrade head` verification. |
