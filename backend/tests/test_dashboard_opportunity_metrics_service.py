import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.dashboard.opportunity_metrics_service import OpportunityMetricsService


def test_returns_no_metrics_when_seller_has_no_recommendations() -> None:
    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    metrics = asyncio.run(OpportunityMetricsService(session).get_metrics(seller_id="seller-1"))

    assert metrics == []
