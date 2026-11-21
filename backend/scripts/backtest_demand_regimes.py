"""Fit a seller-scoped Task 12 policy from archived Phase 3 forecast cases."""

import argparse
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.services.demand_regime_service import RegimeForecastService
from app.services.statistical_forecast_service import StatisticalForecastService
from scripts.backtest_statistical_forecasts import EvaluationManifest, _cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", required=True, type=UUID)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--statsforecast", action="store_true")
    args = parser.parse_args()
    try:
        manifest = EvaluationManifest.model_validate_json(args.manifest.read_bytes())
        forecaster = RegimeForecastService(
            StatisticalForecastService(
                authorized_seller_id=args.seller_id,
                config=manifest.config,
                enable_statsforecast=args.statsforecast,
            )
        )
        policy = forecaster.fit_policy(_cases(manifest, args.manifest.parent))
    except ValidationError as exc:
        parser.error(
            f"Invalid forecasting artifact ({exc.error_count()} validation errors)."
        )
    except (PermissionError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    except OSError:
        parser.error("Unable to read the evaluation manifest or a source artifact.")
    print(policy.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
