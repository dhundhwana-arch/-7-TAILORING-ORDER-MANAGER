"""Category B: Controlled Lifecycle, Hold/Resume, Cancellation, Quality Rework, and Completion Tests."""

from fastapi.testclient import TestClient

from tests.conftest import build_valid_order_payload


def _advance_to_confirmed(
    client: TestClient,
    customer_headers: dict[str, str],
    tailor_headers: dict[str, str],
    *,
    quotation_ref: str = "QUO-001",
) -> str:
    resp = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(
            quotation_ref=quotation_ref, submit_immediately=False
        ),
        headers=customer_headers,
    )
    assert resp.status_code == 201
    order_ref = resp.json()["order_reference"]

    assert (
        client.post(
            f"/api/v1/orders/{order_ref}/submit", headers=customer_headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": "UNDER_REVIEW"},
            headers=tailor_headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": "AWAITING_CUSTOMER_CONFIRMATION"},
            headers=tailor_headers,
        ).status_code
        == 200
    )
    confirm = client.post(
        f"/api/v1/orders/{order_ref}/confirm",
        json={"accepted_quotation_ref": quotation_ref},
        headers=customer_headers,
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["current_status"] == "CONFIRMED"
    return order_ref


def test_full_end_to_end_order_lifecycle_to_completed(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    order_ref = _advance_to_confirmed(client, customer1_headers, tailor_headers)

    for next_stage in (
        "MATERIAL_PREPARATION",
        "CUTTING",
        "STITCHING",
        "FINISHING",
        "QUALITY_CHECK",
    ):
        r = client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": next_stage},
            headers=tailor_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["current_status"] == next_stage

    # Cannot jump to READY before passing QUALITY_CHECK inspection!
    premature_ready = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "READY"},
        headers=tailor_headers,
    )
    assert premature_ready.status_code == 422
    assert premature_ready.json()["error_code"] == "QUALITY_CHECK_NOT_PASSED"

    # Create and pass QUALITY_CHECK task
    qc_task = client.post(
        "/api/v1/workflow/tasks",
        json={
            "order_reference": order_ref,
            "stage": "QUALITY_CHECK",
            "task_name": "Final Garment Quality Inspection",
        },
        headers=tailor_headers,
    )
    assert qc_task.status_code == 201
    task_ref = qc_task.json()["task_ref"]

    qc_done = client.patch(
        f"/api/v1/workflow/tasks/{task_ref}",
        json={
            "inspection_result": "PASSED",
            "task_status": "COMPLETED",
            "notes": "Measurements and collar stitch verified against snapshot v1.",
        },
        headers=tailor_headers,
    )
    assert qc_done.status_code == 200

    # Now QUALITY_CHECK -> READY succeeds
    ready_resp = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "READY"},
        headers=tailor_headers,
    )
    assert ready_resp.status_code == 200
    assert ready_resp.json()["current_status"] == "READY"

    # Cannot mark COMPLETED directly from READY (must be DELIVERED first!)
    invalid_complete = client.post(
        f"/api/v1/orders/{order_ref}/complete",
        json={"completion_evidence": "Tried skipping delivery"},
        headers=admin_headers,
    )
    assert invalid_complete.status_code == 422

    # Record verified collection/delivery -> DELIVERED
    delivered = client.post(
        f"/api/v1/orders/{order_ref}/deliver",
        json={
            "delivery_method": "COLLECTION",
            "delivery_reference": "PICKUP-SLIP-2026-01",
            "delivery_recipient_ack": "Collected at Dhundhwana workshop counter",
        },
        headers=tailor_headers,
    )
    assert delivered.status_code == 200
    assert delivered.json()["current_status"] == "DELIVERED"

    # Tailor cannot close as COMPLETED (ADMIN/OWNER required)
    tailor_complete = client.post(
        f"/api/v1/orders/{order_ref}/complete",
        json={"completion_evidence": "Tailor attempted close"},
        headers=tailor_headers,
    )
    assert tailor_complete.status_code == 403

    # Admin formally completes with verified completion evidence
    completed = client.post(
        f"/api/v1/orders/{order_ref}/complete",
        json={"completion_evidence": "Customer receipt PICKUP-SLIP-2026-01 verified"},
        headers=admin_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["current_status"] == "COMPLETED"
    assert completed.json()["completed_at"] is not None


def test_invalid_and_unauthorized_status_transitions_rejected(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    resp = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    )
    order_ref = resp.json()["order_reference"]

    # Customer cannot move SUBMITTED -> UNDER_REVIEW
    unauth = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "UNDER_REVIEW"},
        headers=customer1_headers,
    )
    assert unauth.status_code == 403

    # Tailor cannot jump SUBMITTED -> STITCHING
    invalid = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "STITCHING"},
        headers=tailor_headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "INVALID_STATUS_TRANSITION"


