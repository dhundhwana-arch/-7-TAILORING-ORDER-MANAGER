"""Categories J & K: Notifications, API Error Handling, Pagination, Database Errors, and Alembic Migrations."""

from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.adapters.registry import AdapterRegistry
from tests.conftest import build_valid_order_payload


def test_notification_events_and_mock_provider_failure_resilience(
    client: TestClient,
    mock_adapters: AdapterRegistry,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    # 1. Normal mock delivery records SENT_MOCK without any external calls
    r1 = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    )
    assert r1.status_code == 201
    order_ref = r1.json()["order_reference"]
    assert len(mock_adapters.notification.sent_messages) == 1  # type: ignore[attr-defined]

    # 2. Simulate notification provider failure -> order transition STILL succeeds, notification marked FAILED!
    mock_adapters.notification.set_failure_mode(True)  # type: ignore[attr-defined]
    try:
        r2 = client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": "UNDER_REVIEW"},
            headers=tailor_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["current_status"] == "UNDER_REVIEW"
    finally:
        mock_adapters.notification.set_failure_mode(False)  # type: ignore[attr-defined]

    notifs = client.get(
        f"/api/v1/admin/notifications?order_reference={order_ref}",
        headers=admin_headers,
    ).json()
    assert notifs["total"] == 2
    statuses = {n["event_type"]: n["delivery_status"] for n in notifs["items"]}
    assert statuses["ORDER_SUBMITTED"] == "SENT_MOCK"
    assert statuses["ORDER_REVIEWED"] == "FAILED"


def test_api_pagination_not_found_extra_fields_and_database_error_handling(
    client: TestClient,
    app,
    monkeypatch,
    customer1_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    # Health check
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    # Extra unknown fields rejected with 422
    bad_body = build_valid_order_payload(unexpected_field="boom")
    assert (
        client.post("/api/v1/orders", json=bad_body, headers=customer1_headers).status_code
        == 422
    )

    # Not found -> 404
    nf = client.get("/api/v1/orders/ORD-DOES-NOT-EXIST", headers=admin_headers)
    assert nf.status_code == 404
    assert nf.json()["error_code"] == "NOT_FOUND"

    # Create 5 orders and verify pagination math
    for i in range(5):
        res = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(submission_reference=f"PAGE-SUB-{i}"),
            headers=customer1_headers,
        )
        assert res.status_code == 201

    p1 = client.get(
        "/api/v1/admin/orders?page=1&page_size=2", headers=admin_headers
    ).json()
    assert p1["total"] == 5
    assert p1["pages"] == 3
    assert len(p1["items"]) == 2

    p3 = client.get(
        "/api/v1/admin/orders?page=3&page_size=2", headers=admin_headers
    ).json()
    assert len(p3["items"]) == 1

    # Simulate unexpected SQLAlchemyError -> returns safe 500 DATABASE_ERROR JSON
    from app.services.order_service import OrderService

    def _boom(*_args, **_kwargs):
        raise OperationalError("SELECT secret_internal_sql", {}, Exception("db down"))

    monkeypatch.setattr(OrderService, "list_orders", _boom)
    db_err = client.get("/api/v1/orders", headers=customer1_headers)
    assert db_err.status_code == 500
    err_json = db_err.json()
    assert err_json["error_code"] == "DATABASE_ERROR"
    assert "secret_internal_sql" not in str(err_json)


def test_alembic_upgrade_and_downgrade_roundtrip(tmp_path: Path) -> None:
    mig_db = tmp_path / "alembic_roundtrip.sqlite3"
    env = {
        "PATH": str(Path(sys.executable).parent),
        "DATABASE_URL": f"sqlite:///{mig_db}",
    }
    alembic_bin = str(Path(sys.executable).parent / "alembic")

    up = subprocess.run(
        [alembic_bin, "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert up.returncode == 0, up.stderr

    down = subprocess.run(
        [alembic_bin, "downgrade", "base"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert down.returncode == 0, down.stderr

    up2 = subprocess.run(
        [alembic_bin, "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert up2.returncode == 0, up2.stderr
