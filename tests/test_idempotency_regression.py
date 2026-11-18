"""Regression tests for Idempotency-Key SHA-256 request fingerprinting & migration 0002."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text

from app.core.enums import ActorRole
from app.core.exceptions import ConflictError
from app.core.security import Principal
from app.models.entities import Order
from app.services.lifecycle_engine import LifecycleEngine
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.snapshot_service import SnapshotService
from tests.conftest import build_valid_order_payload


def test_identical_payload_and_identical_key_replays_and_never_exposes_fingerprint(
    client: TestClient,
    app,
    customer1_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    headers = {**customer1_headers, "Idempotency-Key": "IDEM-FP-EXACT-01"}
    payload_1 = build_valid_order_payload(
        submission_reference="SUB-FP-01",
        items=[
            {
                "garment_type": "shirt",
                "quantity": 1,
                "design_ref": "DSG-001",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-001",
                "customization_data": {"cuff_contrast": False, "monogram": "none"},
            }
        ],
    )
    # Reorder nested JSON dict keys to verify canonical normalization matches identically
    payload_2 = build_valid_order_payload(
        submission_reference="SUB-FP-01",
        items=[
            {
                "garment_type": "SHIRT",
                "quantity": 1,
                "design_ref": "DSG-001",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-001",
                "customization_data": {"monogram": "none", "cuff_contrast": False},
            }
        ],
    )

    first = client.post("/api/v1/orders", json=payload_1, headers=headers)
    assert first.status_code == 201, first.text
    first_body = first.json()
    order_ref = first_body["order_reference"]
    tracking_token = first_body["tracking_token"]

    retry = client.post("/api/v1/orders", json=payload_2, headers=headers)
    assert retry.status_code == 200, retry.text
    retry_body = retry.json()
    assert retry_body["idempotent_replay"] is True
    assert retry_body["order_reference"] == order_ref
    assert retry_body["id"] == first_body["id"]

    # Verify fingerprint is persisted in DB as 64-char SHA-256 hex digest
    with app.state.session_factory() as session:
        row = session.query(Order).filter(Order.public_order_ref == order_ref).one()
        assert row.idempotency_fingerprint is not None
        assert len(row.idempotency_fingerprint) == 64
        fp_hex = row.idempotency_fingerprint

    # Verify fingerprint NEVER leaks in customer, tracking, or admin API responses
    get_cust = client.get(f"/api/v1/orders/{order_ref}", headers=customer1_headers)
    get_list = client.get("/api/v1/orders", headers=customer1_headers)
    get_track = client.get(
        f"/api/v1/tracking/{order_ref}",
        headers={"X-Tracking-Token": tracking_token},
    )
    get_admin = client.get(f"/api/v1/admin/orders/{order_ref}", headers=admin_headers)

    for resp in (first, retry, get_cust, get_list, get_track, get_admin):
        raw_text = resp.text
        assert "idempotency_fingerprint" not in raw_text
        assert fp_hex not in raw_text


def test_different_instructions_with_same_key_returns_409(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    headers = {**customer1_headers, "Idempotency-Key": "IDEM-DIFF-INSTR"}
    original = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(customer_instructions="Regular collar stiffness"),
        headers=headers,
    )
    assert original.status_code == 201

    conflict = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(customer_instructions="Extra soft collar lining"),
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"

    # Original order instructions remain untouched
    fetched = client.get(
        f"/api/v1/orders/{original.json()['order_reference']}",
        headers=customer1_headers,
    ).json()
    assert fetched["customer_instructions"] == "Regular collar stiffness"


def test_different_garment_details_with_same_key_returns_409(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    headers = {**customer1_headers, "Idempotency-Key": "IDEM-DIFF-GARMENT"}
    original = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(),
        headers=headers,
    )
    assert original.status_code == 201

    mutated_item_variants = [
        # Different quantity
        [
            {
                "garment_type": "shirt",
                "quantity": 2,
                "design_ref": "DSG-001",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-001",
                "preview_3d_ref": "PRV-001",
                "customization_data": {"monogram": False},
            }
        ],
        # Different garment_type & design_ref
        [
            {
                "garment_type": "shirt_and_pant_set",
                "quantity": 1,
                "design_ref": "DSG-002",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-001",
                "preview_3d_ref": "PRV-001",
                "customization_data": {"monogram": False},
            }
        ],
        # Different fabric_source & fabric_ref
        [
            {
                "garment_type": "shirt",
                "quantity": 1,
                "design_ref": "DSG-001",
                "fabric_source": "BUSINESS_INVENTORY",
                "fabric_ref": "FAB-001",
                "fabric_variant_ref": "FVAR-001",
                "preview_3d_ref": "PRV-001",
                "customization_data": {"monogram": False},
            }
        ],
        # Different customization_data
        [
            {
                "garment_type": "shirt",
                "quantity": 1,
                "design_ref": "DSG-001",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-001",
                "preview_3d_ref": "PRV-001",
                "customization_data": {"monogram": True},
            }
        ],
    ]

    for mutated_items in mutated_item_variants:
        resp = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(items=mutated_items),
            headers=headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"


def test_different_measurement_reference_with_same_key_returns_409(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    headers = {**customer1_headers, "Idempotency-Key": "IDEM-DIFF-MEAS"}
    original = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(measurement_ref="MEA-001"),
        headers=headers,
    )
    assert original.status_code == 201

    # Valid alternate measurement owned by CUS-001 ("MEA-001-ALT") with reused key -> 409
    conflict = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(measurement_ref="MEA-001-ALT"),
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"


def test_same_payload_with_different_keys_creates_distinct_orders_and_preserves_customer_isolation(
    client: TestClient,
    customer1_headers: dict[str, str],
    customer2_headers: dict[str, str],
) -> None:
    payload = build_valid_order_payload()
    r1 = client.post(
        "/api/v1/orders",
        json=payload,
        headers={**customer1_headers, "Idempotency-Key": "KEY-ONE"},
    )
    r2 = client.post(
        "/api/v1/orders",
        json=payload,
        headers={**customer1_headers, "Idempotency-Key": "KEY-TWO"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["order_reference"] != r2.json()["order_reference"]

    # Customer 2 using "KEY-ONE" for their own order creates Customer 2's separate order
    c2_payload = build_valid_order_payload(
        customer_ref="CUS-002", measurement_ref="MEA-002"
    )
    r_c2 = client.post(
        "/api/v1/orders",
        json=c2_payload,
        headers={**customer2_headers, "Idempotency-Key": "KEY-ONE"},
    )
    assert r_c2.status_code == 201
    assert r_c2.json()["customer_ref"] == "CUS-002"
    assert r_c2.json()["order_reference"] != r1.json()["order_reference"]


def test_concurrent_conflicting_and_identical_requests_cannot_create_inconsistent_records(
    client: TestClient, app, customer1_headers: dict[str, str]
) -> None:
    shared_headers = {**customer1_headers, "Idempotency-Key": "CONCURRENT-MIXED-KEY"}

    def worker(idx: int) -> tuple[int, str, str | None]:
        variant = "Variant-A" if idx % 2 == 0 else "Variant-B"
        r = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(customer_instructions=variant),
            headers=shared_headers,
        )
        body = r.json()
        return (
            r.status_code,
            variant,
            body.get("order_reference") or body.get("error_code"),
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(worker, range(6)))

    created_entries = [r for r in results if r[0] == 201]
    assert len(created_entries) == 1
    winning_variant = created_entries[0][1]
    winning_order_ref = created_entries[0][2]

    for status_code, variant, ref_or_err in results:
        if variant == winning_variant:
            assert status_code in (200, 201)
            assert ref_or_err == winning_order_ref
        else:
            assert status_code == 409
            assert ref_or_err == "IDEMPOTENCY_KEY_REUSED"

    # Also directly exercise simultaneous two-session IntegrityError recovery with mismatched payload
    session_1 = app.state.session_factory()
    session_2 = app.state.session_factory()
    try:
        notif = NotificationService(app.state.adapters.notification)
        snap = SnapshotService(app.state.adapters)
        life = LifecycleEngine(snapshot_service=snap, notification_service=notif)
        svc = OrderService(
            settings=app.state.settings,
            adapters=app.state.adapters,
            lifecycle_engine=life,
            snapshot_service=snap,
            notification_service=notif,
        )
        principal = Principal(actor_id="CUS-001", role=ActorRole.CUSTOMER)

        # Session 1 commits key "RACE-DIRECT-KEY" with instructions "Alpha"
        res1 = svc.create_order(
            session_1,
            principal=principal,
            customer_ref="CUS-001",
            measurement_ref="MEA-001",
            quotation_ref="QUO-001",
            idempotency_key="RACE-DIRECT-KEY",
            customer_instructions="Alpha",
            items_payload=build_valid_order_payload()["items"],
        )
        assert res1.idempotent_replay is False

        # Simulate IntegrityError recovery path directly when pre-check was bypassed by concurrency
        from sqlalchemy import select as sa_select

        orig_scalar = session_2.scalar
        call_counter = {"count": 0}

        def _skip_first_lookup(stmt, *args, **kwargs):
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                return None
            return orig_scalar(stmt, *args, **kwargs)

        session_2.scalar = _skip_first_lookup  # type: ignore[method-assign]
        with pytest.raises(ConflictError) as exc_info:
            svc.create_order(
                session_2,
                principal=principal,
                customer_ref="CUS-001",
                measurement_ref="MEA-001",
                quotation_ref="QUO-001",
                idempotency_key="RACE-DIRECT-KEY",
                customer_instructions="Beta-Different",
                items_payload=build_valid_order_payload()["items"],
            )
        assert exc_info.value.error_code == "IDEMPOTENCY_KEY_REUSED"
        assert sa_select is not None
    finally:
        session_1.close()
        session_2.close()


def test_legacy_pre_migration_row_and_alembic_0001_to_0002_upgrade_preserve_existing_records(
    client: TestClient, app, customer1_headers: dict[str, str], tmp_path: Path
) -> None:
    # 1. Simulate a pre-migration legacy record by nulling out idempotency_fingerprint
    headers = {**customer1_headers, "Idempotency-Key": "LEGACY-PRE-0002"}
    payload = build_valid_order_payload(customer_instructions="Legacy order note")
    created = client.post("/api/v1/orders", json=payload, headers=headers)
    assert created.status_code == 201
    order_ref = created.json()["order_reference"]

    with app.state.session_factory() as session:
        row = session.query(Order).filter(Order.public_order_ref == order_ref).one()
        row.idempotency_fingerprint = None
        session.commit()

    # Identical retry on legacy NULL-fingerprint row still succeeds with 200
    ok_retry = client.post("/api/v1/orders", json=payload, headers=headers)
    assert ok_retry.status_code == 200
    assert ok_retry.json()["idempotent_replay"] is True
    assert ok_retry.json()["order_reference"] == order_ref

    # Mismatched payload on legacy NULL-fingerprint row still returns 409 IDEMPOTENCY_KEY_REUSED
    bad_retry = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(customer_instructions="Tampered legacy note"),
        headers=headers,
    )
    assert bad_retry.status_code == 409
    assert bad_retry.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"

    # 2. Verify Alembic migration from 0001_initial with existing data -> 0002_idempotency_fingerprint
    mig_db = tmp_path / "legacy_upgrade_test.sqlite3"
    db_url = f"sqlite:///{mig_db}"
    env = {"PATH": str(Path(sys.executable).parent), "DATABASE_URL": db_url}
    alembic_bin = str(Path(sys.executable).parent / "alembic")

    r_0001 = subprocess.run(
        [alembic_bin, "upgrade", "0001_initial"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_0001.returncode == 0, r_0001.stderr

    # Insert an order row under schema 0001_initial
    eng = create_engine(db_url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO orders ("
                "public_order_ref, customer_ref, current_status, order_source, "
                "idempotency_key, currency, measurement_ref, customer_price_confirmed, "
                "is_urgent, tracking_token_hash, rework_count, version, created_at, updated_at"
                ") VALUES ("
                "'ORD-MIG-01', 'CUS-001', 'DRAFT', 'MODULE_01_PLATFORM', "
                "'KEY-MIG-01', 'INR', 'MEA-001', 0, 0, 'hash123', 0, 1, "
                "'2026-11-18T00:00:00Z', '2026-11-18T00:00:00Z'"
                ")"
            )
        )

    # Upgrade to head (0002_idempotency_fingerprint) and verify row survives with NULL fingerprint
    r_head = subprocess.run(
        [alembic_bin, "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r_head.returncode == 0, r_head.stderr

    with eng.connect() as conn:
        migrated_row = conn.execute(
            text(
                "SELECT public_order_ref, idempotency_key, idempotency_fingerprint "
                "FROM orders WHERE public_order_ref = 'ORD-MIG-01'"
            )
        ).one()
        assert migrated_row[0] == "ORD-MIG-01"
        assert migrated_row[1] == "KEY-MIG-01"
        assert migrated_row[2] is None
    eng.dispose()
