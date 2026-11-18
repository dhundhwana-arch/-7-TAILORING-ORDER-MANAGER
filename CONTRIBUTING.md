# Contributing to Module 07 — Tailoring Order Manager

Thank you for contributing to **CUSTOM SHIRT STUDIO (Module 07/08: Tailoring Order Manager)**.

## 1. Core Engineering Rules

1. **Preserve Module Boundaries:**
   - Never calculate official garment prices inside Module 07 (owned by **Module 05**).
   - Never mutate confirmed `OrderSnapshot` or `OrderEvent` rows.
   - Never compute or promise automatic delivery dates from machine counts or reference daily capacity.
   - Never expose `INTERNAL` workshop notes or raw customer body measurements on customer/public tracking APIs.
2. **Centralized Lifecycle:** All order status transitions must go through `app/services/lifecycle_engine.py` (`LifecycleEngine.transition`). Never mutate `order.current_status` directly inside API routers.
3. **Zero Real Customer Data or Secrets:** Use synthetic illustrative IDs (`CUS-001`, `DSG-001`, `FAB-001`, `MEA-001`, `QUO-001`) in tests and docs. Never commit `.env` files, API keys, or personal customer information.
4. **No Real Notifications in Development:** Keep `NOTIFICATION_PROVIDER=mock` or `disabled` in local and test environments.

## 2. Safe Branch & Pull Request Workflow

- Never push directly to `main` or force-push shared history.
- Work on a dedicated feature/development branch off `main`.
- Run migrations and the full test suite before committing:
  ```bash
  .venv/bin/alembic upgrade head
  .venv/bin/pytest -v --cov=app --cov-report=term-missing
  ```
- Open a Pull Request targeting `main` and await review and explicit approval from Project Owner **DIVYESH BAMBHANIYA** before merging.
