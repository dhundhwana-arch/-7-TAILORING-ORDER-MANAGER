"""Additional endpoint tests: Admin search/filter, Stage Corrections, History/Snapshots privacy, and Task listings."""

from fastapi.testclient import TestClient

from tests.conftest import build_valid_order_payload


def test_history_and_snapshots_customer_privacy_vs_staff_access(
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

    # Add an internal note (creates customer_visible=False event)
    client.post(
        f"/api/v1/orders/{order_ref}/notes",
        json={"visibility": "INTERNAL", "content": "Private tailor memo"},
        headers=tailor_headers,
    )

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

    # Customer history omits non-customer-visible events and strips internal actor_id
    cust_hist = client.get(
        f"/api/v1/orders/{order_ref}/history", headers=customer1_headers
    ).json()
    assert all(ev["customer_visible"] is True for ev in cust_hist)
    assert all(ev["actor_id"] is None for ev in cust_hist)

    # Staff history includes INTERNAL_NOTE_ADDED event + actor_id
    staff_hist = client.get(
        f"/api/v1/orders/{order_ref}/history", headers=tailor_headers
    ).json()
    assert len(staff_hist) > len(cust_hist)
    assert any(ev["event_type"] == "INTERNAL_NOTE_ADDED" for ev in staff_hist)

    # Customer snapshot endpoint redacts raw body measurements while preserving profile_version
    cust_snaps = client.get(
        f"/api/v1/orders/{order_ref}/snapshots", headers=customer1_headers
    ).json()
    assert len(cust_snaps) == 1
    assert cust_snaps[0]["measurement_snapshot"]["profile_version"] == 1
    assert "measurements" not in cust_snaps[0]["measurement_snapshot"]

    # Tailor/Admin snapshot endpoint provides full measurement snapshot for cutting/stitching
    staff_snaps = client.get(
        f"/api/v1/orders/{order_ref}/snapshots", headers=tailor_headers
    ).json()
    assert staff_snaps[0]["measurement_snapshot"]["measurements"]["chest"] == 100.0

    # Admin search & status filter
    search_res = client.get(
        f"/api/v1/admin/orders?search={order_ref}&status=CONFIRMED",
        headers=admin_headers,
    ).json()
    assert search_res["total"] == 1
    assert search_res["items"][0]["order_reference"] == order_ref


def test_exceptional_admin_stage_correction_and_workflow_task_listing(
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

    for st in ("UNDER_REVIEW", "AWAITING_CUSTOMER_CONFIRMATION"):
        client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": st},
            headers=tailor_headers,
        )
    client.post(
        f"/api/v1/orders/{order_ref}/confirm",
        json={"accepted_quotation_ref": "QUO-001"},
        headers=customer1_headers,
    )
    for st in ("MATERIAL_PREPARATION", "CUTTING", "STITCHING"):
        client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": st},
            headers=tailor_headers,
        )

    # Tailor cannot execute an administrative stage correction
    t_corr = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "CUTTING",
            "is_admin_correction": True,
            "reason": "Accidentally clicked stitching early",
        },
        headers=tailor_headers,
    )
    assert t_corr.status_code == 403

    # Admin cannot jump arbitrarily (e.g., STITCHING -> COMPLETED) via admin correction
    bad_jump = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "COMPLETED",
            "is_admin_correction": True,
            "reason": "Arbitrary jump attempt",
        },
        headers=admin_headers,
    )
    assert bad_jump.status_code == 422
    assert bad_jump.json()["error_code"] == "INVALID_ADMIN_CORRECTION"

    # Admin CAN perform single-step correction STITCHING -> CUTTING with explicit audit reason
    valid_corr = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "CUTTING",
            "is_admin_correction": True,
            "reason": "Operator marked CUTTING done on wrong ticket; reverting to CUTTING",
        },
        headers=admin_headers,
    )
    assert valid_corr.status_code == 200
    assert valid_corr.json()["current_status"] == "CUTTING"

    # Create and list workflow tasks using dev headers (non-production)
    dev_headers = {"X-Actor-Id": "STF-TAILOR-02", "X-Actor-Role": "TAILOR"}
    t_create = client.post(
        "/api/v1/workflow/tasks",
        json={
            "order_reference": order_ref,
            "stage": "CUTTING",
            "task_name": "Cut shirt panels",
            "assigned_staff_ref": "STF-TAILOR-02",
        },
        headers=dev_headers,
    )
    assert t_create.status_code == 201

    task_list = client.get(
        f"/api/v1/workflow/tasks?order_reference={order_ref}&stage=CUTTING&task_status=PENDING",
        headers=dev_headers,
    )
    assert task_list.status_code == 200
    assert task_list.json()["total"] == 1
