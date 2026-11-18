"""Structured domain exceptions mapped to safe HTTP error responses."""

from typing import Any


class DomainError(Exception):
    """Base class for expected business and security errors."""

    status_code: int = 400
    error_code: str = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        self.details = details or {}


class ValidationError(DomainError):
    status_code = 422
    error_code = "VALIDATION_ERROR"


class NotFoundError(DomainError):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(DomainError):
    status_code = 409
    error_code = "CONFLICT"


class ConcurrencyConflictError(ConflictError):
    status_code = 409
    error_code = "CONCURRENCY_CONFLICT"


class ImmutableRecordError(ConflictError):
    status_code = 409
    error_code = "IMMUTABLE_RECORD"


class UnauthorizedError(DomainError):
    status_code = 401
    error_code = "UNAUTHORIZED"


class ForbiddenError(DomainError):
    status_code = 403
    error_code = "FORBIDDEN"


class IntegrationError(DomainError):
    status_code = 502
    error_code = "UPSTREAM_INTEGRATION_ERROR"


class RateLimitExceededError(DomainError):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
