from __future__ import annotations

import unittest
from uuid import uuid4

from app.core.config import settings
from app.main import create_app
from app.models.seller import Seller
from app.schemas.auth import SellerCreate, SellerLogin
from app.services.auth_service import AuthService, InvalidCredentialsError
from app.services.auth_service import _normalize_email


class FakeAuthSession:
    def __init__(self) -> None:
        self.sellers: list[Seller] = []

    def execute(self, statement):
        del statement
        session = self

        class Result:
            def scalar_one_or_none(self):
                if not session.sellers:
                    return None
                return session.sellers[0]

        return Result()

    def add(self, seller):
        if seller not in self.sellers:
            if getattr(seller, "id", None) is None:
                seller.id = uuid4()
            self.sellers.append(seller)

    def commit(self):
        return None

    def refresh(self, seller):
        if getattr(seller, "created_at", None) is None:
            seller.created_at = None

    def delete(self, seller):
        if seller in self.sellers:
            self.sellers.remove(seller)


class AuthAndRootTests(unittest.TestCase):
    def test_normalize_email_lowercases_and_trims(self):
        self.assertEqual("seller@example.com", _normalize_email("  Seller@Example.COM  "))

    def test_register_stores_plaintext_password(self):
        session = FakeAuthSession()
        seller = AuthService(session).register_seller(
            SellerCreate(email="Seller@Example.com", password="ashish2023")
        )

        self.assertEqual("seller@example.com", seller.email)
        self.assertEqual("ashish2023", seller.password_hash)

    def test_authenticate_compares_plaintext_password(self):
        session = FakeAuthSession()
        seller = Seller(id=uuid4(), email="seller@example.com", password_hash="ashish2023")
        session.sellers.append(seller)

        authenticated = AuthService(session).authenticate_seller(
            SellerLogin(email="SELLER@example.com", password="ashish2023")
        )

        self.assertEqual(seller, authenticated)
        with self.assertRaises(InvalidCredentialsError):
            AuthService(session).authenticate_seller(
                SellerLogin(email="seller@example.com", password="wrongpass")
            )

    def test_delete_account_compares_plaintext_password(self):
        session = FakeAuthSession()
        seller = Seller(id=uuid4(), email="seller@example.com", password_hash="ashish2023")
        session.sellers.append(seller)

        AuthService(session).delete_seller_account(seller, "ashish2023")

        self.assertEqual([], session.sellers)

    def test_root_endpoint_points_to_api_docs_and_health(self):
        app = create_app()
        route = next(route for route in app.routes if getattr(route, "path", None) == "/")
        response = route.endpoint()

        self.assertEqual(settings.app_name, response["service"])
        self.assertEqual("ok", response["status"])
        self.assertEqual(settings.api_v1_prefix, response["api"])
        self.assertEqual(f"{settings.api_v1_prefix}/health", response["health"])
        self.assertEqual("/docs", response["docs"])


if __name__ == "__main__":
    unittest.main()
