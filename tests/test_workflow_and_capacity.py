"""Category I & Workflow: Tailoring Workflow Stages, Finishing Checklist, and Capacity Awareness."""

from fastapi.testclient import TestClient

from tests.conftest import build_valid_order_payload


def test_material_preparation_block_and_finishing_checklist_enforcement(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    # Advance order to MATERIAL_PREPARATION
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
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "MATERIAL_PREPARATION"},
        headers=tailor_headers,
    )

    # Record missing customer cloth -> blocks advancing to CUTTING!
    mat_task = client.post(
        "/api/v1/workflow/tasks",
        json={
            "order_reference": order_ref,
            "stage": "MATERIAL_PREPARATION",
            "task_name": "Verify customer fabric length",
            "material_ready": False,
            "missing_material_info": "Customer cloth not yet dropped off at workshop",
        },
        headers=tailor_headers,
    ).json()
    assert mat_task["task_status"] == "BLOCKED"
    assert mat_task["assigned_staff_ref"] is None  # Never auto-invented!

    premature_cut = client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "CUTTING"},
        headers=tailor_headers,
    )
    assert premature_cut.status_code == 422
    assert premature_cut.json()["error_code"] == "MATERIAL_NOT_READY"

    # Mark material ready and complete MATERIAL_PREPARATION task
    client.patch(
        f"/api/v1/workflow/tasks/{mat_task['task_ref']}",
        json={
            "material_ready": True,
            "missing_material_info": "",
            "task_status": "COMPLETED",
        },
        headers=tailor_headers,
    )
    assert (
        client.post(
            f"/api/v1/orders/{order_ref}/transitions",
            json={"target_status": "CUTTING"},
            headers=tailor_headers,
        ).status_code
        == 200
    )
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "STITCHING"},
        headers=tailor_headers,
    )
    client.post(
        f"/api/v1/orders/{order_ref}/transitions",
        json={"target_status": "FINISHING"},
        headers=tailor_headers,
    )

    # Create FINISHING task -> gets default checklist (buttons, cuffs, thread_checks, ironing)
    fin_task = client.post(
        "/api/v1/workflow/tasks",
        json={
            "order_reference": order_ref,
            "stage": "FINISHING",
            "task_name": "Standard Shirt Finishing",
        },
        headers=tailor_headers,
    ).json()
    assert set(fin_task["checklist"].keys()) == {
        "buttons",
        "cuffs",
        "thread_checks",
        "ironing",
    }

    # Attempting to complete FINISHING task before checking items off -> rejected!
    incomplete_fin = client.patch(
        f"/api/v1/workflow/tasks/{fin_task['task_ref']}",
        json={
            "checklist_updates": {"buttons": True, "cuffs": True},
            "task_status": "COMPLETED",
        },
        headers=tailor_headers,
    )
    assert incomplete_fin.status_code == 422
    assert incomplete_fin.json()["error_code"] == "FINISHING_CHECKLIST_INCOMPLETE"

    # Complete all finishing checks -> succeeds!
    done_fin = client.patch(
        f"/api/v1/workflow/tasks/{fin_task['task_ref']}",
        json={
            "checklist_updates": {
                "buttons": True,
                "cuffs": True,
                "thread_checks": True,
                "ironing": True,
            },
            "task_status": "COMPLETED",
        },
        headers=tailor_headers,
    )
    assert done_fin.status_code == 200
    assert done_fin.json()["task_status"] == "COMPLETED"


