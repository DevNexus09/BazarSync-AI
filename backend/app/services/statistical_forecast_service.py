"""Point forecasts using validated sales observed before a forecast origin."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from itertools import takewhile
from types import ModuleType
from uuid import UUID

from app.schemas.forecast_features import (
    FEATURE_VERSION,
    ForecastHorizon,
    ForecastSourceSnapshot,
)
from app.schemas.statistical_forecast import (
    BaselineConfig,
    BaselineModel,
    DataSufficiencyStatus,
    EvidenceStatus,
    ForecastResult,
    ProductCohort,
)
from app.services.forecast_feature_builder import ForecastFeatureBuilder, OriginHistory
from app.services.historical_dataset_service import DAY

MODEL_VERSION = "statistical-baselines-v1"
STATSFORECAST_VERSION = "2.1.1"
NATIVE_MODELS = (
    BaselineModel.NAIVE,
    BaselineModel.SEASONAL_NAIVE,
    BaselineModel.MOVING_AVERAGE,
    BaselineModel.EXPONENTIAL_SMOOTHING,
)
STATSFORECAST_MODELS = {
    BaselineModel.CROSTON_CLASSIC: "CrostonClassic",
    BaselineModel.CROSTON_SBA: "CrostonSBA",
    BaselineModel.CROSTON_OPTIMIZED: "CrostonOptimized",
    BaselineModel.TSB: "TSB",
    BaselineModel.ADIDA: "ADIDA",
}


@dataclass(frozen=True)
class PreparedForecast:
    product_id: UUID
    origin: OriginHistory
    captured_at: datetime
    sales: tuple[int, ...]  # Oldest to newest, with every day present.


def _supports_weekly_seasonality(
    sales: tuple[int, ...], config: BaselineConfig
) -> bool:
    if len(sales) < config.seasonal_minimum_days:
        return False
    weekly_error = sum(abs(sales[i] - sales[i - 7]) for i in range(7, len(sales)))
    naive_error = sum(abs(sales[i] - sales[i - 1]) for i in range(7, len(sales)))
    return naive_error > 0 and weekly_error <= config.seasonal_error_ratio * naive_error


def _zero_fraction(sales: tuple[int, ...]) -> Decimal:
    return Decimal(sales.count(0)) / len(sales)


class StatisticalForecastService:
    def __init__(
        self,
        *,
        authorized_seller_id: UUID,
        config: BaselineConfig | None = None,
        enable_statsforecast: bool = False,
    ) -> None:
        self.seller_id = authorized_seller_id
        self.config = config if config is not None else BaselineConfig()
        self.features = ForecastFeatureBuilder(
            authorized_seller_id=authorized_seller_id
        )
        self._stats_models: ModuleType | None = None
        self._numpy: ModuleType | None = None
        self.statsforecast_version: str | None = None
        self.statsforecast_dependencies: dict[str, str] = {}
        if enable_statsforecast:
            self._load_statsforecast()

    def _load_statsforecast(self) -> None:
        try:
            installed = version("statsforecast")
            if installed != STATSFORECAST_VERSION:
                raise RuntimeError(
                    f"Use StatsForecast {STATSFORECAST_VERSION} for this benchmark."
                )
            self._stats_models = import_module("statsforecast.models")
            self._numpy = import_module("numpy")
            self.statsforecast_dependencies = {
                name: version(name) for name in ("coreforecast", "numpy", "scipy")
            }
        except (ImportError, PackageNotFoundError, OSError) as exc:
            raise RuntimeError(
                "StatsForecast is unavailable in this evaluation environment."
            ) from exc
        self.statsforecast_version = installed

    def _prepare(
        self,
        snapshot: ForecastSourceSnapshot,
        origin: datetime,
        *,
        allow_empty: bool = False,
    ) -> PreparedForecast:
        history = self.features.prepare_history(
            snapshot,
            forecast_origin=origin,
            lookback_days=self.config.lookback_days,
            allow_empty=allow_empty,
        )
        sales = tuple(
            reversed(
                tuple(
                    value
                    for value in takewhile(
                        lambda value: value is not None, history.sales
                    )
                    if value is not None
                )
            )
        )
        return PreparedForecast(
            snapshot.product_id, history, snapshot.captured_at, sales
        )

    def _cohort(self, prepared: PreparedForecast) -> ProductCohort:
        sales = prepared.sales
        if prepared.origin.product_age_days < self.config.new_product_age_days:
            return ProductCohort.NEW
        if len(sales) < self.config.minimum_history_days:
            return ProductCohort.UNKNOWN
        if not any(sales):
            return ProductCohort.ZERO_DEMAND
        if _zero_fraction(sales) >= self.config.intermittent_zero_fraction:
            return ProductCohort.INTERMITTENT
        if Decimal(sum(sales)) >= self.config.high_volume_units_per_day * len(sales):
            return ProductCohort.HIGH_VOLUME
        return ProductCohort.LOW_VOLUME

    def forecast(
        self,
        snapshot: ForecastSourceSnapshot,
        *,
        forecast_origin: datetime,
        horizon_days: ForecastHorizon,
        model: BaselineModel = BaselineModel.AUTO,
        generated_at: datetime | None = None,
    ) -> ForecastResult:
        prepared = self._prepare(snapshot, forecast_origin)
        return self._forecast(
            prepared,
            horizon_days,
            model,
            generated_at if generated_at is not None else datetime.now(timezone.utc),
        )

    def _forecast(
        self,
        prepared: PreparedForecast,
        horizon: ForecastHorizon,
        requested: BaselineModel,
        generated_at: datetime,
    ) -> ForecastResult:
        if horizon not in (7, 14, 30) or generated_at.utcoffset() is None:
            raise ValueError(
                "An aware generation time and a 7, 14, or 30 day horizon are required."
            )
        sales = prepared.sales
        model = BaselineModel(requested)
        reason = None
        expected = None
        status = DataSufficiencyStatus.SUFFICIENT
        model_version = MODEL_VERSION
        with localcontext(Context(prec=38)):
            if len(sales) < self.config.minimum_history_days:
                status, reason = (
                    DataSufficiencyStatus.INSUFFICIENT,
                    "MINIMUM_CONTIGUOUS_HISTORY",
                )
            else:
                if model == BaselineModel.AUTO:
                    if _supports_weekly_seasonality(sales, self.config):
                        model = BaselineModel.SEASONAL_NAIVE
                    elif len(sales) >= self.config.moving_average_days:
                        model = BaselineModel.MOVING_AVERAGE
                    else:
                        model, reason = (
                            BaselineModel.NAIVE,
                            "MOVING_AVERAGE_WINDOW_UNAVAILABLE",
                        )
                expected, model_reason = self._predict(model, sales, horizon)
                if model_reason is not None:
                    status, reason = model_reason
                if (
                    model in STATSFORECAST_MODELS
                    and self.statsforecast_version is not None
                ):
                    model_version += f"+statsforecast-{self.statsforecast_version}"
        return ForecastResult(
            seller_id=self.seller_id,
            product_id=prepared.product_id,
            forecast_origin=prepared.origin.forecast_origin,
            horizon_days=horizon,
            target_start_date=prepared.origin.feature_date + DAY,
            target_end_date=prepared.origin.feature_date + horizon * DAY,
            expected_units=expected,
            requested_model=requested,
            model_name=model if expected is not None else None,
            model_version=model_version,
            data_sufficiency_status=status,
            evidence_status=(
                EvidenceStatus.ELIGIBLE_OBSERVED_SALES
                if expected is not None
                else EvidenceStatus.UNAVAILABLE
            ),
            generated_at=generated_at.astimezone(timezone.utc),
            fallback_reason=reason,
            contiguous_history_days=len(sales),
            data_cutoff=prepared.captured_at,
            feature_version=FEATURE_VERSION,
        )

    def _predict(
        self,
        model: BaselineModel,
        sales: tuple[int, ...],
        horizon: ForecastHorizon,
    ) -> tuple[Decimal | None, tuple[DataSufficiencyStatus, str] | None]:
        config = self.config
        inapplicable = DataSufficiencyStatus.MODEL_NOT_APPLICABLE
        if model == BaselineModel.NAIVE:
            return Decimal(sales[-1] * horizon), None
        if model == BaselineModel.MOVING_AVERAGE:
            if len(sales) < config.moving_average_days:
                return None, (inapplicable, "MOVING_AVERAGE_WINDOW_UNAVAILABLE")
            return Decimal(
                sum(sales[-config.moving_average_days :]) * horizon
            ) / config.moving_average_days, None
        if model == BaselineModel.SEASONAL_NAIVE:
            if not _supports_weekly_seasonality(sales, config):
                return None, (inapplicable, "WEEKLY_SEASONALITY_NOT_SUPPORTED")
            latest_week = sales[-7:]
            # The feature date is between the last history date and target day one.
            return Decimal(
                sum(latest_week[(step + 1) % 7] for step in range(horizon))
            ), None
        if model == BaselineModel.EXPONENTIAL_SMOOTHING:
            if (
                len(sales) < config.smoothing_minimum_days
                or _zero_fraction(sales) >= config.intermittent_zero_fraction
            ):
                return None, (inapplicable, "DENSE_SMOOTHING_HISTORY_UNAVAILABLE")
            level = Decimal(sales[0])
            for value in sales[1:]:
                level += config.smoothing_alpha * (value - level)
            return level * horizon, None
        return self._intermittent_forecast(model, sales, horizon)

    def _intermittent_forecast(
        self,
        model: BaselineModel,
        sales: tuple[int, ...],
        horizon: ForecastHorizon,
    ) -> tuple[Decimal | None, tuple[DataSufficiencyStatus, str] | None]:
        if self._stats_models is None or self._numpy is None:
            return None, (
                DataSufficiencyStatus.MODEL_UNAVAILABLE,
                "STATSFORECAST_DISABLED",
            )
        if (
            len(sales) < self.config.intermittent_minimum_days
            or sum(value > 0 for value in sales) < 2
            or _zero_fraction(sales) < self.config.intermittent_zero_fraction
        ):
            return None, (
                DataSufficiencyStatus.MODEL_NOT_APPLICABLE,
                "INTERMITTENT_HISTORY_NOT_SUPPORTED",
            )
        model_class = getattr(self._stats_models, STATSFORECAST_MODELS[model])
        estimator = (
            model_class(alpha_d=0.2, alpha_p=0.2)
            if model == BaselineModel.TSB
            else model_class()
        )
        try:
            # Forecast the skipped feature day, then retain the actual target horizon.
            forecast = estimator.forecast(
                y=self._numpy.asarray(sales, dtype="float64"), h=horizon + 1
            )["mean"]
            expected = tuple(Decimal(str(value)) for value in forecast[1:])
        except (ValueError, ArithmeticError, RuntimeError):
            return None, (
                DataSufficiencyStatus.MODEL_UNAVAILABLE,
                "STATSFORECAST_NUMERICAL_FAILURE",
            )
        if len(expected) != horizon or any(
            not value.is_finite() or value < 0 for value in expected
        ):
            return None, (
                DataSufficiencyStatus.MODEL_UNAVAILABLE,
                "STATSFORECAST_INVALID_PREDICTION",
            )
        return sum(expected, Decimal(0)), None
