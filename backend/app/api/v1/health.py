from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies.db import get_db
from app.schemas.health import HealthResponse
from app.services.health_service import HealthService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    service = HealthService(db)
    return service.check()
