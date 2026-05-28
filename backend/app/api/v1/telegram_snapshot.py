from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_seller
from app.dependencies.db import get_db
from app.models.seller import Seller
from app.schemas.product_snapshot import (
    ProductSnapshotErrorResponse,
    ProductSnapshotRequest,
    ProductSnapshotResponse,
)
from app.services.telegram.product_snapshot_service import (
    ProductSnapshotService,
    ProductSnapshotServiceError,
)

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)


@router.post(
    "/send-product-snapshot",
    response_model=ProductSnapshotResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ProductSnapshotErrorResponse},
        401: {"model": ProductSnapshotErrorResponse},
        403: {"model": ProductSnapshotErrorResponse},
        404: {"model": ProductSnapshotErrorResponse},
        422: {"model": ProductSnapshotErrorResponse},
        500: {"model": ProductSnapshotErrorResponse},
        502: {"model": ProductSnapshotErrorResponse},
    },
)
async def send_product_snapshot(
    payload: ProductSnapshotRequest,
    db: Session = Depends(get_db),
    current_seller: Seller = Depends(get_current_seller),
) -> ProductSnapshotResponse | JSONResponse:
    service = ProductSnapshotService(db, logger=logger)
    try:
        result = await service.send_snapshot(
            seller_id=current_seller.id,
            product_id=payload.product_id,
        )
    except ProductSnapshotServiceError as exc:
        return _error_response(exc)
    return ProductSnapshotResponse(
        success=True,
        message="Snapshot sent successfully",
        sent_at=result.sent_at,
        delivery_status=result.delivery_status,
    )


def _error_response(
    exc: ProductSnapshotServiceError, *, status_code: int | None = None
) -> JSONResponse:
    code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    payload = ProductSnapshotErrorResponse(
        success=False,
        detail=getattr(exc, "detail", str(exc)),
        error_code=getattr(exc, "error_code", None),
    ).model_dump()
    return JSONResponse(status_code=status_code or code, content=payload)
