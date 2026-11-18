# Security & Privacy Architecture — Module 07 (`SECURITY.md`)

## 1. Authentication Architecture

Because Module 01 (Customer Accounts) and Module 08 (Admin Auth) do not yet publish a shared identity provider on `main`, Module 07 implements a replaceable `AuthAdapter` (`app/core/security.py`):

1. **Signed HMAC-SHA256 Bearer Tokens (`v1.<payload>.<signature>`):**
   - Verified using constant-time `hmac.compare_digest`.
   - Enforces `exp` expiration timestamps, non-empty `sub` (`actor_id`), and valid `ActorRole`.
2. **Strictly Gated Local/Test Headers:**
   - `X-Actor-Id` and `X-Actor-Role` are accepted **only** when `AUTH_DEV_HEADER_ENABLED=true` AND `APP_ENV != "production"`.
   - `Settings.validate_production_security` refuses application startup if `APP_ENV=production` has `AUTH_DEV_HEADER_ENABLED=true` or weak/default secrets (`< 32` characters).

---

## 2. Proposed Role-Based Access Control (RBAC) Matrix

> **Note:** Roles `CUSTOMER`, `TAILOR`, `ADMIN`, `OWNER` (plus internal `SYSTEM`) are proposed and centrally enforced pending ecosystem-wide identity approval.

| Capability | `CUSTOMER` | `TAILOR` | `ADMIN` | `OWNER` |
|---|---|---|---|---|
| Create / submit own order | Yes (own `customer_ref`) | No | Yes | Yes |
| View own order & customer-visible timeline | Yes (own `customer_ref`) | All orders | All orders | All orders |
| View another customer's order | **No (`403`)** | Operational | Yes | Yes |
| Confirm quoted price (`AWAITING_CUSTOMER_CONFIRMATION -> CONFIRMED`) | Yes (own) | No | With evidence | With evidence |
| Cancel unconfirmed order (`DRAFT`..`AWAITING_CUSTOMER_CONFIRMATION`) | Yes (own) | No | Yes | Yes |
| Cancel confirmed / active workshop order (`CONFIRMED`..`READY`, `ON_HOLD`) | **No (`403`)** | **No (`403`)** | Yes | Yes |
| Authorize `is_urgent=true` | **No (`403`)** | **No (`403`)** | Yes | Yes |
| Manage workshop tasks & forward workshop transitions | No | Yes | Yes | Yes |
| Place on `ON_HOLD` / resume | No | Yes | Yes | Yes |
| Single-step `is_admin_correction` rollback | No | **No (`403`)** | Yes | Yes |
| Record delivery (`READY -> DELIVERED`) | No | Yes | Yes | Yes |
| Mark `COMPLETED` (`DELIVERED -> COMPLETED`) | No | **No (`403`)** | Yes | Yes |
| Add / read `INTERNAL` notes | **Never** | Yes | Yes | Yes |
| Modify capacity settings (`/api/v1/capacity/settings`) | No | **No (`403`)** | Yes | Yes |
| Access `/api/v1/admin/*` (orders, audit, notifications) | No | **No (`403`)** | Yes | Yes |

---

## 3. Privacy & Data Protection Controls

1. **Order ID Never Grants Access Alone:** `GET /api/v1/tracking/{order_reference}` rejects bare order references with `401 UNAUTHORIZED`. Callers must present either an owning `CUSTOMER` Bearer token, a staff Bearer token, or the high-entropy `tracking_token` (`trk_...`) returned once at order creation.
2. **Hashed Tracking Tokens:** Only the keyed HMAC-SHA256 digest (`tracking_token_hash`) bound to `public_order_ref` is stored in the database — plaintext tracking tokens are never persisted.
3. **Internal Note Isolation:** `app/api/serializers.py` and `TrackingService` strictly filter out `NoteVisibility.INTERNAL` records and internal staff `actor_id`s on customer responses.
4. **Measurement Privacy:** Raw body dimensions (`chest`, `waist`, etc.) are omitted from `/api/v1/tracking/{order_reference}` and redacted on customer `/snapshots` responses, remaining accessible only to authorized tailoring/admin staff.
5. **SQL Injection & Input Hardening:** All database queries use parameterized SQLAlchemy 2.0 Core/ORM statements; Pydantic v2 schemas enforce `extra="forbid"`, length bounds, and regex reference validation (`SAFE_REF_PATTERN`).
6. **Safe Error Handling:** `SQLAlchemyError` and unhandled exceptions return generic error envelopes (`DATABASE_ERROR`, `INTERNAL_SERVER_ERROR`) without exposing SQL statements, stack traces, or customer attributes.
7. **Immutable Audit & Snapshot Records:** SQLAlchemy `before_update` and `before_delete` hooks on `OrderSnapshot` and `OrderEvent` block mutation or deletion even from internal Python code.
8. **Idempotency Payload Integrity:** Order creation requests carrying an `Idempotency-Key` persist a canonical, secret-free SHA-256 payload digest (`orders.idempotency_fingerprint`). Reusing an existing key for the same `customer_ref` with any altered creation attribute returns `409 IDEMPOTENCY_KEY_REUSED`, and the digest is never exposed in API responses.

---

## 4. Known Security Limitations Before Production

- **Shared Identity Provider Integration Pending:** `HmacBearerAuthAdapter` must be wired to Module 01 / Module 08's finalized JWT/JWKS or session verification contract once approved.
- **Process-Local Rate Limiter:** `SlidingWindowRateLimiter` protects single-instance deployments; multi-replica production deployments should enforce distributed rate limiting at the reverse proxy / Redis layer.
- **Database-Level Append-Only Permissions:** In PostgreSQL production deployments, complement ORM immutability listeners by revoking SQL `UPDATE` and `DELETE` privileges on `order_snapshots` and `order_events` for the application database role.
