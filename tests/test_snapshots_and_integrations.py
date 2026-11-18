"""Categories C, D, E: Price Snapshots, Measurement Snapshots, Design/Fabric/Preview Adapters."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.adapters.contracts import MeasurementRecord, QuotationRecord
from app.adapters.http_adapters import (
    HttpDesignConfigAdapter,
    HttpMeasurementAdapter,
    HttpPreviewReferenceAdapter,
    HttpPricingAdapter,
)
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ImmutableRecordError, IntegrationError
from app.models.entities import OrderSnapshot
from tests.conftest import build_valid_order_payload


def test_expired_and_invalid_quotations_rejected(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    for bad_q, expected_code in (
        ("QUO-NONEXISTENT", "INVALID_QUOTATION_REFERENCE"),
        ("QUO-EXPIRED", "EXPIRED_OR_INVALID_QUOTATION"),
        ("QUO-REVOKED", "EXPIRED_OR_INVALID_QUOTATION"),
    ):
        resp = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(quotation_ref=bad_q),
            headers=customer1_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == expected_code


def test_confirmed_price_and_measurement_snapshots_preserved_after_upstream_changes(
    client: TestClient,
    app,
    mock_adapters: AdapterRegistry,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    # Create, submit, review, and confirm order with QUO-001 (INR 450.00) and MEA-001 (v1, chest=100.0)
    created = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    ).json()
    order_ref = created["order_reference"]

    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW"},
        headers=tailor_headers,
    )
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "AWAITING_CUSTOMER_CONFIRMATION"},
        headers=tailor_headers,
    )
    confirmed = client.post(
        f"/api/v1/orders/{order_ref}/confirm",
        json={"accepted_quotation_ref": "QUO-001"},
        headers=customer1_headers,
    )
    assert confirmed.status_code == 200

    # Simulate later upstream changes in Module 05 (price bump to 600.00) and Module 06 (profile_version=2, chest=108.0)
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    mock_adapters.pricing.register_quotation(  # type: ignore[attr-defined]
        QuotationRecord(
            quotation_id="QUO-001",
            quoted_amount=Decimal("600.00"),
            currency="INR",
            price_breakdown={"stitching_fee": "600.00"},
            quotation_status="VALID",
            pricing_config_version="v2.0.0-updated",
            quotation_timestamp=now,
            valid_until=now + timedelta(days=30),
        )
    )
    mock_adapters.measurement.register_measurement(  # type: ignore[attr-defined]
        MeasurementRecord(
            measurement_id="MEA-001",
            customer_ref="CUS-001",
            profile_version=2,
            validation_status="VALIDATED",
            approval_status="APPROVED",
            measurements={"unit": "cm", "chest": 108.0, "waist": 94.0},
            recorded_at=now,
        )
    )

    # Silent PATCH on confirmed order quotation_ref or measurement_ref must fail!
    silent_patch = client.patch(
        f"/api/v1/orders/{order_ref}",
        json={"quotation_ref": "QUO-002"},
        headers=admin_headers,
    )
    assert silent_patch.status_code == 422
    assert silent_patch.json()["error_code"] == "CONFIRMED_ORDER_PROTECTED"

    # Inspect confirmed snapshot via admin endpoint -> MUST preserve INR 450.00 & profile_version=1 (chest=100.0)!
    detail = client.get(
        f"/api/v1/admin/orders/{order_ref}", headers=admin_headers
    ).json()
    snaps = detail["full_snapshots"]
    assert len(snaps) == 1
    assert snaps[0]["snapshot_version"] == 1
    assert snaps[0]["confirmed_amount"] == "450.00"
    assert snaps[0]["quotation_snapshot"]["pricing_config_version"] == "v1.0.0-mock"
    assert snaps[0]["measurement_snapshot"]["profile_version"] == 1
    assert snaps[0]["measurement_snapshot"]["measurements"]["chest"] == 100.0

    # Verify ORM-level immutability guard blocks direct snapshot UPDATE or DELETE
    with app.state.session_factory() as session:
        snap_row = session.query(OrderSnapshot).first()
        assert snap_row is not None
        snap_row.confirmed_amount = Decimal("999.00")
        with pytest.raises(ImmutableRecordError):
            session.flush()
        session.rollback()

        snap_row2 = session.query(OrderSnapshot).first()
        session.delete(snap_row2)
        with pytest.raises(ImmutableRecordError):
            session.flush()
        session.rollback()


def test_explicit_requotation_and_reconfirmation_creates_snapshot_v2_preserving_v1(
    client: TestClient,
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

    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW"},
        headers=tailor_headers,
    )
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "AWAITING_CUSTOMER_CONFIRMATION"},
        headers=tailor_headers,
    )
    client.post(
        f"/api/v1/orders/{order_ref}/confirm",
        json={"accepted_quotation_ref": "QUO-001"},
        headers=customer1_headers,
    )

    # Admin explicitly re-opens confirmation for approved urgent re-quotation
    reopen = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "AWAITING_CUSTOMER_CONFIRMATION",
            "reason": "Customer requested urgent turnaround re-quotation",
        },
        headers=admin_headers,
    )
    assert reopen.status_code == 200

    # Attach QUO-002 (INR 500.00) while in AWAITING_CUSTOMER_CONFIRMATION
    patched = client.patch(
        f"/api/v1/orders/{order_ref}",
        json={"quotation_ref": "QUO-002", "is_urgent": True},
        headers=admin_headers,
    )
    assert patched.status_code == 200

    # Customer reconfirms QUO-002 -> creates Snapshot v2 while preserving v1!
    reconfirmed = client.post(
        f"/api/v1/orders/{order_ref}/confirm",
        json={"accepted_quotation_ref": "QUO-002"},
        headers=customer1_headers,
    )
    assert reconfirmed.status_code == 200
    snaps = reconfirmed.json()["snapshots"]
    assert len(snaps) == 2
    assert snaps[0]["snapshot_version"] == 1
    assert snaps[0]["confirmed_amount"] == "450.00"
    assert snaps[1]["snapshot_version"] == 2
    assert snaps[1]["snapshot_type"] == "REQUOTATION_RECONFIRMATION"
    assert snaps[1]["confirmed_amount"] == "500.00"


def test_unvalidated_measurement_flagged_in_review_and_blocked_at_confirmation(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(
            measurement_ref="MEA-UNVALIDATED", submit_immediately=True
        ),
        headers=customer1_headers,
    )
    assert created.status_code == 201
    order_ref = created.json()["order_reference"]

    # Order Review identifies unvalidated measurement
    review = client.post(
        f"/api/v1/orders/{order_ref}/review", headers=tailor_headers
    ).json()
    assert review["measurement_verified"] is False
    assert review["ready_for_customer_confirmation"] is False
    assert any("not yet validated" in msg for msg in review["missing_or_issues"])

    # Advance to AWAITING_CUSTOMER_CONFIRMATION and try confirming -> blocked!
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW"},
        headers=tailor_headers,
    )
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "AWAITING_CUSTOMER_CONFIRMATION"},
        headers=tailor_headers,
    )
    confirm = client.post(
        f"/api/v1/orders/{order_ref}/confirm",
        json={"accepted_quotation_ref": "QUO-001"},
        headers=customer1_headers,
    )
    assert confirm.status_code == 422
    assert confirm.json()["error_code"] == "UNVALIDATED_MEASUREMENT_PROFILE"


def test_design_fabric_preview_validation_and_adapter_failures(
    client: TestClient,
    mock_adapters: AdapterRegistry,
    customer1_headers: dict[str, str],
) -> None:
    # Invalid design config
    r_bad_design = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(
            items=[
                {
                    "garment_type": "shirt",
                    "quantity": 1,
                    "design_ref": "DSG-INVALID",
                    "fabric_source": "CUSTOMER_SUPPLIED",
                    "fabric_ref": "CUST-01",
                }
            ]
        ),
        headers=customer1_headers,
    )
    assert r_bad_design.status_code == 422
    assert r_bad_design.json()["error_code"] == "INVALID_DESIGN_CONFIGURATION"

    # Out-of-stock catalogue fabric
    r_out_fabric = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(
            items=[
                {
                    "garment_type": "shirt",
                    "quantity": 1,
                    "design_ref": "DSG-001",
                    "fabric_source": "BUSINESS_INVENTORY",
                    "fabric_ref": "FAB-OUT",
                }
            ]
        ),
        headers=customer1_headers,
    )
    assert r_out_fabric.status_code == 422
    assert r_out_fabric.json()["error_code"] == "UNAVAILABLE_FABRIC"

    # Missing 3D preview reference
    r_bad_preview = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(
            items=[
                {
                    "garment_type": "shirt",
                    "quantity": 1,
                    "design_ref": "DSG-001",
                    "fabric_source": "CUSTOMER_SUPPLIED",
                    "fabric_ref": "CUST-01",
                    "preview_3d_ref": "PRV-MISSING",
                }
            ]
        ),
        headers=customer1_headers,
    )
    assert r_bad_preview.status_code == 422
    assert r_bad_preview.json()["error_code"] == "INVALID_PREVIEW_REFERENCE"

    # Upstream adapter failure -> HTTP 502 UPSTREAM_INTEGRATION_ERROR
    mock_adapters.design.set_failure_mode(True)  # type: ignore[attr-defined]
    try:
        r_fail = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(),
            headers=customer1_headers,
        )
        assert r_fail.status_code == 502
        assert r_fail.json()["error_code"] == "UPSTREAM_INTEGRATION_ERROR"
    finally:
        mock_adapters.design.set_failure_mode(False)  # type: ignore[attr-defined]

    # Verify unverified live HTTP adapters refuse to fabricate contracts
    with pytest.raises(IntegrationError):
        HttpPricingAdapter("http://localhost:8005").get_quotation("QUO-001")
    with pytest.raises(IntegrationError):
        HttpMeasurementAdapter("http://localhost:8006").get_measurement("MEA-001")
    with pytest.raises(IntegrationError):
        HttpDesignConfigAdapter("http://localhost:8003").get_design("DSG-001")
    with pytest.raises(IntegrationError):
        HttpPreviewReferenceAdapter("http://localhost:8004").get_preview("PRV-001")
