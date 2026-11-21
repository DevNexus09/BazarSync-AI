"""Evaluate archived seller forecasts and write a deterministic JSON report to stdout."""

import argparse
from pathlib import Path
from typing import Iterator
from uuid import UUID

from pydantic import AwareDatetime, ValidationError

from app.schemas.forecast_features import FeatureModel, ForecastSourceSnapshot
from app.schemas.statistical_forecast import BaselineConfig
from app.services.forecast_backtesting_service import (
    ForecastBacktestingService,
    RollingOriginCase,
)
from app.services.historical_dataset_service import HistoricalDataset
from app.services.statistical_forecast_service import StatisticalForecastService


class OriginFile(FeatureModel):
    forecast_origin: AwareDatetime
    snapshot: Path
    outcomes: Path


class EvaluationManifest(FeatureModel):
    cases: tuple[OriginFile, ...]
    config: BaselineConfig = BaselineConfig()


def _cases(
    manifest: EvaluationManifest, directory: Path
) -> Iterator[RollingOriginCase]:
    for entry in manifest.cases:
        yield RollingOriginCase(
            forecast_origin=entry.forecast_origin,
            snapshot=ForecastSourceSnapshot.model_validate_json(
                (directory / entry.snapshot).read_bytes()
            ),
            outcomes=HistoricalDataset.model_validate_json(
                (directory / entry.outcomes).read_bytes()
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seller-id",
        required=True,
        type=UUID,
        help="Seller authorized for this evaluation",
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--statsforecast",
        action="store_true",
        help="Enable the optional intermittent benchmarks",
    )
    args = parser.parse_args()
    try:
        manifest = EvaluationManifest.model_validate_json(args.manifest.read_bytes())
        if not manifest.cases:
            parser.error("The manifest must have a forecast origin.")
        forecaster = StatisticalForecastService(
            authorized_seller_id=args.seller_id,
            config=manifest.config,
            enable_statsforecast=args.statsforecast,
        )
        report = ForecastBacktestingService(forecaster).evaluate(
            _cases(manifest, args.manifest.parent)
        )
    except ValidationError as exc:
        # Validation errors can contain source row values. Report the contract failure only.
        parser.error(
            f"Invalid forecasting artifact ({exc.error_count()} validation errors)."
        )
    except (ValueError, RuntimeError, PermissionError) as exc:
        parser.error(str(exc))
    except OSError:
        parser.error("Unable to read the evaluation manifest or a source artifact.")
    print(report.model_dump_json())


if __name__ == "__main__":
    main()
