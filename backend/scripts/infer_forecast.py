"""Run one seller-scoped forecast in the dedicated inference environment."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from app.schemas.demand_regime import RegimeSelectionPolicy
from app.schemas.forecast_features import ForecastHorizon, ForecastSourceSnapshot
from app.schemas.forecast_inference import ForecastMode, InferenceLimits
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.statistical_forecast_service import StatisticalForecastService

MAX_SNAPSHOT = 2 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", required=True, type=UUID)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--horizon", type=int, choices=(7, 14, 30), required=True)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--cpu-seconds", type=int, default=4)
    parser.add_argument("--address-space-mib", type=int, default=1024)
    parser.add_argument("--baseline-policy", type=Path)
    try:
        args = parser.parse_args()
        with args.snapshot.open("rb") as handle:
            payload = handle.read(MAX_SNAPSHOT + 1)
        if len(payload) > MAX_SNAPSHOT:
            parser.error("Forecast snapshot exceeds the configured input size.")
        snapshot = ForecastSourceSnapshot.model_validate_json(payload)
        policy = None
        if args.baseline_policy is not None:
            with args.baseline_policy.open("rb") as handle:
                payload = handle.read(MAX_SNAPSHOT + 1)
            if len(payload) > MAX_SNAPSHOT:
                parser.error("Baseline policy exceeds the configured input size.")
            policy = RegimeSelectionPolicy.model_validate_json(payload)
        origin = TypeAdapter(AwareDatetime).validate_python(args.origin)
        horizon: ForecastHorizon = TypeAdapter(ForecastHorizon).validate_python(
            args.horizon
        )
        service = ForecastInferenceService(
            RegimeForecastService(
                StatisticalForecastService(
                    authorized_seller_id=args.seller_id,
                    config=policy.baseline_config if policy is not None else None,
                )
            ),
            mode=ForecastMode(os.getenv("FORECAST_ML_MODE", "disabled")),
            artifact_root=Path(os.getenv("FORECAST_ARTIFACT_ROOT", "/models")),
            registry_digest=os.getenv("FORECAST_REGISTRY_SHA256"),
            limits=InferenceLimits(
                timeout_seconds=args.timeout,
                cpu_seconds=args.cpu_seconds,
                address_space_mib=args.address_space_mib,
            ),
        )
        result = service.forecast(
            snapshot, forecast_origin=origin, horizon_days=horizon, policy=policy
        )
    except ValidationError as exc:
        parser.error(
            f"Invalid inference input ({exc.error_count()} validation errors)."
        )
    except (OSError, ValueError, PermissionError):
        parser.error(
            "Unable to read forecast input or the seller scope or settings are invalid."
        )
    print(
        json.dumps(
            {
                "result": result.model_dump(mode="json"),
                "health": service.health_metrics(),
            }
        )
    )


if __name__ == "__main__":
    main()
