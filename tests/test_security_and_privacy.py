"""Category H: Security, Authentication, RBAC, Customer Isolation, Tracking Privacy, and Rate Limiting."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.core.enums import ActorRole
from app.core.security import create_signed_bearer_token
from app.main import create_app
from tests.conftest import build_valid_order_payload


def test_customer_isolation_and_internal_note_privacy(
    client: TestClient,
    customer1_headers: dict[str, str],
    customer2_headers: dict[str, str],
    tailor_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(submit_immediately=True),
        headers=customer1_headers,
    ).json()
    order_ref = created["order_reference"]
    tracking_token = created["tracking_token"]

    # Add INTERNAL note and CUSTOMER_VISIBLE note
    n_internal = client.post(
        f"/api/v1/orders/{order_ref}/notes",
        json={
            "visibility": "INTERNAL",
            "content": "CONFIDENTIAL WORKSHOP NOTE: Check sewing machine #2 tension.",
        },
        headers=tailor_headers,
    )
    assert n_internal.status_code == 201

    n_public = client.post(
        f"/api/v1/orders/{order_ref}/notes",
        json={
            "visibility": "CUSTOMER_VISIBLE",
            "content": "Your fabric parcel has been received at the workshop.",
        },
        headers=tailor_headers,
    )
    assert n_public.status_code == 201

    # Customer 1 sees their own order + CUSTOMER_VISIBLE note, NEVER INTERNAL note!
    own_view = client.get(
        f"/api/v1/orders/{order_ref}", headers=customer1_headers
    ).json()
    note_contents = [n["content"] for n in own_view["notes"]]
    assert "Your fabric parcel has been received at the workshop." in note_contents
    assert not any("CONFIDENTIAL" in c for c in note_contents)
    assert all(n["visibility"] == "CUSTOMER_VISIBLE" for n in own_view["notes"])

    # Customer 2 CANNOT view, transition, or track Customer 1's order!
    other_get = client.get(f"/api/v1/orders/{order_ref}", headers=customer2_headers)
    assert other_get.status_code == 403

    other_track = client.get(
        f"/api/v1/tracking/{order_ref}", headers=customer2_headers
    )
    assert other_track.status_code == 403

    # Public tracking WITHOUT credentials or tracking_token is rejected (order ID alone NEVER suffices!)
    bare_track = client.get(f"/api/v1/tracking/{order_ref}")
    assert bare_track.status_code == 401

    # Public tracking WITH forged tracking_token is rejected
    forged_track = client.get(
        f"/api/v1/tracking/{order_ref}",
        headers={"X-Tracking-Token": "trk_forged_invalid_token_value"},
    )
    assert forged_track.status_code == 403

    # Public tracking WITH valid tracking_token succeeds and exposes zero internal notes or measurements
    valid_track = client.get(
        f"/api/v1/tracking/{order_ref}",
        headers={"X-Tracking-Token": tracking_token},
    )
    assert valid_track.status_code == 200
    t_body = valid_track.json()
    assert t_body["order_reference"] == order_ref
    assert "CONFIDENTIAL" not in str(t_body)
    assert "chest" not in str(t_body)
    assert len(t_body["customer_updates"]) == 1

    # Admin view DOES include internal notes
    admin_detail = client.get(
        f"/api/v1/admin/orders/{order_ref}", headers=admin_headers
    ).json()
    assert len(admin_detail["order"]["notes"]) == 2


def test_authentication_failures_and_admin_rbac_enforcement(
    client: TestClient,
    test_settings: Settings,
    customer1_headers: dict[str, str],
    tailor_headers: dict[str, str],
) -> None:
    # Unauthenticated request rejected with 401
    assert client.get("/api/v1/orders").status_code == 401

    # Expired token rejected with 401
    expired_token = create_signed_bearer_token(
        actor_id="CUS-001",
        role=ActorRole.CUSTOMER,
        secret_key=test_settings.AUTH_SECRET_KEY,
        ttl_seconds=-10,
    )
    r_exp = client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert r_exp.status_code == 401

    # Tampered signature rejected with 401
    tampered = expired_token[:-4] + "AAAA"
    assert (
        client.get(
            "/api/v1/orders", headers={"Authorization": f"Bearer {tampered}"}
        ).status_code
        == 401
    )

    # Customer and Tailor rejected from /api/v1/admin/* and /api/v1/capacity/settings
    for hdrs in (customer1_headers, tailor_headers):
        assert client.get("/api/v1/admin/orders", headers=hdrs).status_code == 403
        assert client.get("/api/v1/admin/audit", headers=hdrs).status_code == 403
        assert (
            client.patch(
                "/api/v1/capacity/settings",
                json={"sewing_machines_count": 4},
                headers=hdrs,
            ).status_code
            == 403
        )

    # Customer cannot self-authorize urgent priority
    urgent_attempt = client.post(
        "/api/v1/orders",
        json=build_valid_order_payload(is_urgent=True),
        headers=customer1_headers,
    )
    assert urgent_attempt.status_code == 403


def test_production_settings_reject_weak_secrets_and_dev_headers() -> None:
    with pytest.raises(ValueError, match="AUTH_DEV_HEADER_ENABLED"):
        Settings(
            APP_ENV="production",
            AUTH_DEV_HEADER_ENABLED=True,
            AUTH_SECRET_KEY="x" * 40,
            TRACKING_TOKEN_SECRET="y" * 40,
        )

    with pytest.raises(ValueError, match="AUTH_SECRET_KEY"):
        Settings(
            APP_ENV="production",
            AUTH_DEV_HEADER_ENABLED=False,
            AUTH_SECRET_KEY="changeme",
            TRACKING_TOKEN_SECRET="y" * 40,
        )


def test_rate_limiting_enforced_on_tracking_endpoint(tmp_path: Path) -> None:
    strict_settings = Settings(
        APP_ENV="testing",
        DATABASE_URL=f"sqlite:///{tmp_path / 'rl.db'}",
        RATE_LIMIT_ENABLED=True,
        TRACKING_RATE_LIMIT_PER_MINUTE=3,
    )
    rl_app = create_app(settings=strict_settings)
    with TestClient(rl_app) as tc:
        for _ in range(3):
            res = tc.get("/api/v1/tracking/ORD-NONEXISTENT")
            assert res.status_code == 401
        fourth = tc.get("/api/v1/tracking/ORD-NONEXISTENT")
        assert fourth.status_code == 429
        assert fourth.json()["error_code"] == "RATE_LIMIT_EXCEEDED"