def test_cancellation_permissions_before_and_after_confirmation(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    # 1. Customer can cancel pre-confirmation order
    pre = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    ).json()
    c1 = client.post(
        f"/api/v1/orders/{pre['order_reference']}/cancel",
        json={"reason": "Changed design preference before confirmation"},
        headers=customer1_headers,
    )
    assert c1.status_code == 200
    assert c1.json()["current_status"] == "CANCELLED"

    # 2. Once CONFIRMED, customer and tailor CANNOT cancel; ADMIN CAN cancel
    confirmed_ref = _advance_to_confirmed(client, customer1_headers, tailor_headers)
    cust_cancel = client.post(
        f"/api/v1/orders/{confirmed_ref}/cancel",
        json={"reason": "Want to cancel after confirmation"},
        headers=customer1_headers,
    )
    assert cust_cancel.status_code == 403

    tailor_cancel = client.post(
        f"/api/v1/orders/{confirmed_ref}/cancel",
        json={"reason": "Tailor cancel attempt"},
        headers=tailor_headers,
    )
    assert tailor_cancel.status_code == 403

    admin_cancel = client.post(
        f"/api/v1/orders/{confirmed_ref}/cancel",
        json={"reason": "Authorized mutual cancellation before cutting"},
        headers=admin_headers,
    )
    assert admin_cancel.status_code == 200
    assert admin_cancel.json()["current_status"] == "CANCELLED"


def test_hold_and_resume_behavior(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    order_ref = _advance_to_confirmed(client, customer1_headers, tailor_headers)
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "MATERIAL_PREPARATION"},
        headers=tailor_headers,
    )
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "CUTTING"},
        headers=tailor_headers,
    )

    # Hold without reason rejected
    no_reason = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "ON_HOLD"},
        headers=tailor_headers,
    )
    assert no_reason.status_code == 422
    assert no_reason.json()["error_code"] == "HOLD_REASON_REQUIRED"

    # Hold with reason stores previous_hold_status=CUTTING
    held = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "ON_HOLD",
            "reason": "Awaiting customer clarification on cuff button contrast",
        },
        headers=tailor_headers,
    )
    assert held.status_code == 200
    st = client.get(f"/api/v1/orders/{order_ref}/status", headers=tailor_headers).json()
    assert st["current_status"] == "ON_HOLD"
    assert st["previous_hold_status"] == "CUTTING"

    # Resuming to wrong stage (READY) rejected
    bad_resume = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "READY"},
        headers=tailor_headers,
    )
    assert bad_resume.status_code == 422
    assert bad_resume.json()["error_code"] == "INVALID_RESUME_TARGET"

    # Resuming to CUTTING succeeds
    resumed = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "CUTTING", "reason": "Clarification received"},
        headers=tailor_headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["current_status"] == "CUTTING"


def test_quality_inspection_failure_and_rework_loop(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    order_ref = _advance_to_confirmed(client, customer1_headers, tailor_headers)
    for stage in ("MATERIAL_PREPARATION", "CUTTING", "STITCHING", "FINISHING", "QUALITY_CHECK"):
        assert (
            client.post(
                f"/api/v1/orders/{order_ref}/transitions",
                json={"target_status": stage},
                headers=tailor_headers,
            ).status_code
            == 200
        )

    qc_task = client.post(
        "/api/v1/workflow/tasks",
        json={
            "order_reference": order_ref,
            "stage": "QUALITY_CHECK",
            "task_name": "Inspection #1",
        },
        headers=tailor_headers,
    ).json()

    # Fail inspection -> requires rework_requirements
    failed_qc = client.patch(
        f"/api/v1/workflow/tasks/{qc_task['task_ref']}",
        json={
            "inspection_result": "FAILED_REWORK_REQUIRED",
            "rework_requirements": "Left cuff seam tension uneven; re-stitch cuff",
            "task_status": "COMPLETED",
        },
        headers=tailor_headers,
    )
    assert failed_qc.status_code == 200

    # Cannot advance to READY when inspection failed!
    blocked_ready = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "READY"},
        headers=tailor_headers,
    )
    assert blocked_ready.status_code == 422
    assert blocked_ready.json()["error_code"] == "QUALITY_CHECK_NOT_PASSED"

    # Transition QUALITY_CHECK -> STITCHING as rework (creates rework task and increments rework_count)
    rework = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={
            "target_status": "STITCHING",
            "reason": "Re-stitch left cuff per QC #1",
        },
        headers=tailor_headers,
    )
    assert rework.status_code == 200
    assert rework.json()["current_status"] == "STITCHING"

    wf = client.get(f"/api/v1/orders/{order_ref}/workflow", headers=tailor_headers).json()
    assert wf["rework_count"] == 1
    rework_tasks = [t for t in wf["tasks"] if t["is_rework"]]
    assert len(rework_tasks) == 1
    assert rework_tasks[0]["stage"] == "STITCHING"
