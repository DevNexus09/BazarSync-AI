from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
import logging
import secrets
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    generate_numeric_code,
    get_password_hash,
    hash_password_reset_authorization,
    hash_password_reset_code,
    hash_security_identifier,
    validate_password,
)
from app.models.password_reset import (
    PasswordResetAuthorization,
    PasswordResetChallenge,
    PasswordResetChallengeStatus,
)
from app.models.security_audit_event import SecurityAuditEvent
from app.models.seller import Seller
from app.services.password_reset_email_service import (
    PasswordResetEmailDeliveryError,
    PasswordResetEmailService,
)
from app.services.password_reset_rate_limiter import (
    PasswordResetRateLimitExceeded,
    PasswordResetRateLimiter,
    password_reset_rate_limiter,
)


logger = logging.getLogger(__name__)
ACTIVE_CHALLENGE_STATUSES = (
    PasswordResetChallengeStatus.PENDING,
    PasswordResetChallengeStatus.VERIFIED,
)


class PasswordResetError(Exception):
    pass


class PasswordResetInvalidCodeError(PasswordResetError):
    pass


class PasswordResetSessionExpiredError(PasswordResetError):
    pass


class PasswordResetValidationError(PasswordResetError):
    pass


class PasswordResetService:
    def __init__(
        self,
        db: Session,
        *,
        email_service: PasswordResetEmailService | None = None,
        rate_limiter: PasswordResetRateLimiter | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._email_service = email_service or PasswordResetEmailService()
        self._rate_limiter = rate_limiter or password_reset_rate_limiter
        self._logger = logger_ or logger

    def request_code(
        self,
        *,
        email: str,
        request_ip: str,
        user_agent: str,
    ) -> None:
        self._ensure_enabled()
        normalized_email = _normalize_email(email)
        self._rate_limiter.check(normalized_email, request_ip)
        now = _utc_now()
        email_hash = hash_security_identifier(normalized_email)
        ip_hash = hash_security_identifier(request_ip or "unknown")
        user_agent_hash = hash_security_identifier(user_agent or "unknown")

        seller = self._db.execute(
            select(Seller)
            .where(func.lower(Seller.email) == normalized_email)
            .with_for_update()
        ).scalar_one_or_none()

        if seller is None:
            self._record_audit(
                event_type="PASSWORD_RESET_REQUESTED",
                seller_id=None,
                email_hash=email_hash,
                request_ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            self._db.commit()
            return

        latest = self._db.execute(
            select(PasswordResetChallenge)
            .where(
                PasswordResetChallenge.seller_id == seller.id,
                PasswordResetChallenge.status.in_(ACTIVE_CHALLENGE_STATUSES),
            )
            .order_by(desc(PasswordResetChallenge.created_at))
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            latest
            and _age_seconds(latest.created_at, now)
            < settings.password_reset_resend_cooldown_seconds
        ):
            self._record_audit(
                event_type="PASSWORD_RESET_REQUESTED",
                seller_id=seller.id,
                email_hash=email_hash,
                request_ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            self._db.commit()
            return

        self._invalidate_seller_reset_state(seller.id, now)
        challenge = PasswordResetChallenge(
            seller_id=seller.id,
            email_normalized=normalized_email,
            code_hash="pending",
            status=PasswordResetChallengeStatus.PENDING,
            attempt_count=0,
            max_attempts=settings.password_reset_max_attempts,
            expires_at=now
            + timedelta(minutes=settings.password_reset_code_ttl_minutes),
            request_ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            created_at=now,
            updated_at=now,
        )
        self._db.add(challenge)
        self._db.flush()
        code = generate_numeric_code(settings.password_reset_code_length)
        challenge.code_hash = hash_password_reset_code(
            str(challenge.id), normalized_email, code
        )
        self._record_audit(
            event_type="PASSWORD_RESET_REQUESTED",
            seller_id=seller.id,
            email_hash=email_hash,
            request_ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        self._db.commit()

        try:
            self._email_service.send_code(
                email=normalized_email,
                code=code,
                expires_minutes=settings.password_reset_code_ttl_minutes,
            )
        except PasswordResetEmailDeliveryError:
            challenge.status = PasswordResetChallengeStatus.CANCELLED
            challenge.updated_at = _utc_now()
            self._record_audit(
                event_type="PASSWORD_RESET_EMAIL_DELIVERY_FAILED",
                seller_id=seller.id,
                email_hash=email_hash,
                request_ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            self._db.commit()
            self._logger.warning(
                "password_reset_email_delivery_failed seller_id=%s code=EMAIL_DELIVERY_FAILED",
                seller.id,
            )

    def verify_code(
        self,
        *,
        email: str,
        code: str,
        request_ip: str,
        user_agent: str,
    ) -> tuple[str, datetime]:
        self._ensure_enabled()
        normalized_email = _normalize_email(email)
        now = _utc_now()
        challenge = self._db.execute(
            select(PasswordResetChallenge)
            .where(
                PasswordResetChallenge.email_normalized == normalized_email,
                PasswordResetChallenge.status == PasswordResetChallengeStatus.PENDING,
            )
            .order_by(desc(PasswordResetChallenge.created_at))
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if challenge is None:
            raise PasswordResetInvalidCodeError

        if _as_utc(challenge.expires_at) <= now:
            challenge.status = PasswordResetChallengeStatus.EXPIRED
            challenge.updated_at = now
            self._record_audit(
                event_type="PASSWORD_RESET_CODE_FAILED",
                seller_id=challenge.seller_id,
                email_hash=hash_security_identifier(normalized_email),
                request_ip_hash=hash_security_identifier(request_ip or "unknown"),
                user_agent_hash=hash_security_identifier(user_agent or "unknown"),
            )
            self._db.commit()
            raise PasswordResetInvalidCodeError

        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = PasswordResetChallengeStatus.LOCKED
            challenge.locked_at = now
            challenge.updated_at = now
            self._record_audit(
                event_type="PASSWORD_RESET_CODE_LOCKED",
                seller_id=challenge.seller_id,
                email_hash=hash_security_identifier(normalized_email),
                request_ip_hash=hash_security_identifier(request_ip or "unknown"),
                user_agent_hash=hash_security_identifier(user_agent or "unknown"),
            )
            self._db.commit()
            raise PasswordResetInvalidCodeError

        expected_hash = hash_password_reset_code(
            str(challenge.id), normalized_email, code
        )
        if not hmac.compare_digest(expected_hash, challenge.code_hash):
            challenge.attempt_count += 1
            challenge.updated_at = now
            event_type = "PASSWORD_RESET_CODE_FAILED"
            if challenge.attempt_count >= challenge.max_attempts:
                challenge.status = PasswordResetChallengeStatus.LOCKED
                challenge.locked_at = now
                event_type = "PASSWORD_RESET_CODE_LOCKED"
            self._record_audit(
                event_type=event_type,
                seller_id=challenge.seller_id,
                email_hash=hash_security_identifier(normalized_email),
                request_ip_hash=hash_security_identifier(request_ip or "unknown"),
                user_agent_hash=hash_security_identifier(user_agent or "unknown"),
            )
            self._db.commit()
            raise PasswordResetInvalidCodeError

        challenge.status = PasswordResetChallengeStatus.VERIFIED
        challenge.verified_at = now
        challenge.updated_at = now
        raw_token = secrets.token_urlsafe(32)
        authorization = PasswordResetAuthorization(
            challenge_id=challenge.id,
            seller_id=challenge.seller_id,
            token_hash=hash_password_reset_authorization(raw_token),
            expires_at=now
            + timedelta(minutes=settings.password_reset_auth_ttl_minutes),
            created_at=now,
        )
        self._db.add(authorization)
        self._record_audit(
            event_type="PASSWORD_RESET_CODE_VERIFIED",
            seller_id=challenge.seller_id,
            email_hash=hash_security_identifier(normalized_email),
            request_ip_hash=hash_security_identifier(request_ip or "unknown"),
            user_agent_hash=hash_security_identifier(user_agent or "unknown"),
        )
        self._db.commit()
        return raw_token, _as_utc(authorization.expires_at)

    def reset_password(
        self,
        *,
        reset_authorization: str,
        new_password: str,
        confirm_password: str,
        request_ip: str,
        user_agent: str,
    ) -> None:
        self._ensure_enabled()
        if new_password != confirm_password:
            raise PasswordResetValidationError("The passwords do not match.")
        try:
            validate_password(new_password)
        except ValueError as exc:
            raise PasswordResetValidationError(str(exc)) from exc
        if not reset_authorization:
            raise PasswordResetSessionExpiredError

        now = _utc_now()
        token_hash = hash_password_reset_authorization(reset_authorization)
        authorization = self._db.execute(
            select(PasswordResetAuthorization)
            .where(
                PasswordResetAuthorization.token_hash == token_hash,
                PasswordResetAuthorization.consumed_at.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if authorization is None or _as_utc(authorization.expires_at) <= now:
            raise PasswordResetSessionExpiredError

        seller = self._db.execute(
            select(Seller).where(Seller.id == authorization.seller_id).with_for_update()
        ).scalar_one_or_none()
        challenge = self._db.execute(
            select(PasswordResetChallenge)
            .where(PasswordResetChallenge.id == authorization.challenge_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            seller is None
            or challenge is None
            or challenge.status != PasswordResetChallengeStatus.VERIFIED
        ):
            raise PasswordResetSessionExpiredError

        seller.password_hash = get_password_hash(new_password)
        if settings.password_reset_revoke_sessions:
            seller.auth_version += 1
        authorization.consumed_at = now
        challenge.status = PasswordResetChallengeStatus.CONSUMED
        challenge.consumed_at = now
        challenge.updated_at = now
        self._invalidate_seller_reset_state(
            seller.id, now, exclude_challenge_id=challenge.id
        )
        self._record_audit(
            event_type="PASSWORD_RESET_COMPLETED",
            seller_id=seller.id,
            email_hash=hash_security_identifier(seller.email),
            request_ip_hash=hash_security_identifier(request_ip or "unknown"),
            user_agent_hash=hash_security_identifier(user_agent or "unknown"),
        )
        self._db.commit()

    def _invalidate_seller_reset_state(
        self,
        seller_id: UUID,
        now: datetime,
        *,
        exclude_challenge_id: UUID | None = None,
    ) -> None:
        challenge_statement = update(PasswordResetChallenge).where(
            PasswordResetChallenge.seller_id == seller_id,
            PasswordResetChallenge.status.in_(ACTIVE_CHALLENGE_STATUSES),
        )
        if exclude_challenge_id is not None:
            challenge_statement = challenge_statement.where(
                PasswordResetChallenge.id != exclude_challenge_id
            )
        self._db.execute(
            challenge_statement.values(
                status=PasswordResetChallengeStatus.CANCELLED,
                updated_at=now,
            )
        )
        self._db.execute(
            update(PasswordResetAuthorization)
            .where(
                PasswordResetAuthorization.seller_id == seller_id,
                PasswordResetAuthorization.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

    def _record_audit(
        self,
        *,
        event_type: str,
        seller_id: UUID | None,
        email_hash: str | None,
        request_ip_hash: str | None,
        user_agent_hash: str | None,
    ) -> None:
        self._db.add(
            SecurityAuditEvent(
                seller_id=seller_id,
                event_type=event_type,
                email_hash=email_hash,
                request_ip_hash=request_ip_hash,
                user_agent_hash=user_agent_hash,
                created_at=_utc_now(),
            )
        )
        self._logger.info(
            "password_reset_audit event=%s seller_id=%s",
            event_type,
            seller_id,
        )

    @staticmethod
    def _ensure_enabled() -> None:
        if not settings.password_reset_enabled:
            raise PasswordResetError("Password reset is unavailable.")


def _normalize_email(email: str) -> str:
    return str(email).strip().lower()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _age_seconds(created_at: datetime | None, now: datetime) -> float:
    if created_at is None:
        return float("inf")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created_at).total_seconds())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "PasswordResetError",
    "PasswordResetInvalidCodeError",
    "PasswordResetRateLimitExceeded",
    "PasswordResetService",
    "PasswordResetSessionExpiredError",
    "PasswordResetValidationError",
]
