"""Categories F & G: Immutable Audit History and Concurrency Protection Tests."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from app.core.enums import OrderStatus
from app.core.exceptions import ConcurrencyConflictError, ImmutableRecordError
from app.core.security import Principal
from app.models.entities import Order, OrderEvent
from app.services.lifecycle_engine import LifecycleEngine
from app.services.notification_service import NotificationService
from app.services.snapshot_service import SnapshotService
from tests.conftest import build_valid_order_payload


def test_audit_history_records_actor_timestamps_and_blocks_tampering(
    client: TestClient,
    app,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    ).json()
    order_ref = created["order_reference"]

    # Valid transition creates event
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW", "reason": "Assigned for initial check"},
        headers=tailor_headers,
    )

    # Failed transition rolls back cleanly and does NOT create an event
    bad = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "COMPLETED"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # Retrieve history via admin audit endpoint
    audit = client.get(
        f"/api/v1/admin/audit?order_reference={order_ref}", headers=admin_headers
    ).json()
    assert audit["total"] == 2
    events = list(reversed(audit["items"]))
    assert events[0]["event_type"] == "ORDER_SUBMITTED"
    assert events[0]["actor_id"] == "CUS-001"
    assert events[0]["actor_role"] == "CUSTOMER"
    assert events[1]["event_type"] == "STATUS_TRANSITION"
    assert events[1]["previous_status"] == "SUBMITTED"
    assert events[1]["new_status"] == "UNDER_REVIEW"
    assert events[1]["actor_id"] == "STF-TAILOR-01"
    assert events[1]["created_at"] is not None

    # Verify ORM immutability prevents altering or deleting audit events
    with app.state.session_factory() as session:
        ev = session.query(OrderEvent).first()
        assert ev is not None
        ev.actor_id = "TAMPERED"
        with pytest.raises(ImmutableRecordError):
            session.flush()
        session.rollback()

        ev2 = session.query(OrderEvent).first()
        session.delete(ev2)
        with pytest.raises(ImmutableRecordError):
            session.flush()
        session.rollback()


def test_optimistic_locking_rejects_stale_expected_version_and_concurrent_sessions(
    client: TestClient,
    app,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    ).json()
    order_ref = created["order_reference"]
    initial_version = created["version"]
    assert initial_version == 1

    # Tailor transitions with expected_version=1 -> version becomes 2
    r1 = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW", "expected_version": 1},
        headers=tailor_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["version"] == 2

    # Concurrent admin update still holding stale expected_version=1 -> 409 CONCURRENCY_CONFLICT!
    stale = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "ON_HOLD",
            "reason": "Stale admin hold",
            "expected_version": 1,
        },
        headers=admin_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "CONCURRENCY_CONFLICT"

    # Also test two simultaneous overlapping ORM sessions (both read version=2 before either flushes)
    session_a = app.state.session_factory()
    session_b = app.state.session_factory()
    try:
        order_a = (
            session_a.query(Order)
            .filter(Order.public_order_ref == order_ref)
            .one()
        )
        order_b = (
            session_b.query(Order)
            .filter(Order.public_order_ref == order_ref)
            .one()
        )
        assert order_a.version == 2 and order_b.version == 2

        engine_svc = LifecycleEngine(
            snapshot_service=SnapshotService(app.state.adapters),
            notification_service=NotificationService(app.state.adapters.notification),
        )
        from app.core.enums import ActorRole

        tailor_p = Principal(actor_id="STF-TAILOR-01", role=ActorRole.TAILOR)
        admin_p = Principal(actor_id="STF-ADMIN-01", role=ActorRole.ADMIN)

        # Session A transitions UNDER_REVIEW -> QUOTE_PENDING and commits
        engine_svc.transition(
            session_a,
            order=order_a,
            target_status=OrderStatus.QUOTE_PENDING,
            principal=tailor_p,
        )
        session_a.commit()

        # Session B (which already loaded stale version=2) tries UNDER_REVIEW -> ON_HOLD -> StaleDataError -> ConcurrencyConflictError!
        with pytest.raises(ConcurrencyConflictError):
            engine_svc.transition(
                session_b,
                order=order_b,
                target_status=OrderStatus.ON_HOLD,
                principal=admin_p,
                reason="Simultaneous session conflict",
            )
    finally:
        session_a.close()
        session_b.close()


def test_multithreaded_concurrent_duplicate_submissions_and_idempotency(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    def submit_duplicate(_idx: int) -> int:
        r = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(
                submission_reference="CONCURRENT-SUB-99"
            ),
            headers=customer1_headers,
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(submit_duplicate, range(4)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 3

    def submit_idempotent(_idx: int) -> tuple[int, str]:
        r = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(
                submission_reference="CONCURRENT-IDEM-SUB"
            ),
            headers={**customer1_headers, "Idempotency-Key": "CONCURRENT-IDEM-KEY"},
        )
        return r.status_code, r.json()["order_reference"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        idem_results = list(pool.map(submit_idempotent, range(4)))

    codes = [c for c, _ in idem_results]
    refs = {ref for _, ref in idem_results}
    assert all(c in (200, 201) for c in codes)
    assert len(refs) == 1
