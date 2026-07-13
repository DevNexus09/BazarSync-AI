from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.api.v1.auth import router
from app.db.base import Base
from app.dependencies.db import get_db
from app.models.password_reset import PasswordResetAuthorization, PasswordResetChallenge
from app.models.security_audit_event import SecurityAuditEvent
from app.models.seller import Seller
from app.services.password_reset_email_service import PasswordResetEmailService
from app.services.password_reset_rate_limiter import password_reset_rate_limiter


class PasswordResetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
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
        self.db.add(
            Seller(
                id=uuid4(),
                email="seller@example.com",
                password_hash="legacy-password",
            )
        )
        self.db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.email_patch = patch.object(
            PasswordResetEmailService, "send_code", return_value=None
        )
        self.rate_patch = patch.object(
            password_reset_rate_limiter, "check", return_value=None
        )
        self.email_patch.start()
        self.rate_patch.start()

    def tearDown(self) -> None:
        self.rate_patch.stop()
        self.email_patch.stop()
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

    def test_registered_and_unregistered_requests_have_identical_public_response(
        self,
    ) -> None:
        registered = self.client.post(
            "/auth/forgot-password/request-code",
            json={"email": "seller@example.com"},
        )
        unregistered = self.client.post(
            "/auth/forgot-password/request-code",
            json={"email": "unknown@example.com"},
        )

        self.assertEqual(200, registered.status_code)
        self.assertEqual(200, unregistered.status_code)
        self.assertEqual(registered.json(), unregistered.json())

    def test_malformed_code_and_unauthorized_reset_do_not_echo_secrets(self) -> None:
        self.client.post(
            "/auth/forgot-password/request-code",
            json={"email": "seller@example.com"},
        )
        invalid_code = self.client.post(
            "/auth/forgot-password/verify-code",
            json={"email": "seller@example.com", "code": "12"},
        )
        self.assertEqual(400, invalid_code.status_code)
        self.assertNotIn("12", invalid_code.text)

        reset = self.client.post(
            "/auth/forgot-password/reset",
            json={
                "new_password": "new-secure-password",
                "confirm_password": "new-secure-password",
            },
        )
        self.assertEqual(400, reset.status_code)
        self.assertNotIn("new-secure-password", reset.text)


if __name__ == "__main__":
    unittest.main()
