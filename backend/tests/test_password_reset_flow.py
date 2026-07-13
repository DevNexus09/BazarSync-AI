from __future__ import annotations

from datetime import timedelta
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password
from app.db.base import Base
from app.models.password_reset import (
    PasswordResetAuthorization,
    PasswordResetChallenge,
    PasswordResetChallengeStatus,
)
from app.models.security_audit_event import SecurityAuditEvent
from app.models.seller import Seller
from app.services.password_reset_service import (
    PasswordResetInvalidCodeError,
    PasswordResetService,
)
from app.services.password_reset_rate_limiter import (
    PasswordResetRateLimitExceeded,
    PasswordResetRateLimiter,
)


class CapturingEmailService:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def send_code(self, *, email: str, code: str, expires_minutes: int) -> None:
        del email, expires_minutes
        self.codes.append(code)


class NoOpRateLimiter:
    def check(self, email: str, request_ip: str) -> None:
        del email, request_ip


class PasswordResetFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(
            self.engine,
            tables=[
                Seller.__table__,
                PasswordResetChallenge.__table__,
                PasswordResetAuthorization.__table__,
                SecurityAuditEvent.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.seller = Seller(
            id=uuid4(),
            email="seller@example.com",
            password_hash="legacy-password",
            auth_version=0,
        )
        self.db.add(self.seller)
        self.db.commit()
        self.email = CapturingEmailService()
        self.service = PasswordResetService(
            self.db,
            email_service=self.email,
            rate_limiter=NoOpRateLimiter(),
        )

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(
            self.engine,
            tables=[
                SecurityAuditEvent.__table__,
                PasswordResetAuthorization.__table__,
                PasswordResetChallenge.__table__,
                Seller.__table__,
            ],
        )
        self.engine.dispose()

    def test_registered_and_unregistered_requests_are_response_equivalent_and_code_is_hashed(
        self,
    ) -> None:
        self.service.request_code(
            email=" SELLER@example.com ",
            request_ip="127.0.0.1",
            user_agent="test-agent",
        )
        registered_challenge = self.db.scalar(select(PasswordResetChallenge))
        self.assertIsNotNone(registered_challenge)
        self.assertEqual(1, len(self.email.codes))
        self.assertNotEqual(self.email.codes[0], registered_challenge.code_hash)
        self.assertEqual(64, len(registered_challenge.code_hash))

        self.service.request_code(
            email="unknown@example.com",
            request_ip="127.0.0.2",
            user_agent="test-agent",
        )
        self.assertEqual(1, len(self.email.codes))
        self.assertEqual(
            2, self.db.scalar(select(func.count()).select_from(SecurityAuditEvent))
        )

    def test_correct_code_is_single_use_and_reset_revokes_auth_version(self) -> None:
        with patch.object(settings, "password_reset_resend_cooldown_seconds", 0):
            self.service.request_code(
                email=self.seller.email,
                request_ip="127.0.0.1",
                user_agent="test-agent",
            )
        token, _ = self.service.verify_code(
            email=self.seller.email,
            code=self.email.codes[0],
            request_ip="127.0.0.1",
            user_agent="test-agent",
        )

        with self.assertRaises(PasswordResetInvalidCodeError):
            self.service.verify_code(
                email=self.seller.email,
                code=self.email.codes[0],
                request_ip="127.0.0.1",
                user_agent="test-agent",
            )

        self.service.reset_password(
            reset_authorization=token,
            new_password="new-secure-password",
            confirm_password="new-secure-password",
            request_ip="127.0.0.1",
            user_agent="test-agent",
        )
        self.db.refresh(self.seller)
        self.assertTrue(
            verify_password("new-secure-password", self.seller.password_hash)
        )
        self.assertEqual(1, self.seller.auth_version)
        self.assertEqual(
            PasswordResetChallengeStatus.CONSUMED,
            self.db.scalar(select(PasswordResetChallenge.status)),
        )

    def test_wrong_code_locks_after_configured_attempts(self) -> None:
        with patch.object(settings, "password_reset_max_attempts", 2):
            self.service.request_code(
                email=self.seller.email,
                request_ip="127.0.0.1",
                user_agent="test-agent",
            )
            for _ in range(2):
                with self.assertRaises(PasswordResetInvalidCodeError):
                    self.service.verify_code(
                        email=self.seller.email,
                        code="000000",
                        request_ip="127.0.0.1",
                        user_agent="test-agent",
                    )

        challenge = self.db.scalar(select(PasswordResetChallenge))
        self.assertEqual(PasswordResetChallengeStatus.LOCKED, challenge.status)
        self.assertEqual(2, challenge.attempt_count)

    def test_expired_code_and_resend_invalidate_old_challenge(self) -> None:
        self.service.request_code(
            email=self.seller.email,
            request_ip="127.0.0.1",
            user_agent="test-agent",
        )
        first_code = self.email.codes[0]
        challenge = self.db.scalar(select(PasswordResetChallenge))
        challenge.expires_at -= timedelta(minutes=20)
        self.db.commit()

        with self.assertRaises(PasswordResetInvalidCodeError):
            self.service.verify_code(
                email=self.seller.email,
                code=first_code,
                request_ip="127.0.0.1",
                user_agent="test-agent",
            )

        with patch.object(settings, "password_reset_resend_cooldown_seconds", 0):
            self.service.request_code(
                email=self.seller.email,
                request_ip="127.0.0.1",
                user_agent="test-agent",
            )
        challenges = self.db.scalars(
            select(PasswordResetChallenge).order_by(PasswordResetChallenge.created_at)
        ).all()
        self.assertEqual(2, len(challenges))
        self.assertNotEqual(challenges[0].status, PasswordResetChallengeStatus.PENDING)
        self.assertNotEqual(first_code, self.email.codes[-1])

    def test_email_and_ip_rate_limits_are_enforced_without_revealing_keys(self) -> None:
        limiter = PasswordResetRateLimiter()
        with (
            patch.object(settings, "redis_broker_url", None),
            patch.object(settings, "password_reset_max_requests_per_hour", 2),
            patch.object(settings, "password_reset_max_requests_per_ip", 2),
        ):
            limiter.check("seller@example.com", "127.0.0.1")
            limiter.check("seller@example.com", "127.0.0.1")
            with self.assertRaises(PasswordResetRateLimitExceeded):
                limiter.check("seller@example.com", "127.0.0.1")

        self.assertNotIn("seller@example.com", limiter._local_events)
        self.assertNotIn("127.0.0.1", limiter._local_events)


if __name__ == "__main__":
    unittest.main()