def test_capacity_missing_config_configured_settings_and_workload_warnings(
    client: TestClient,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    # 1. Missing capacity configuration initially surfaces explicit warning
    initial_cap = client.get("/api/v1/capacity", headers=tailor_headers).json()
    assert initial_cap["configured"] is False
    assert initial_cap["is_guaranteed_capacity"] is False
    assert initial_cap["delivery_date_policy"] == "NO_AUTOMATIC_DELIVERY_PROMISE"

    initial_wl = client.get("/api/v1/capacity/workload", headers=tailor_headers).json()
    assert any(
        w["code"] == "MISSING_CAPACITY_CONFIGURATION"
        for w in initial_wl["capacity_warnings"]
    )

    # 2. Invalid resource availability (> total) rejected
    bad_cap = client.patch(
        "/api/v1/capacity/settings",
        json={"sewing_machines_count": 3, "available_sewing_machines": 5},
        headers=admin_headers,
    )
    assert bad_cap.status_code == 422

    # 3. Configure realistic Dhundhwana workshop settings with tight warning thresholds to test warnings
    cfg = client.patch(
        "/api/v1/capacity/settings",
        json={
            "sewing_machines_count": 3,
            "available_sewing_machines": 1,
            "overlock_machines_count": 1,
            "available_overlock_machines": 1,
            "irons_count": 1,
            "available_irons": 0,
            "cutting_tables_count": 1,
            "available_cutting_tables": 1,
            "reference_sets_per_day": "2.00",
            "max_active_production_orders_warning": 1,
            "max_stage_orders_warning": 1,
            "max_urgent_orders_warning": 0,
            "operating_notes": "Two machines awaiting maintenance; iron temporarily offline.",
        },
        headers=admin_headers,
    )
    assert cfg.status_code == 200
    cfg_data = cfg.json()
    assert cfg_data["configured"] is True
    assert cfg_data["is_guaranteed_capacity"] is False

    # Create 2 urgent confirmed orders and move one to FINISHING (iron unavailable!) and one to STITCHING
    order_refs = []
    for idx in range(2):
        r = client.post(
            "/api/v1/orders",
            json=build_valid_order_payload(
                submission_reference=f"CAP-SUB-{idx}",
                is_urgent=True,
                submit_immediately=True,
            ),
            headers=admin_headers,
        )
        assert r.status_code == 201
        o_ref = r.json()["order_reference"]
        order_refs.append(o_ref)
        client.post(
            f"/api/v1/orders/{o_ref}/transitions",
            json={"target_status": "UNDER_REVIEW"},
            headers=tailor_headers,
        )
        client.post(
            f"/api/v1/orders/{o_ref}/transitions",
            json={"target_status": "AWAITING_CUSTOMER_CONFIRMATION"},
            headers=tailor_headers,
        )
        client.post(
            f"/api/v1/orders/{o_ref}/confirm",
            json={"accepted_quotation_ref": "QUO-001"},
            headers=customer1_headers,
        )

    # Advance order 0 -> FINISHING, order 1 -> STITCHING
    for st in ("MATERIAL_PREPARATION", "CUTTING", "STITCHING", "FINISHING"):
        client.post(
            f"/api/v1/orders/{order_refs[0]}/transitions",
            json={"target_status": st},
            headers=tailor_headers,
        )
    for st in ("MATERIAL_PREPARATION", "CUTTING", "STITCHING"):
        client.post(
            f"/api/v1/orders/{order_refs[1]}/transitions",
            json={"target_status": st},
            headers=tailor_headers,
        )

    wl = client.get("/api/v1/capacity/workload", headers=admin_headers).json()
    assert wl["capacity_exceeded"] is True
    assert wl["delivery_date_policy"] == "NO_AUTOMATIC_DELIVERY_PROMISE"
    assert wl["estimated_workload"]["active_production_orders"] == 2
    assert wl["estimated_workload"]["orders_in_finishing"] == 1
    assert wl["estimated_workload"]["orders_in_stitching"] == 1
    assert wl["estimated_workload"]["urgent_orders"] == 2

    warn_codes = {w["code"] for w in wl["capacity_warnings"]}
    conflict_codes = {c["code"] for c in wl["scheduling_conflicts"]}
    assert "ACTIVE_PRODUCTION_THRESHOLD_EXCEEDED" in warn_codes
    assert "URGENT_WORKLOAD_HIGH" in warn_codes
    assert "IRON_UNAVAILABLE" in conflict_codes
