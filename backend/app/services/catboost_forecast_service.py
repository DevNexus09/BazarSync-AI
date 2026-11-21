"""Deterministic offline CatBoost demand training and fail-closed inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import math
import os
from pathlib import Path
import platform as platform_module
import statistics
from typing import Iterable, Mapping, Sequence
from uuid import UUID

from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

from app.schemas.demand_regime import DemandRegime
from app.schemas.forecast_features import (
    FEATURE_SCHEMA_SHA256,
    FEATURE_VERSION,
    ForecastFeatureRow,
    ForecastHorizon,
    ForecastTrainingExample,
)
from app.schemas.ml_forecast import (
    CatBoostCandidateResult,
    CatBoostEvaluationReport,
    CatBoostModelMetadata,
    CatBoostTrainingConfig,
    EvaluationScope,
    HorizonTrainingResult,
    MLEvaluationMetrics,
    MLForecastResult,
    MLForecastStatus,
    ModelSelectionStatus,
)
from app.schemas.statistical_forecast import ProductCohort
from app.services.catboost_features import (
    CATBOOST_VERSION as CATBOOST_VERSION,
    ENCODER_VERSION,
    MODEL_VERSION,
    flatten_feature_row as flatten_feature_row,
)
from app.services.historical_dataset_service import DAY, _opening

HORIZONS: tuple[ForecastHorizon, ...] = (7, 14, 30)


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class TrainingSample:
    example: ForecastTrainingExample
    cohort: ProductCohort
    category: str
    mase_scale: Decimal | None
    baseline_forecasts: Mapping[str, Decimal | None]
    demand_regime: DemandRegime


@dataclass(frozen=True)
class _Candidate:
    name: str
    loss: str
    depth: int
    learning_rate: float
    l2_leaf_reg: float = 3.0


CANDIDATES = (
    _Candidate("rmse_depth4", "RMSE", 4, 0.05),
    _Candidate("mae_depth4", "MAE", 4, 0.05),
    _Candidate("poisson_depth4", "Poisson", 4, 0.05),
    _Candidate("tweedie_depth4", "Tweedie:variance_power=1.5", 4, 0.05),
    _Candidate("rmse_depth6", "RMSE", 6, 0.03, 5.0),
)


def _metrics(
    model_name: str,
    horizon: ForecastHorizon,
    samples: Sequence[TrainingSample],
    predictions: Sequence[float],
    *,
    category: str = "all",
    cohort: ProductCohort = ProductCohort.ALL,
) -> MLEvaluationMetrics:
    pairs = [
        (sample, Decimal(str(prediction)), Decimal(sample.example.target_net_units))
        for sample, prediction in zip(samples, predictions, strict=True)
        if sample.example.target_net_units is not None
        and (category == "all" or sample.category == category)
        and (cohort == ProductCohort.ALL or sample.cohort == cohort)
    ]
    if not pairs:
        return MLEvaluationMetrics(
            model_name=model_name,
            horizon_days=horizon,
            category=category,
            cohort=cohort,
            scored_rows=0,
        )
    errors = [prediction - actual for _, prediction, actual in pairs]
    absolute = [abs(error) for error in errors]
    actual_total = sum((actual for _, _, actual in pairs), Decimal(0))
    scaled = [
        abs(prediction - actual) / sample.mase_scale
        for sample, prediction, actual in pairs
        if sample.mase_scale is not None and sample.mase_scale > 0
    ]
    count = Decimal(len(pairs))
    return MLEvaluationMetrics(
        model_name=model_name,
        horizon_days=horizon,
        category=category,
        cohort=cohort,
        scored_rows=len(pairs),
        mae=sum(absolute, Decimal(0)) / count,
        wape_percent=(Decimal(100) * sum(absolute, Decimal(0)) / actual_total)
        if actual_total > 0
        else None,
        mase=sum(scaled, Decimal(0)) / len(scaled) if scaled else None,
        bias_units=sum(errors, Decimal(0)) / count,
    )


class CatBoostTrainingService:
    def __init__(
        self, *, seller_id: UUID, config: CatBoostTrainingConfig | None = None
    ):
        if version("catboost") != CATBOOST_VERSION:
            raise RuntimeError(f"CatBoost {CATBOOST_VERSION} is required.")
        self.seller_id = seller_id
        self.config = config or CatBoostTrainingConfig()

    def _validate(self, samples: Iterable[TrainingSample]) -> list[TrainingSample]:
        validated = []
        seen = set()
        for sample in samples:
            row = sample.example.feature_row
            if row.seller_id != self.seller_id:
                raise PermissionError("Training samples must stay within seller scope.")
            units = sample.example.target_net_units
            if units is not None and (
                units < 0
                or sample.example.eligible_target_days != row.horizon_days
                or sample.example.outcome_extract_cutoff
                < _opening(row.target_end_date + DAY)
            ):
                raise ValueError(
                    "Training labels must be nonnegative and cover a closed horizon."
                )
            key = (row.product_id, row.feature_date, row.horizon_days)
            if key in seen:
                raise ValueError("Duplicate product-origin-horizon training sample.")
            seen.add(key)
            flatten_feature_row(row)
            validated.append(sample)
        return sorted(
            validated,
            key=lambda item: (
                item.example.feature_row.feature_date,
                item.example.feature_row.product_id,
                item.example.feature_row.horizon_days,
            ),
        )

    def train(
        self,
        samples: Iterable[TrainingSample],
        *,
        output_dir: Path,
        scope: EvaluationScope,
        generated_at: datetime | None = None,
        lineage_sha256: str | None = None,
    ) -> CatBoostEvaluationReport:
        generated = (generated_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        rows = self._validate(samples)
        output_dir.mkdir(parents=True, exist_ok=True)
        results = tuple(
            self._train_horizon(
                [
                    sample
                    for sample in rows
                    if sample.example.feature_row.horizon_days == horizon
                ],
                horizon,
                output_dir,
                scope,
                generated,
                lineage_sha256,
            )
            for horizon in HORIZONS
        )
        report = CatBoostEvaluationReport(
            generated_at=generated,
            seller_id=self.seller_id,
            scope=scope,
            catboost_version=CATBOOST_VERSION,
            python_version=platform_module.python_version(),
            platform=platform_module.platform(),
            feature_version=FEATURE_VERSION,
            feature_schema_sha256=FEATURE_SCHEMA_SHA256,
            config=self.config,
            production_selection_allowed=(
                scope == EvaluationScope.HISTORICAL_HOLDOUT
                and lineage_sha256 is not None
                and any(
                    result.status == ModelSelectionStatus.SELECTED for result in results
                )
            ),
            lineage_sha256=lineage_sha256,
            results=results,
        )
        _write_text_atomic(
            output_dir / "evaluation.json", report.model_dump_json(indent=2)
        )
        return report

    @staticmethod
    def _scorable(sample: TrainingSample) -> bool:
        return (
            sample.example.target_net_units is not None
            and sample.example.feature_row.quality.sufficient_history
            and sample.demand_regime == DemandRegime.REGULAR
        )

    def _split(self, samples: Sequence[TrainingSample]):
        dates = sorted({sample.example.feature_row.feature_date for sample in samples})
        if len(dates) <= self.config.test_origins:
            return (), (), tuple(filter(self._scorable, samples)), None
        test_start = dates[-self.config.test_origins]
        test_origin = _opening(test_start)
        development, embargo, test = [], [], []
        for sample in filter(self._scorable, samples):
            row = sample.example.feature_row
            if row.feature_date >= test_start:
                test.append(sample)
            elif (
                row.target_end_date < test_start
                and sample.example.outcome_extract_cutoff < test_origin
            ):
                development.append(sample)
            else:
                embargo.append(sample)
        return development, embargo, test, test_start

    def _folds(self, development: Sequence[TrainingSample]):
        dates = sorted(
            {sample.example.feature_row.feature_date for sample in development}
        )
        block = self.config.validation_origins
        folds = []
        for fold_index in range(self.config.rolling_folds, 0, -1):
            end = len(dates) - (fold_index - 1) * block
            start = max(0, end - block)
            validation_dates = set(dates[start:end])
            if end <= 0 or not validation_dates:
                continue
            validation_start = min(validation_dates)
            validation_origin = _opening(validation_start)
            training = tuple(
                sample
                for sample in development
                if sample.example.feature_row.target_end_date < validation_start
                and sample.example.outcome_extract_cutoff < validation_origin
            )
            validation = tuple(
                sample
                for sample in development
                if sample.example.feature_row.feature_date in validation_dates
            )
            if len(training) >= self.config.minimum_training_rows and validation:
                folds.append((training, validation))
        return folds

    def _pool(self, samples: Sequence[TrainingSample], feature_names=None):
        records = [
            flatten_feature_row(sample.example.feature_row) for sample in samples
        ]
        names = tuple(feature_names or records[0].keys())
        if any(tuple(record.keys()) != names for record in records):
            raise ValueError("Flattened feature schema changed within one horizon.")
        categorical = tuple(
            name
            for name in names
            if name
            in {
                "category",
                "brand",
                "price_currency",
                "competitor_market_signature",
                "quality_flags",
            }
        )
        data = [[record[name] for name in names] for record in records]
        labels = [sample.example.target_net_units for sample in samples]
        return (
            Pool(
                data,
                label=labels,
                feature_names=list(names),
                cat_features=list(categorical),
                thread_count=self.config.thread_count,
            ),
            names,
            categorical,
        )

    def _model(self, candidate: _Candidate, iterations: int) -> CatBoostRegressor:
        return CatBoostRegressor(
            loss_function=candidate.loss,
            eval_metric="MAE",
            iterations=iterations,
            depth=candidate.depth,
            learning_rate=candidate.learning_rate,
            l2_leaf_reg=candidate.l2_leaf_reg,
            random_seed=self.config.random_seed,
            thread_count=self.config.thread_count,
            task_type="CPU",
            has_time=True,
            counter_calc_method="SkipTest",
            one_hot_max_size=1,
            allow_const_label=True,
            bootstrap_type="No",
            random_strength=0,
            allow_writing_files=False,
            verbose=False,
        )

    def _train_horizon(
        self, samples, horizon, output_dir, scope, generated, lineage_sha256
    ):
        development, embargo, test, test_start = self._split(samples)
        deployment_ineligible = sum(
            sample.demand_regime != DemandRegime.REGULAR for sample in samples
        )
        nonoverlapping = 0
        previous_date: date | None = None
        for day in sorted({sample.example.feature_row.feature_date for sample in test}):
            if previous_date is None or day - previous_date >= horizon * DAY:
                nonoverlapping += 1
                previous_date = day
        if (
            len(development) < self.config.minimum_training_rows
            or len(test) < self.config.minimum_test_rows
        ):
            return HorizonTrainingResult(
                horizon_days=horizon,
                status=ModelSelectionStatus.INSUFFICIENT_DATA,
                reason="CHRONOLOGICAL_TRAIN_TEST_ROWS",
                development_rows=len(development),
                embargoed_rows=len(embargo),
                test_rows=len(test),
                test_start_date=test_start,
                test_nonoverlapping_origins=nonoverlapping,
                deployment_ineligible_rows=deployment_ineligible,
            )
        folds = self._folds(development)
        if not folds:
            return HorizonTrainingResult(
                horizon_days=horizon,
                status=ModelSelectionStatus.INSUFFICIENT_DATA,
                reason="ROLLING_ORIGIN_FOLDS",
                development_rows=len(development),
                embargoed_rows=len(embargo),
                test_rows=len(test),
                test_start_date=test_start,
                test_nonoverlapping_origins=nonoverlapping,
                deployment_ineligible_rows=deployment_ineligible,
            )
        candidates = []
        for candidate in CANDIDATES:
            errors, best_iterations = [], []
            for training, validation in folds:
                train_pool, names, _ = self._pool(training)
                validation_pool, _, _ = self._pool(validation, names)
                model = self._model(candidate, self.config.iterations)
                model.fit(
                    train_pool,
                    eval_set=validation_pool,
                    early_stopping_rounds=self.config.early_stopping_rounds,
                    use_best_model=True,
                )
                predictions = self._validated_predictions(
                    model.predict(validation_pool)
                )
                errors.extend(
                    abs(prediction - sample.example.target_net_units)
                    for prediction, sample in zip(predictions, validation, strict=True)
                )
                best_iterations.append(max(1, model.tree_count_))
            candidates.append(
                CatBoostCandidateResult(
                    candidate_name=candidate.name,
                    loss_function=candidate.loss,
                    parameters=self._candidate_parameters(candidate),
                    folds=len(folds),
                    scored_rows=len(errors),
                    mae=Decimal(str(statistics.fmean(errors))) if errors else None,
                    selected_iterations=round(statistics.median(best_iterations)),
                )
            )
        selected_result = min(
            candidates,
            key=lambda item: (
                item.mae if item.mae is not None else Decimal("Infinity"),
                item.candidate_name,
            ),
        )
        selected = next(
            item for item in CANDIDATES if item.name == selected_result.candidate_name
        )
        train_pool, names, categorical = self._pool(development)
        test_pool, _, _ = self._pool(test, names)
        model = self._model(
            selected, selected_result.selected_iterations or self.config.iterations
        )
        model.fit(train_pool)
        predictions = self._validated_predictions(model.predict(test_pool))
        groups = [
            ("all", ProductCohort.ALL),
            *(
                (category, ProductCohort.ALL)
                for category in sorted({sample.category for sample in test} - {"all"})
            ),
            *(
                ("all", cohort)
                for cohort in sorted(
                    {sample.cohort for sample in test} - {ProductCohort.ALL}
                )
            ),
        ]
        metrics = [
            _metrics(
                "catboost", horizon, test, predictions, category=category, cohort=cohort
            )
            for category, cohort in groups
        ]
        baseline_names = sorted(
            {name for sample in test for name in sample.baseline_forecasts}
        )
        for baseline in baseline_names:
            eligible = [
                (sample, sample.baseline_forecasts.get(baseline))
                for sample in test
                if sample.baseline_forecasts.get(baseline) is not None
            ]
            baseline_samples = [sample for sample, _ in eligible]
            values = [float(value) for _, value in eligible if value is not None]
            metrics.extend(
                _metrics(
                    baseline,
                    horizon,
                    baseline_samples,
                    values,
                    category=category,
                    cohort=cohort,
                )
                for category, cohort in groups
            )
        catboost_metric = metrics[0]
        baselines = [
            item
            for item in metrics[1:]
            if item.category == "all"
            and item.cohort == ProductCohort.ALL
            and item.mae is not None
            and item.scored_rows == catboost_metric.scored_rows
        ]
        improved = bool(
            catboost_metric.mae is not None
            and baselines
            and catboost_metric.mae
            < min(item.mae for item in baselines if item.mae is not None)
        )
        promotion_supported = scope == EvaluationScope.SYNTHETIC or (
            nonoverlapping >= 3
            and any(item.model_name == "regime_fallback" for item in baselines)
        )
        status = (
            ModelSelectionStatus.SELECTED
            if improved and promotion_supported
            else ModelSelectionStatus.BASELINE_RETAINED
        )
        model_name = f"catboost-horizon-{horizon}.cbm"
        model_path = output_dir / model_name
        temporary_model = output_dir / f".{model_name}.tmp"
        model.save_model(temporary_model)
        os.replace(temporary_model, model_path)
        digest = sha256(model_path.read_bytes()).hexdigest()
        metadata = CatBoostModelMetadata(
            seller_id=self.seller_id,
            horizon_days=horizon,
            trained_at=generated,
            training_data_cutoff=max(
                item.example.outcome_extract_cutoff for item in development
            ),
            catboost_version=CATBOOST_VERSION,
            python_version=platform_module.python_version(),
            platform=platform_module.platform(),
            feature_version=FEATURE_VERSION,
            feature_schema_sha256=FEATURE_SCHEMA_SHA256,
            feature_names=names,
            categorical_features=categorical,
            encoder_version=ENCODER_VERSION,
            lineage_sha256=lineage_sha256,
            loss_function=selected.loss,
            parameters=self._candidate_parameters(selected)
            | {
                "iterations": selected_result.selected_iterations
                or self.config.iterations
            },
            model_file=model_name,
            model_sha256=digest,
            training_origin_start=min(
                item.example.feature_row.feature_date for item in development
            ),
            training_origin_end=max(
                item.example.feature_row.feature_date for item in development
            ),
            training_rows=len(development),
            evaluation_scope=scope,
            holdout_selection_status=status,
        )
        _write_text_atomic(
            output_dir / f"catboost-horizon-{horizon}.metadata.json",
            metadata.model_dump_json(indent=2),
        )
        return HorizonTrainingResult(
            horizon_days=horizon,
            status=status,
            reason=(
                None
                if improved and promotion_supported
                else "INSUFFICIENT_DEPLOYMENT_HOLDOUT_SUPPORT"
                if improved
                else "NO_FULL_COVERAGE_BASELINE"
                if not baselines
                else "NO_HOLDOUT_MAE_IMPROVEMENT"
            ),
            development_rows=len(development),
            embargoed_rows=len(embargo),
            test_rows=len(test),
            test_start_date=test_start,
            test_nonoverlapping_origins=nonoverlapping,
            deployment_ineligible_rows=deployment_ineligible,
            selected_candidate=selected.name,
            selected_loss_function=selected.loss,
            selected_iterations=selected_result.selected_iterations,
            candidate_results=tuple(candidates),
            metrics=tuple(metrics),
            model_file=model_name,
            model_sha256=digest,
        )

    def _candidate_parameters(self, candidate):
        return {
            "loss_function": candidate.loss,
            "depth": candidate.depth,
            "learning_rate": candidate.learning_rate,
            "l2_leaf_reg": candidate.l2_leaf_reg,
            "random_seed": self.config.random_seed,
            "thread_count": self.config.thread_count,
            "task_type": "CPU",
            "bootstrap_type": "No",
            "random_strength": 0,
            "has_time": True,
            "counter_calc_method": "SkipTest",
            "one_hot_max_size": 1,
            "allow_const_label": True,
        }

    @staticmethod
    def _validated_predictions(values) -> list[float]:
        predictions = [float(value) for value in values]
        if any(not math.isfinite(value) or value < 0 for value in predictions):
            raise RuntimeError(
                "CatBoost returned an invalid negative or non-finite forecast."
            )
        return predictions


class CatBoostForecastService:
    """Load one serialized direct-horizon model; never substitutes failures with zero."""

    def __init__(self, *, metadata_path: Path, authorized_seller_id: UUID):
        self.metadata = CatBoostModelMetadata.model_validate_json(
            metadata_path.read_bytes()
        )
        if self.metadata.seller_id != authorized_seller_id:
            raise PermissionError("Model seller scope does not match the caller.")
        if self.metadata.catboost_version != version("catboost"):
            raise RuntimeError(
                "CatBoost runtime differs from the serialized model metadata."
            )
        if (
            self.metadata.feature_schema_sha256 != FEATURE_SCHEMA_SHA256
            or self.metadata.feature_version != FEATURE_VERSION
            or self.metadata.encoder_version not in (None, ENCODER_VERSION)
        ):
            raise RuntimeError(
                "Model feature schema is not supported by this application version."
            )
        expected_file = f"catboost-horizon-{self.metadata.horizon_days}.cbm"
        model_path = metadata_path.parent / expected_file
        if self.metadata.model_file != expected_file or model_path.is_symlink():
            raise ValueError("The model must be the adjacent horizon artifact.")
        if sha256(model_path.read_bytes()).hexdigest() != self.metadata.model_sha256:
            raise RuntimeError("Serialized model checksum validation failed.")
        self.model = CatBoostRegressor()
        self.model.load_model(model_path)
        if tuple(self.model.feature_names_) != self.metadata.feature_names:
            raise ValueError("Serialized model features do not match metadata.")

    def forecast(self, row: ForecastFeatureRow) -> MLForecastResult:
        if row.seller_id != self.metadata.seller_id:
            raise PermissionError("Forecast row is outside the model seller scope.")
        if row.horizon_days != self.metadata.horizon_days:
            raise ValueError("Use the model matching the explicit forecast horizon.")
        record = flatten_feature_row(row)
        if not row.quality.sufficient_history:
            return self._unavailable(row, "INSUFFICIENT_FEATURE_HISTORY")
        if tuple(record) != self.metadata.feature_names:
            raise ValueError(
                "Inference feature shape differs from the training schema."
            )
        data = [[record[name] for name in self.metadata.feature_names]]
        pool = Pool(
            data,
            feature_names=list(self.metadata.feature_names),
            cat_features=list(self.metadata.categorical_features),
            thread_count=1,
        )
        try:
            value = float(self.model.predict(pool, thread_count=1)[0])
        except Exception as exc:
            raise RuntimeError(
                "CatBoost inference failed; no forecast was produced."
            ) from exc
        if not math.isfinite(value) or value < 0:
            raise RuntimeError("CatBoost inference returned an invalid forecast.")
        return MLForecastResult(
            seller_id=row.seller_id,
            product_id=row.product_id,
            forecast_origin=row.forecast_origin,
            horizon_days=row.horizon_days,
            target_start_date=row.target_start_date,
            target_end_date=row.target_end_date,
            expected_units=Decimal(str(value)),
            status=MLForecastStatus.AVAILABLE,
            model_version=MODEL_VERSION,
            model_sha256=self.metadata.model_sha256,
            feature_version=row.version,
            feature_schema_sha256=row.schema_sha256,
        )

    def _unavailable(self, row, reason):
        return MLForecastResult(
            seller_id=row.seller_id,
            product_id=row.product_id,
            forecast_origin=row.forecast_origin,
            horizon_days=row.horizon_days,
            target_start_date=row.target_start_date,
            target_end_date=row.target_end_date,
            status=MLForecastStatus.INSUFFICIENT_DATA,
            reason=reason,
            model_version=MODEL_VERSION,
            model_sha256=self.metadata.model_sha256,
            feature_version=row.version,
            feature_schema_sha256=row.schema_sha256,
        )
