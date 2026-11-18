"""Authentication adapter, RBAC principal resolution, tracking tokens, and rate limiting.

Because Module 01 (Customer Platform) and Module 08 (Admin Dashboard) do not yet
have finalized authentication contracts on `main`, Module 07 implements a
documented, replaceable `AuthAdapter` supporting HMAC-SHA256 Bearer tokens and
strictly gated local/test headers (`AUTH_DEV_HEADER_ENABLED`).
"""

import base64
from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Protocol

from fastapi import Request

from app.core.config import Settings
from app.core.enums import ActorRole
from app.core.exceptions import (
    ForbiddenError,
    RateLimitExceededError,
    UnauthorizedError,
)


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity and RBAC role."""

    actor_id: str
    role: ActorRole

    @property
    def is_staff(self) -> bool:
        return self.role in {ActorRole.TAILOR, ActorRole.ADMIN, ActorRole.OWNER}

    @property
    def is_admin(self) -> bool:
        return self.role in {ActorRole.ADMIN, ActorRole.OWNER}


class AuthAdapter(Protocol):
    """Replaceable authentication adapter contract."""

    def authenticate_request(self, request: Request) -> Principal:
        ...

    def authenticate_optional(self, request: Request) -> Principal | None:
        ...


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def create_signed_bearer_token(
    *,
    actor_id: str,
    role: ActorRole,
    secret_key: str,
    ttl_seconds: int = 3600,
    now_epoch: int | None = None,
) -> str:
    """Create a compact HMAC-SHA256 signed bearer token (`v1.<payload>.<sig>`)."""
    issued_at = int(time.time()) if now_epoch is None else now_epoch
    payload = {
        "sub": actor_id.strip(),
        "role": role.value,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    if not payload["sub"]:
        raise ValueError("actor_id cannot be empty.")
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"v1.{payload_b64}".encode("ascii")
    sig = hmac.new(
        secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return f"v1.{payload_b64}.{_b64url_encode(sig)}"


def verify_signed_bearer_token(token: str, *, secret_key: str) -> Principal:
    """Verify an HMAC-SHA256 bearer token and return the authenticated Principal."""
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise UnauthorizedError("Malformed authentication token.")
    _, payload_b64, sig_b64 = parts
    signing_input = f"v1.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(
        secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    try:
        provided_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise UnauthorizedError("Invalid token signature encoding.") from exc

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise UnauthorizedError("Invalid authentication token signature.")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise UnauthorizedError("Invalid authentication token payload.") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise UnauthorizedError("Authentication token has expired.")

    sub = str(payload.get("sub", "")).strip()
    role_raw = str(payload.get("role", "")).strip().upper()
    if not sub:
        raise UnauthorizedError("Authentication token missing subject.")
    try:
        role = ActorRole(role_raw)
    except ValueError as exc:
        raise UnauthorizedError(f"Unsupported actor role '{role_raw}'.") from exc

    return Principal(actor_id=sub, role=role)


class HmacBearerAuthAdapter:
    """Default authentication adapter supporting Bearer tokens and gated dev headers."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate_optional(self, request: Request) -> Principal | None:
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header:
            if not auth_header.lower().startswith("bearer "):
                raise UnauthorizedError("Authorization header must use Bearer scheme.")
            raw_token = auth_header[7:].strip()
            if not raw_token:
                raise UnauthorizedError("Empty Bearer token.")
            return verify_signed_bearer_token(
                raw_token, secret_key=self._settings.AUTH_SECRET_KEY
            )

        if (
            self._settings.AUTH_DEV_HEADER_ENABLED
            and self._settings.APP_ENV != "production"
        ):
            dev_actor = request.headers.get("X-Actor-Id", "").strip()
            dev_role = request.headers.get("X-Actor-Role", "").strip().upper()
            if dev_actor or dev_role:
                if not dev_actor or not dev_role:
                    raise UnauthorizedError(
                        "Both X-Actor-Id and X-Actor-Role headers are required when using development headers."
                    )
                try:
                    role = ActorRole(dev_role)
                except ValueError as exc:
                    raise UnauthorizedError(
                        f"Unsupported X-Actor-Role '{dev_role}'."
                    ) from exc
                return Principal(actor_id=dev_actor, role=role)

        return None

    def authenticate_request(self, request: Request) -> Principal:
        principal = self.authenticate_optional(request)
        if principal is None:
            raise UnauthorizedError("Authentication credentials were not provided.")
        return principal


def ensure_roles(principal: Principal, allowed_roles: set[ActorRole]) -> Principal:
    if principal.role not in allowed_roles:
        raise ForbiddenError(
            f"Role '{principal.role.value}' is not authorized for this operation.",
            details={
                "actor_role": principal.role.value,
                "allowed_roles": sorted(r.value for r in allowed_roles),
            },
        )
    return principal


def generate_tracking_token() -> str:
    """Generate a high-entropy URL-safe customer tracking token."""
    return f"trk_{secrets.token_urlsafe(24)}"


def hash_tracking_token(
    tracking_token: str, *, order_ref: str, secret_key: str
) -> str:
    """Compute keyed HMAC-SHA256 digest of a tracking token bound to an order reference."""
    msg = f"{order_ref}:{tracking_token.strip()}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_tracking_token(
    tracking_token: str,
    *,
    order_ref: str,
    expected_hash: str,
    secret_key: str,
) -> bool:
    computed = hash_tracking_token(
        tracking_token, order_ref=order_ref, secret_key=secret_key
    )
    return hmac.compare_digest(computed, expected_hash)


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter keyed by client + bucket."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, limit: int, window_seconds: float = 60.0) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                raise RateLimitExceededError(
                    "Too many requests. Please slow down and retry shortly.",
                    details={"limit_per_minute": limit},
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
