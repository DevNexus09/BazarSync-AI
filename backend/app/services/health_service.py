from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.health import HealthResponse


class HealthService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def check(self) -> HealthResponse:
        self._db.execute(text("SELECT 1"))
        return HealthResponse(status="ok", database="up")
