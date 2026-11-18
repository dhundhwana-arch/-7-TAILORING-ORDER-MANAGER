"""Identifier generation and strict reference validation utilities."""

from datetime import datetime, timezone
import re
import secrets

from app.core.exceptions import ValidationError

# Accepts clean alphanumeric identifiers with hyphens/underscores (e.g., CUS-001, DSG-A1B2C3D4)
SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,63}$")


def validate_reference_id(value: str | None, *, field_name: str, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ValidationError(f"{field_name} is required.")
        return None
    cleaned = value.strip()
    if not cleaned:
        if required:
            raise ValidationError(f"{field_name} cannot be blank.")
        return None
    if not SAFE_REF_PATTERN.match(cleaned):
        raise ValidationError(
            f"Invalid {field_name} '{cleaned}'. Must be 2–64 alphanumeric/hyphen/underscore characters.",
            details={"field": field_name},
        )
    return cleaned


def generate_public_ref(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    token = secrets.token_hex(4).upper()
    return f"{prefix}-{stamp}-{token}"
