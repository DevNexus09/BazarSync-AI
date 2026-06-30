from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.repositories.competitor_event_repository import CompetitorEventRepository
from app.schemas.scrape import CompetitorEventPageResponse, CompetitorEventResponse

router = APIRouter(prefix="/competitor-events", tags=["competitor-events"])


@router.get("", response_model=CompetitorEventPageResponse)
def list_competitor_events(
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
    product_id: UUID | None = Query(None),
    competitor_id: UUID | None = Query(None),
    event_type: str | None = Query(None),
    severity: str | None = Query(None),
    from_at: datetime | None = Query(None, alias="from"),
    to_at: datetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> CompetitorEventPageResponse:
    if from_at and to_at and _ensure_utc(from_at) > _ensure_utc(to_at):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date range.")

    events, total = CompetitorEventRepository(db).list_events(
        seller_id=current_seller.id,
        product_id=product_id,
        competitor_id=competitor_id,
        event_type=event_type.upper() if event_type else None,
        severity=severity.upper() if severity else None,
        from_at=_ensure_utc(from_at) if from_at else None,
        to_at=_ensure_utc(to_at) if to_at else None,
        limit=limit,
        offset=offset,
    )
    return CompetitorEventPageResponse(
        items=[CompetitorEventResponse.model_validate(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
