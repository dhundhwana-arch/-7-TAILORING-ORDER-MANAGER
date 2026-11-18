"""Category A: Order Creation, Validation, Duplicate Protection, and Idempotency Tests."""

from fastapi.testclient import TestClient

from tests.conftest import build_valid_order_payload


def test_valid_draft_order_creation_and_never_auto_confirmed(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    payload = build_valid_order_payload()
    resp = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["order_reference"].startswith("ORD-")
    assert data["current_status"] == "DRAFT"
    assert data["customer_price_confirmed"] is False
    assert data["tracking_token"].startswith("trk_")
    assert data["idempotent_replay"] is False
    assert data["version"] == 1
    assert len(data["items"]) == 1
    assert data["snapshots"] == []


def test_valid_submitted_order_creation_with_catalogue_fabric_and_multi_item(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    payload = build_valid_order_payload(
        order_reference="ORD-001",
        quotation_ref="QUO-CAT-001",
        submit_immediately=True,
        items=[
            {
                "garment_type": "shirt",
                "quantity": 2,
                "design_ref": "DSG-001",
                "fabric_source": "BUSINESS_INVENTORY",
                "fabric_ref": "FAB-001",
                "fabric_variant_ref": "FVAR-001",
                "customization_data": {"collar": "classic"},
            },
            {
                "garment_type": "shirt_and_pant_set",
                "quantity": 1,
                "design_ref": "DSG-002",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-002",
            },
        ],
    )
    resp = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["order_reference"] == "ORD-001"
    # Even when submit_immediately=True, it enters SUBMITTED, NEVER CONFIRMED
    assert data["current_status"] == "SUBMITTED"
    assert len(data["items"]) == 2
    assert data["quoted_amount"] == "1250.00"


def test_missing_customer_reference_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    payload = build_valid_order_payload()
    payload.pop("customer_ref")
    resp = client.post("/api/v1/orders", json=payload, headers=admin_headers)
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "REQUEST_VALIDATION_ERROR"


def test_missing_design_reference_rejected(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    payload = build_valid_order_payload()
    payload["items"][0].pop("design_ref")
    resp = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert resp.status_code == 422


def test_missing_measurement_reference_rejected(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    payload = build_valid_order_payload()
    payload.pop("measurement_ref")
    resp = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert resp.status_code == 422


def test_missing_quotation_allowed_at_submission_but_required_before_confirmation(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    payload = build_valid_order_payload(quotation_ref=None, submit_immediately=True)
    resp = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert resp.status_code == 201
    order_ref = resp.json()["order_reference"]

    # Move SUBMITTED -> UNDER_REVIEW
    r1 = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW"},
        headers=tailor_headers,
    )
    assert r1.status_code == 200

    # Attempt UNDER_REVIEW -> AWAITING_CUSTOMER_CONFIRMATION without quotation_ref -> rejected!
    r2 = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "AWAITING_CUSTOMER_CONFIRMATION"},
        headers=tailor_headers,
    )
    assert r2.status_code == 422
    assert r2.json()["error_code"] == "MISSING_QUOTATION_REFERENCE"


def test_invalid_quantity_rejected(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    for bad_qty in (0, -3, 101):
        payload = build_valid_order_payload()
        payload["items"][0]["quantity"] = bad_qty
        resp = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
        assert resp.status_code == 422


def test_invalid_identifiers_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    for bad_id in ("../etc/passwd", "CUS 001; DROP TABLE orders;", "A"):
        payload = build_valid_order_payload(customer_ref=bad_id)
        resp = client.post("/api/v1/orders", json=payload, headers=admin_headers)
        assert resp.status_code == 422


def test_duplicate_submission_reference_rejected(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    payload = build_valid_order_payload(submission_reference="SUB-2026-0001")
    first = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert first.status_code == 201

    second = client.post("/api/v1/orders", json=payload, headers=customer1_headers)
    assert second.status_code == 409
    assert second.json()["error_code"] == "DUPLICATE_SUBMISSION"


def test_idempotent_retry_returns_same_order_without_duplicate(
    client: TestClient, customer1_headers: dict[str, str]
) -> None:
    headers = {**customer1_headers, "Idempotency-Key": "IDEM-KEY-0001"}
    payload = build_valid_order_payload(submission_reference="SUB-IDEM-001")

    first = client.post("/api/v1/orders", json=payload, headers=headers)
    assert first.status_code == 201
    first_data = first.json()
    assert first_data["idempotent_replay"] is False
    assert first_data["tracking_token"] is not None

    retry = client.post("/api/v1/orders", json=payload, headers=headers)
    assert retry.status_code == 200
    retry_data = retry.json()
    assert retry_data["idempotent_replay"] is True
    assert retry_data["order_reference"] == first_data["order_reference"]
    assert retry_data["id"] == first_data["id"]
    # Tracking token is only disclosed once at initial creation
    assert retry_data["tracking_token"] is None

    listing = client.get("/api/v1/orders", headers=customer1_headers).json()
    assert listing["total"] == 1
