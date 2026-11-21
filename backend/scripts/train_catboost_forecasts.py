"""Train and evaluate seller-scoped CatBoost forecasts from archived Phase 3 cases."""

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterator
from uuid import UUID

from pydantic import AwareDatetime, ValidationError

from app.schemas.demand_regime import RegimeSelectionPolicy
from app.schemas.forecast_features import FeatureModel, ForecastSourceSnapshot
from app.schemas.ml_forecast import CatBoostTrainingConfig, EvaluationScope
from app.schemas.statistical_forecast import BaselineConfig, BaselineModel
from app.services.catboost_forecast_service import (
    HORIZONS,
    CatBoostTrainingService,
    TrainingSample,
)
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_backtesting_service import _horizon_mase_scale
from app.services.forecast_feature_builder import (
    ForecastFeatureBuilder,
    eligible_observed_sales,
)
from app.services.historical_dataset_service import DAY, HistoricalDataset
from app.services.statistical_forecast_service import (
    NATIVE_MODELS,
    STATSFORECAST_MODELS,
    StatisticalForecastService,
)


class OriginFile(FeatureModel):
    forecast_origin: AwareDatetime
    snapshot: Path
    outcomes: Path


class TrainingManifest(FeatureModel):
    scope: EvaluationScope
    cases: tuple[OriginFile, ...]
    config: CatBoostTrainingConfig = CatBoostTrainingConfig()
    baseline_config: BaselineConfig = BaselineConfig()
    enable_statsforecast: bool = False
    baseline_policy: Path | None = None


def _samples(
    manifest: TrainingManifest,
    directory: Path,
    seller_id: UUID,
    *,
    lineage: list[dict[str, str]] | None = None,
    policy: RegimeSelectionPolicy | None = None,
) -> Iterator[TrainingSample]:
    builder = ForecastFeatureBuilder(authorized_seller_id=seller_id)
    baselines = StatisticalForecastService(
        authorized_seller_id=seller_id,
        config=manifest.baseline_config,
        enable_statsforecast=manifest.enable_statsforecast,
    )
    models: tuple[BaselineModel, ...] = (BaselineModel.AUTO, *NATIVE_MODELS)
    if manifest.enable_statsforecast:
        models += tuple(STATSFORECAST_MODELS)
    regimes = RegimeForecastService(baselines)
    observed_targets: dict[tuple[UUID, date], int] = {}
    for entry in manifest.cases:
        if policy is not None and policy.available_at >= entry.forecast_origin:
            raise ValueError(
                "Baseline selection policy must precede every archived origin."
            )
        source_bytes = (directory / entry.snapshot).read_bytes()
        outcome_bytes = (directory / entry.outcomes).read_bytes()
        snapshot = ForecastSourceSnapshot.model_validate_json(source_bytes)
        outcomes = HistoricalDataset.model_validate_json(outcome_bytes)
        prepared = baselines._prepare(snapshot, entry.forecast_origin, allow_empty=True)
        cohort = baselines._cohort(prepared)
        labels = builder.index_history(outcomes, snapshot.product_id)
        if lineage is not None:
            lineage.append(
                {
                    "product_id": str(snapshot.product_id),
                    "forecast_origin": prepared.origin.forecast_origin.isoformat(),
                    "captured_at": snapshot.captured_at.isoformat(),
                    "feature_extract_as_of": snapshot.history.as_of_timestamp.isoformat(),
                    "outcome_extract_as_of": outcomes.as_of_timestamp.isoformat(),
                    "snapshot_version": snapshot.version,
                    "dataset_version": outcomes.version,
                    "snapshot_sha256": sha256(source_bytes).hexdigest(),
                    "outcomes_sha256": sha256(outcome_bytes).hexdigest(),
                }
            )
        for offset in range(1, max(HORIZONS) + 1):
            day = prepared.origin.feature_date + offset * DAY
            units = eligible_observed_sales(labels.get(day))
            if (
                units is not None
                and observed_targets.setdefault((snapshot.product_id, day), units)
                != units
            ):
                raise ValueError(
                    "Conflicting observed outcomes for the same product-day."
                )
        for horizon in HORIZONS:
            example = builder.build_training_example(
                snapshot,
                forecast_origin=entry.forecast_origin,
                horizon_days=horizon,
                outcomes=outcomes,
                allow_empty=True,
            )
            forecasts = {}
            for model in models:
                result = baselines._forecast(
                    prepared, horizon, model, entry.forecast_origin
                )
                forecasts[str(model)] = result.expected_units
            fallback = regimes.forecast(
                snapshot,
                forecast_origin=entry.forecast_origin,
                horizon_days=horizon,
                generated_at=entry.forecast_origin,
                policy=policy,
            )
            forecasts["regime_fallback"] = fallback.forecast.expected_units
            yield TrainingSample(
                example=example,
                cohort=cohort,
                category=example.feature_row.features.category or "unknown",
                mase_scale=_horizon_mase_scale(prepared.sales, horizon),
                baseline_forecasts=forecasts,
                demand_regime=fallback.evidence.regime,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-id", required=True, type=UUID)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest_bytes = args.manifest.read_bytes()
        manifest = TrainingManifest.model_validate_json(manifest_bytes)
        if not manifest.cases:
            parser.error("The manifest must contain archived forecast origins.")
        args.output_dir.mkdir(mode=0o700)
        entries: list[dict[str, str]] = []
        policy_bytes = (
            (args.manifest.parent / manifest.baseline_policy).read_bytes()
            if manifest.baseline_policy is not None
            else None
        )
        policy = (
            RegimeSelectionPolicy.model_validate_json(policy_bytes)
            if policy_bytes is not None
            else None
        )
        if policy is not None and (
            policy.seller_id != args.seller_id
            or policy.baseline_config != manifest.baseline_config
        ):
            raise ValueError(
                "Baseline policy must match the training seller and baseline configuration."
            )
        samples = list(
            _samples(
                manifest,
                args.manifest.parent,
                args.seller_id,
                lineage=entries,
                policy=policy,
            )
        )
        lineage = json.dumps(
            {
                "version": "catboost-input-lineage-v1",
                "scope": manifest.scope,
                "seller_id": str(args.seller_id),
                "manifest_sha256": sha256(manifest_bytes).hexdigest(),
                "baseline_policy_sha256": sha256(policy_bytes).hexdigest()
                if policy_bytes is not None
                else None,
                "cases": entries,
            },
            sort_keys=True,
            indent=2,
        ).encode()
        (args.output_dir / "lineage.json").write_bytes(lineage)
        report = CatBoostTrainingService(
            seller_id=args.seller_id, config=manifest.config
        ).train(
            samples,
            output_dir=args.output_dir,
            scope=manifest.scope,
            lineage_sha256=sha256(lineage).hexdigest(),
        )
    except ValidationError as exc:
        parser.error(
            f"Invalid training artifact ({exc.error_count()} validation errors)."
        )
    except (OSError, ValueError, RuntimeError, PermissionError) as exc:
        parser.error(str(exc))
    print(report.model_dump_json())


if __name__ == "__main__":
    main()
