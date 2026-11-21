"""Fit and evaluate Task 13 intervals on separate chronological periods."""

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.schemas.demand_regime import RegimeSelectionPolicy
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_interval_replay import (
    regime_forecast_context,
    replay_regime_intervals,
)
from app.services.forecast_interval_service import backtest_intervals
from app.services.statistical_forecast_service import StatisticalForecastService
from scripts.backtest_statistical_forecasts import EvaluationManifest, _cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", required=True, type=UUID)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--test-start",
        required=True,
        type=date.fromisoformat,
        help="First test origin business date in Asia/Dhaka",
    )
    parser.add_argument("--level", default="0.90")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--statsforecast", action="store_true")
    args = parser.parse_args()
    try:
        manifest = EvaluationManifest.model_validate_json(args.manifest.read_bytes())
        if not manifest.cases:
            parser.error("The manifest must contain archived forecast origins.")
        policy = (
            RegimeSelectionPolicy.model_validate_json(args.policy.read_bytes())
            if args.policy is not None
            else None
        )
        forecaster = RegimeForecastService(
            StatisticalForecastService(
                authorized_seller_id=args.seller_id,
                config=manifest.config,
                enable_statsforecast=args.statsforecast,
            )
        )
        report = backtest_intervals(
            replay_regime_intervals(
                _cases(manifest, args.manifest.parent), forecaster, policy=policy
            ),
            seller_id=args.seller_id,
            forecast_context=regime_forecast_context(forecaster, policy),
            test_start_date=args.test_start,
            nominal_level=Decimal(args.level),
        )
    except ValidationError as exc:
        parser.error(
            f"Invalid forecasting artifact ({exc.error_count()} validation errors)."
        )
    except (ValueError, RuntimeError, PermissionError, InvalidOperation) as exc:
        parser.error(str(exc))
    except OSError:
        parser.error("Unable to read the evaluation manifest or a source artifact.")
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
