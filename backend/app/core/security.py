from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

BCRYPT_ROUNDS = 12
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 72


def get_password_hash(password: str) -> str:
    validate_password(password)
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def verify_password_or_legacy(plain_password: str, stored_password: str) -> tuple[bool, bool]:
    """Verify bcrypt passwords and safely support legacy plaintext records once.

    The legacy branch exists only so accounts created before password hashing was
    enabled can still sign in and be upgraded by the auth service.
    """
    if stored_password.startswith(("$2a$", "$2b$", "$2y$")):
        return verify_password(plain_password, stored_password), False
    return hmac.compare_digest(plain_password, stored_password), True


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not password.strip():
        raise ValueError("Password cannot be blank.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("Password must be at least 8 characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        raise ValueError("Password must be at most 72 bytes.")


def needs_password_rehash(hashed_password: str) -> bool:
    parts = hashed_password.split("$")
    if len(parts) < 4:
        return True
    cost_str = parts[2]
    if not cost_str.isdigit():
        return True
    cost = int(cost_str)
    return cost < BCRYPT_ROUNDS


def create_access_token(
    subject: str,
    expires_minutes: int | None = None,
    auth_version: int = 0,
    demo: bool = False,
) -> str:
    expires_in = expires_minutes or settings.access_token_expire_minutes
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in)
    payload: dict[str, Any] = {"sub": subject, "exp": expire_at, "auth_version": auth_version}
    if demo:
        payload["demo"] = True
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_numeric_code(length: int) -> str:
    if length < 1:
        raise ValueError("Code length must be positive.")
    return f"{secrets.randbelow(10 ** length):0{length}d}"


def hash_password_reset_code(challenge_id: str, email: str, code: str) -> str:
    message = f"password-reset-code:{challenge_id}:{email}:{code}".encode("utf-8")
    return hmac.new(
        settings.password_reset_code_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def hash_password_reset_authorization(token: str) -> str:
    message = f"password-reset-authorization:{token}".encode("utf-8")
    return hmac.new(
        settings.password_reset_code_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def hash_security_identifier(value: str) -> str:
    message = f"security-identifier:{value}".encode("utf-8")
    return hmac.new(
        settings.password_reset_code_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
