from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models.seller import Seller


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a seller password locally.")
    parser.add_argument("--email", required=True, help="Seller email address")
    parser.add_argument("--password", default=None, help="New password. Omit to prompt securely.")
    args = parser.parse_args()

    password = args.password or getpass.getpass("New password: ")
    if len(password) < 8:
        print("password_reset_failed reason=password_must_be_at_least_8_characters")
        return 1

    normalized_email = args.email.strip().lower()
    session = SessionLocal()
    try:
        seller = session.execute(
            select(Seller).where(func.lower(Seller.email) == normalized_email)
        ).scalar_one_or_none()
        if seller is None:
            print(f"password_reset_failed reason=seller_not_found email={normalized_email}")
            return 1
        seller.email = normalized_email
        seller.password_hash = password
        session.add(seller)
        session.commit()
        print(f"password_reset_ok email={normalized_email}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
