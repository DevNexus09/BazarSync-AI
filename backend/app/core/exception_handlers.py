from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas.dashboard.error_schema import DashboardErrorResponse, ErrorDetail
from app.services.dashboard.exceptions import DashboardServiceError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DashboardServiceError)
    async def handle_dashboard_error(
        _: Request, exc: DashboardServiceError
    ) -> JSONResponse:
        payload = DashboardErrorResponse(
            error=ErrorDetail(
                code=getattr(exc, "error_code", "dashboard_error"),
                message=exc.detail,
            )
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())
