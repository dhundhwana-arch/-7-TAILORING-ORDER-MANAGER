"""Shared Pytest fixtures for Module 07 (Tailoring Order Manager) test suite.

All test fixtures use synthetic illustrative identifiers ONLY (`CUS-001`, `DSG-001`,
`FAB-001`, `MEA-001`, `QUO-001`) — zero personal customer information.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.adapters.mock_adapters import (
    MockDesignConfigAdapter,
    MockFabricCatalogAdapter,
    MockMeasurementAdapter,
    MockNotificationProvider,
    MockPreviewReferenceAdapter,
    MockPricingAdapter,
)
from app.adapters.registry import AdapterRegistry
from app.core.config import Settings
from app.core.enums import ActorRole
from app.core.security import create_signed_bearer_token
from app.main import create_app


@pytest.fixture()
def mock_adapters() -> AdapterRegistry:
    return AdapterRegistry(
        pricing=MockPricingAdapter(),
        measurement=MockMeasurementAdapter(),
        fabric=MockFabricCatalogAdapter(),
        design=MockDesignConfigAdapter(),
        preview=MockPreviewReferenceAdapter(),
        notification=MockNotificationProvider(),
    )


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "test_module07.sqlite3"
    return Settings(
        APP_ENV="testing",
        DATABASE_URL=f"sqlite:///{db_path}",
        AUTH_SECRET_KEY="test-only-hmac-secret-key-for-automated-suite-2026",
        TRACKING_TOKEN_SECRET="test-only-tracking-secret-key-for-automated-suite-2026",
        AUTH_DEV_HEADER_ENABLED=True,
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_REQUESTS_PER_MINUTE=500,
        TRACKING_RATE_LIMIT_PER_MINUTE=200,
        INTEGRATION_MODE="mock",
        NOTIFICATION_PROVIDER="mock",
    )


@pytest.fixture()
def app(test_settings: Settings, mock_adapters: AdapterRegistry):
    return create_app(settings=test_settings, adapters=mock_adapters)


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app) as tc:
        yield tc


def make_auth_headers(
    settings: Settings, actor_id: str, role: ActorRole, *, ttl_seconds: int = 3600
) -> dict[str, str]:
    token = create_signed_bearer_token(
        actor_id=actor_id,
        role=role,
        secret_key=settings.AUTH_SECRET_KEY,
        ttl_seconds=ttl_seconds,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def customer1_headers(test_settings: Settings) -> dict[str, str]:
    return make_auth_headers(test_settings, "CUS-001", ActorRole.CUSTOMER)


@pytest.fixture()
def customer2_headers(test_settings: Settings) -> dict[str, str]:
    return make_auth_headers(test_settings, "CUS-002", ActorRole.CUSTOMER)


@pytest.fixture()
def tailor_headers(test_settings: Settings) -> dict[str, str]:
    return make_auth_headers(test_settings, "STF-TAILOR-01", ActorRole.TAILOR)


@pytest.fixture()
def admin_headers(test_settings: Settings) -> dict[str, str]:
    return make_auth_headers(test_settings, "STF-ADMIN-01", ActorRole.ADMIN)


@pytest.fixture()
def owner_headers(test_settings: Settings) -> dict[str, str]:
    return make_auth_headers(test_settings, "STF-OWNER-01", ActorRole.OWNER)


def build_valid_order_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "customer_ref": "CUS-001",
        "measurement_ref": "MEA-001",
        "quotation_ref": "QUO-001",
        "currency": "INR",
        "order_source": "MODULE_01_PLATFORM",
        "customer_instructions": "Keep collar crisp, regular comfort fit.",
        "submit_immediately": False,
        "items": [
            {
                "garment_type": "shirt",
                "quantity": 1,
                "design_ref": "DSG-001",
                "fabric_source": "CUSTOMER_SUPPLIED",
                "fabric_ref": "CUST-CLOTH-001",
                "preview_3d_ref": "PRV-001",
                "customization_data": {"monogram": False},
            }
        ],
    }
    base.update(overrides)
    return base
