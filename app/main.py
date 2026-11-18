"""FastAPI application factory for CUSTOM SHIRT STUDIO — Module 07 (Tailoring Order Manager)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.registry import AdapterRegistry, build_adapter_registry
from app.api.v1 import admin, capacity, lifecycle, orders, tracking, workflow
from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.core.logging import configure_logging, logger
from app.core.security import HmacBearerAuthAdapter, SlidingWindowRateLimiter
from app.db.session import build_engine, build_session_factory, init_db


def create_app(
    *,
    settings: Settings | None = None,
    adapters: AdapterRegistry | None = None,
) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging(active_settings.LOG_LEVEL)

    engine = build_engine(active_settings.DATABASE_URL)
    session_factory = build_session_factory(engine)
    active_adapters = adapters or build_adapter_registry(active_settings)
    auth_adapter = HmacBearerAuthAdapter(active_settings)
    rate_limiter = SlidingWindowRateLimiter()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        init_db(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title=active_settings.APP_NAME,
        version=active_settings.APP_VERSION,
        description=(
            "CUSTOM SHIRT STUDIO — Module 07/08: Tailoring Order Manager. "
            "Owns order lifecycle, immutable confirmation snapshots, tailoring "
            "production workflow, audit records, capacity awareness, and customer tracking."
        ),
        lifespan=lifespan,
    )

    app.state.settings = active_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.adapters = active_adapters
    app.state.auth_adapter = auth_adapter
    app.state.rate_limiter = rate_limiter

    # Allow preview & cross-module origins safely
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: Any) -> Any:
        cfg: Settings = request.app.state.settings
        if cfg.RATE_LIMIT_ENABLED and request.url.path.startswith("/api/"):
            client_ip = (
                request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or (request.client.host if request.client else "unknown")
            )
            try:
                if request.url.path.startswith("/api/v1/tracking"):
                    request.app.state.rate_limiter.check(
                        f"tracking:{client_ip}",
                        limit=cfg.TRACKING_RATE_LIMIT_PER_MINUTE,
                    )
                else:
                    request.app.state.rate_limiter.check(
                        f"api:{client_ip}",
                        limit=cfg.RATE_LIMIT_REQUESTS_PER_MINUTE,
                    )
            except DomainError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error_code": exc.error_code,
                        "message": exc.message,
                        "details": exc.details,
                    },
                )
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        sanitized_errors = [
            {
                "loc": list(err.get("loc", ())),
                "msg": err.get("msg", "Invalid input"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=getattr(
                status, "HTTP_422_UNPROCESSABLE_CONTENT", 422
            ),
            content={
                "error_code": "REQUEST_VALIDATION_ERROR",
                "message": "Request payload failed schema validation.",
                "details": {"errors": sanitized_errors},
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(
        _request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.error("Database operation failed: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "DATABASE_ERROR",
                "message": "A database error occurred while processing the request.",
                "details": {},
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("Unhandled error: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal error occurred.",
                "details": {},
            },
        )

    @app.get("/health", tags=["System"])
    def health_check() -> dict[str, str]:
        return {
            "status": "ok",
            "module": "07-tailoring-order-manager",
            "version": active_settings.APP_VERSION,
            "environment": active_settings.APP_ENV,
            "integration_mode": active_settings.INTEGRATION_MODE,
        }

    api_prefix = "/api/v1"
    app.include_router(orders.router, prefix=api_prefix)
    app.include_router(lifecycle.router, prefix=api_prefix)
    app.include_router(workflow.router, prefix=api_prefix)
    app.include_router(tracking.router, prefix=api_prefix)
    app.include_router(capacity.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)

    return app


app = create_app()
