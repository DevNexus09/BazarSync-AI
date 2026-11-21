"""Reproduce the Phase 4 synthetic audit. Never publish its temporary registry."""

from contextlib import redirect_stdout
from datetime import date, timedelta
from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import resource
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
from uuid import UUID

from app.schemas.forecast_inference import ForecastMode, ForecastModelManifest
from app.services.catboost_forecast_service import CatBoostForecastService, HORIZONS
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_interval_replay import (
    regime_forecast_context,
    replay_regime_intervals,
)
from app.services.forecast_interval_service import backtest_intervals
from app.services.statistical_forecast_service import StatisticalForecastService
from scripts.forecast_native_worker import runtime_dependencies
from scripts.train_catboost_forecasts import main as train
from test_catboost_forecast import write_archived_fixture
from test_forecast_inference import manifest, write_registry
from test_statistical_forecast import origin_case
from app.services.forecast_inference_service import ForecastInferenceService


def main():
    with TemporaryDirectory(prefix="phase4-fixture-") as temp:
        root = Path(temp)
        seller, training_manifest = write_archived_fixture(root)
        models = root / "models"
        cli = [
            "train",
            "--seller-id",
            str(seller),
            "--manifest",
            str(training_manifest),
            "--output-dir",
            str(models),
        ]
        with patch.object(sys, "argv", cli), redirect_stdout(io.StringIO()):
            train()
        evaluation = json.loads((models / "evaluation.json").read_bytes())
        lineage = (models / "lineage.json").read_bytes()
        assert sha256(lineage).hexdigest() == evaluation["lineage_sha256"]
        assert not evaluation["production_selection_allowed"]

        runtime = runtime_dependencies()
        native = {}
        release_parts = []
        legacy = {}
        for horizon in HORIZONS:
            name = f"catboost-horizon-{horizon}.cbm"
            data = (models / name).read_bytes()
            artifact_hash = sha256(data).hexdigest()
            release_parts.append(
                manifest(
                    "fixture-active",
                    artifact_hash,
                    horizon=horizon,
                    dependencies=runtime,
                )
            )
            legacy[horizon] = CatBoostForecastService(
                metadata_path=models / f"catboost-horizon-{horizon}.metadata.json",
                authorized_seller_id=seller,
            )
            for release in ("fixture-active", "fixture-previous"):
                target = root / str(seller) / release
                target.mkdir(parents=True, exist_ok=True)
                (target / name).write_bytes(data)
        active = ForecastModelManifest.model_validate(
            release_parts[0].model_dump()
            | {
                "artifacts": [part.artifacts[0] for part in release_parts],
            }
        )
        previous = active.model_copy(update={"release": "fixture-previous"})
        pin = write_registry(root, active=active, previous=previous)
        baselines = RegimeForecastService(
            StatisticalForecastService(authorized_seller_id=seller)
        )
        service = ForecastInferenceService(
            baselines,
            artifact_root=root,
            registry_digest=pin,
            mode=ForecastMode.ENABLED,
        )
        smoke = origin_case((10,) * 65, day=date(2027, 1, 1), product=UUID(int=901))
        for horizon in HORIZONS:
            durations = []
            forecasted = []
            row = baselines.baselines.features.build(
                smoke.snapshot,
                forecast_origin=smoke.forecast_origin,
                horizon_days=horizon,
            )
            expected = legacy[horizon].forecast(row).expected_units
            for _ in range(5):
                start = perf_counter()
                result = service.forecast(
                    smoke.snapshot,
                    forecast_origin=smoke.forecast_origin,
                    horizon_days=horizon,
                )
                durations.append((perf_counter() - start) * 1000)
                assert result.source == "active", result.attempts
                assert result.forecast.expected_units == expected
                forecasted.append(result.forecast.expected_units)
            native[str(horizon)] = {
                "samples": len(durations),
                "median_ms": round(median(durations), 2),
                "max_ms": round(max(durations), 2),
                "matched_task11_loader": len(set(forecasted)) == 1,
                "artifact_bytes": (models / f"catboost-horizon-{horizon}.cbm")
                .stat()
                .st_size,
            }
        child_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        child_rss_bytes = child_rss if sys.platform == "darwin" else child_rss * 1024
        fallback = {}
        for horizon in HORIZONS:
            name = f"catboost-horizon-{horizon}.cbm"
            (root / str(seller) / "fixture-active" / name).write_bytes(
                b"corruption fixture"
            )
            prior = service.forecast(
                smoke.snapshot,
                forecast_origin=smoke.forecast_origin,
                horizon_days=horizon,
            )
            assert prior.source == "previous"
            (root / str(seller) / "fixture-previous" / name).unlink()
            baseline = service.forecast(
                smoke.snapshot,
                forecast_origin=smoke.forecast_origin,
                horizon_days=horizon,
            )
            assert baseline.source == "baseline"
            fallback[str(horizon)] = [prior.source, baseline.source]

        # Separate later synthetic origins. Point models are frozen before this replay.
        start = date(2027, 1, 1)
        archive = [
            origin_case(
                (10,) * 65,
                actual=(value,) * 30,
                day=start + timedelta(days=index * 35),
                product=UUID(int=901),
            )
            for index, value in enumerate((7, 13) * 10 + (1, 10, 20))
        ]
        baseline_rows = list(replay_regime_intervals(archive, baselines))
        ml_rows = []
        for case, offset in zip(archive, range(0, len(baseline_rows), 3), strict=True):
            for horizon, sample in zip(
                HORIZONS, baseline_rows[offset : offset + 3], strict=True
            ):
                row = baselines.baselines.features.build(
                    case.snapshot,
                    forecast_origin=case.forecast_origin,
                    horizon_days=horizon,
                )
                ml_rows.append(
                    sample.model_copy(
                        update={"forecast": legacy[horizon].forecast(row)}
                    )
                )
        intervals = {}
        for name, rows in (("regime_fallback", baseline_rows), ("catboost", ml_rows)):
            report = backtest_intervals(
                rows,
                seller_id=seller,
                forecast_context=regime_forecast_context(baselines, None) + ":" + name,
                test_start_date=start + timedelta(days=20 * 35),
            )
            intervals[name] = report.model_dump(mode="json")
        print(
            json.dumps(
                {
                    "scope": "synthetic_fixture_only",
                    "approval": "simulated_ephemeral_registry_for_model_loading_only",
                    "dependencies": runtime,
                    "platform": platform.platform(),
                    "training": evaluation,
                    "lineage": json.loads(lineage),
                    "native_inference": native,
                    "max_child_rss_bytes": child_rss_bytes,
                    "rollback": fallback,
                    "intervals": intervals,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
