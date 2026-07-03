from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import exp, log
from statistics import mean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.demand_elasticity_estimate import DemandElasticityEstimate, DemandEstimateDataStatus, DemandEstimationMethod
from app.models.product import Product
from app.models.sales_record import SalesRecord, SalesRecordStatus

VALID_DEMAND_STATUSES = {SalesRecordStatus.COMPLETED, SalesRecordStatus.FULFILLED}


@dataclass(frozen=True)
class DemandResponseConfig:
    min_observations: int
    min_price_variation_rate: Decimal
    min_coverage_days: int
    max_data_age_days: int
    zero_unit_adjustment: Decimal
    min_elasticity: Decimal
    max_elasticity: Decimal
    conservative_elasticity_prior: Decimal
    allow_heuristic_fallback: bool
    max_forecast_multiplier: Decimal
    calculation_version: str

    @classmethod
    def from_settings(cls) -> "DemandResponseConfig":
        return cls(
            min_observations=settings.demand_response_min_observations,
            min_price_variation_rate=Decimal(str(settings.demand_response_min_price_variation_rate)),
            min_coverage_days=settings.demand_response_min_coverage_days,
            max_data_age_days=settings.demand_response_max_data_age_days,
            zero_unit_adjustment=Decimal(str(settings.demand_response_zero_unit_adjustment)),
            min_elasticity=Decimal(str(settings.demand_response_min_elasticity)),
            max_elasticity=Decimal(str(settings.demand_response_max_elasticity)),
            conservative_elasticity_prior=Decimal(str(settings.demand_response_conservative_elasticity_prior)),
            allow_heuristic_fallback=settings.demand_response_allow_heuristic_fallback,
            max_forecast_multiplier=Decimal(str(settings.demand_response_max_forecast_multiplier)),
            calculation_version=settings.demand_response_formula_version,
        )


@dataclass(frozen=True)
class DemandObservation:
    seller_id: UUID
    product_id: UUID
    observed_date: date
    price: Decimal
    units_sold: int
    returned_units: int = 0
    refunded_restocked_units: int = 0
    status: SalesRecordStatus = SalesRecordStatus.COMPLETED
    is_test_order: bool = False
    promotion_active: bool = False
    source_reference: str | None = None

    @property
    def net_units(self) -> int:
        return max(0, self.units_sold - self.returned_units - self.refunded_restocked_units)


@dataclass(frozen=True)
class DemandElasticityResult:
    method: DemandEstimationMethod
    elasticity: Decimal | None
    sample_count: int
    baseline_units: Decimal | None
    observation_start: date | None
    observation_end: date | None
    price_range: tuple[Decimal, Decimal] | None
    quality_metrics: dict[str, object]
    confidence: Decimal
    data_status: DemandEstimateDataStatus
    calculation_version: str
    evidence: dict[str, object]


@dataclass(frozen=True)
class CandidateUnitForecast:
    method: DemandEstimationMethod
    current_price: Decimal
    candidate_price: Decimal
    lower_estimate: Decimal | None
    central_estimate: Decimal | None
    upper_estimate: Decimal | None
    forecast_horizon_days: int
    baseline_period: dict[str, object]
    confidence: Decimal
    assumptions: dict[str, object]
    elasticity: Decimal | None
    data_status: DemandEstimateDataStatus
    calculation_version: str


class DemandResponseService:
    def __init__(self, db: Session | None = None, *, config: DemandResponseConfig | None = None) -> None:
        self._db = db
        self._config = config or DemandResponseConfig.from_settings()

    def estimate_from_observations(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        observations: list[DemandObservation],
        as_of_date: date,
    ) -> DemandElasticityResult:
        clean, rejected = self._clean_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=observations,
            as_of_date=as_of_date,
        )
        eligibility = self._eligibility(clean, rejected, as_of_date)
        if eligibility:
            return self._fallback_or_insufficient(
                clean=clean,
                rejected=rejected,
                reasons=eligibility,
            )
        return self._historical_estimate(clean=clean, rejected=rejected)

    def forecast_candidate_units(
        self,
        *,
        current_price: Decimal,
        candidate_price: Decimal,
        baseline_units: Decimal,
        forecast_horizon_days: int,
        baseline_period: dict[str, object],
        estimate: DemandElasticityResult,
    ) -> CandidateUnitForecast:
        current = Decimal(str(current_price))
        candidate = Decimal(str(candidate_price))
        baseline = Decimal(str(baseline_units))
        assumptions = dict(estimate.evidence)
        if current <= 0 or candidate <= 0 or estimate.elasticity is None or baseline < 0:
            return CandidateUnitForecast(
                method=DemandEstimationMethod.INSUFFICIENT_DATA,
                current_price=current,
                candidate_price=candidate,
                lower_estimate=None,
                central_estimate=None,
                upper_estimate=None,
                forecast_horizon_days=forecast_horizon_days,
                baseline_period=baseline_period,
                confidence=Decimal("0.00"),
                assumptions={"reason": "missing_positive_price_or_elasticity"},
                elasticity=None,
                data_status=DemandEstimateDataStatus.INSUFFICIENT,
                calculation_version=self._config.calculation_version,
            )
        ratio = candidate / current
        central = baseline * Decimal(str(exp(float(estimate.elasticity) * log(float(ratio)))))
        cap = baseline * self._config.max_forecast_multiplier
        central = min(max(Decimal("0"), central), cap)
        uncertainty = Decimal("0.35") if estimate.method == DemandEstimationMethod.HISTORICAL_ELASTICITY else Decimal("0.60")
        lower = max(Decimal("0"), central * (Decimal("1") - uncertainty))
        upper = min(cap, central * (Decimal("1") + uncertainty))
        assumptions["forecast_cap"] = str(cap.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        assumptions["uncertainty_band"] = str(uncertainty)
        return CandidateUnitForecast(
            method=estimate.method,
            current_price=current,
            candidate_price=candidate,
            lower_estimate=_q4(lower),
            central_estimate=_q4(central),
            upper_estimate=_q4(upper),
            forecast_horizon_days=forecast_horizon_days,
            baseline_period=baseline_period,
            confidence=estimate.confidence,
            assumptions=assumptions,
            elasticity=estimate.elasticity,
            data_status=estimate.data_status,
            calculation_version=estimate.calculation_version,
        )

    def estimate_for_product(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        as_of_date: date,
    ) -> DemandElasticityResult:
        if self._db is None:
            raise ValueError("A database session is required for product estimation.")
        product = self._db.execute(
            select(Product).where(Product.seller_id == seller_id, Product.id == product_id)
        ).scalar_one_or_none()
        if product is None:
            return self._fallback_or_insufficient(clean=[], rejected=[], reasons=["product_not_found"])
        observations = self._load_observations_from_sales_records(
            seller_id=seller_id,
            product_id=product_id,
            as_of_date=as_of_date,
        )
        return self.estimate_from_observations(
            seller_id=seller_id,
            product_id=product_id,
            observations=observations,
            as_of_date=as_of_date,
        )

    def persist_estimate(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        estimate: DemandElasticityResult,
        calculated_at: datetime | None = None,
    ) -> DemandElasticityEstimate:
        if self._db is None:
            raise ValueError("A database session is required to persist demand estimates.")
        record = DemandElasticityEstimate(
            seller_id=seller_id,
            product_id=product_id,
            estimation_method=estimate.method,
            elasticity=estimate.elasticity,
            sample_count=estimate.sample_count,
            baseline_units=estimate.baseline_units,
            observation_start=estimate.observation_start,
            observation_end=estimate.observation_end,
            quality_metrics=estimate.quality_metrics,
            confidence=estimate.confidence,
            data_status=estimate.data_status,
            calculation_version=estimate.calculation_version,
            calculated_at=calculated_at or datetime.now(timezone.utc),
        )
        self._db.add(record)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self._db.execute(
                select(DemandElasticityEstimate).where(
                    DemandElasticityEstimate.seller_id == seller_id,
                    DemandElasticityEstimate.product_id == product_id,
                    DemandElasticityEstimate.observation_end == estimate.observation_end,
                    DemandElasticityEstimate.calculation_version == estimate.calculation_version,
                )
            ).scalar_one_or_none()
            if existing:
                return existing
            raise
        self._db.refresh(record)
        return record

    def _load_observations_from_sales_records(self, *, seller_id: UUID, product_id: UUID, as_of_date: date) -> list[DemandObservation]:
        window_start = datetime.combine(as_of_date - timedelta(days=self._config.max_data_age_days), datetime.min.time(), tzinfo=timezone.utc)
        window_end = datetime.combine(as_of_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        rows = self._db.execute(
            select(SalesRecord).where(
                SalesRecord.seller_id == seller_id,
                SalesRecord.product_id == product_id,
                SalesRecord.sold_at >= window_start,
                SalesRecord.sold_at < window_end,
            )
        ).scalars().all()
        # Current sales_records do not store transaction price, so these rows cannot
        # support historical elasticity until order-price data is added.
        return [
            DemandObservation(
                seller_id=row.seller_id,
                product_id=row.product_id,
                observed_date=row.sold_at.date(),
                price=Decimal("0"),
                units_sold=row.quantity_sold,
                returned_units=row.returned_units,
                refunded_restocked_units=row.refunded_restocked_units,
                status=row.status,
                is_test_order=row.is_test_order,
                source_reference=row.source_reference,
            )
            for row in rows
        ]

    def _clean_observations(
        self,
        *,
        seller_id: UUID,
        product_id: UUID,
        observations: list[DemandObservation],
        as_of_date: date,
    ) -> tuple[list[DemandObservation], list[dict[str, object]]]:
        clean: list[DemandObservation] = []
        rejected: list[dict[str, object]] = []
        seen: set[tuple[date, Decimal, str | None]] = set()
        for obs in observations:
            reason = None
            if obs.seller_id != seller_id or obs.product_id != product_id:
                reason = "seller_or_product_mismatch"
            elif obs.observed_date > as_of_date:
                reason = "future_observation_excluded"
            elif obs.status not in VALID_DEMAND_STATUSES or obs.is_test_order:
                reason = "invalid_order_status"
            elif obs.price <= 0:
                reason = "missing_or_invalid_price"
            elif obs.units_sold < 0 or obs.returned_units < 0 or obs.refunded_restocked_units < 0:
                reason = "invalid_units"
            elif obs.promotion_active:
                reason = "promotion_distortion"
            elif (obs.observed_date, obs.price, obs.source_reference) in seen:
                reason = "duplicate_observation"
            if reason:
                rejected.append({"date": obs.observed_date.isoformat(), "reason": reason})
                continue
            seen.add((obs.observed_date, obs.price, obs.source_reference))
            clean.append(obs)
        clean.sort(key=lambda item: (item.observed_date, item.price, item.source_reference or ""))
        return clean, rejected

    def _eligibility(self, clean: list[DemandObservation], rejected: list[dict[str, object]], as_of_date: date) -> list[str]:
        reasons: list[str] = []
        if len(clean) < self._config.min_observations:
            reasons.append("insufficient_observations")
        if clean:
            prices = [obs.price for obs in clean]
            min_price = min(prices)
            max_price = max(prices)
            if min_price <= 0 or ((max_price - min_price) / min_price) < self._config.min_price_variation_rate:
                reasons.append("insufficient_price_variation")
            coverage = (max(obs.observed_date for obs in clean) - min(obs.observed_date for obs in clean)).days + 1
            if coverage < self._config.min_coverage_days:
                reasons.append("insufficient_date_coverage")
            if (as_of_date - max(obs.observed_date for obs in clean)).days > self._config.max_data_age_days:
                reasons.append("stale_observations")
        if any(item["reason"] == "promotion_distortion" for item in rejected):
            reasons.append("promotion_distortion")
        return reasons

    def _historical_estimate(self, *, clean: list[DemandObservation], rejected: list[dict[str, object]]) -> DemandElasticityResult:
        xs = [log(float(obs.price)) for obs in clean]
        ys = [log(float(Decimal(obs.net_units) + self._config.zero_unit_adjustment)) for obs in clean]
        x_mean = mean(xs)
        y_mean = mean(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator == 0:
            return self._fallback_or_insufficient(clean=clean, rejected=rejected, reasons=["insufficient_price_variation"])
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
        intercept = y_mean - slope * x_mean
        residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
        sse = sum(residual ** 2 for residual in residuals)
        sst = sum((y - y_mean) ** 2 for y in ys)
        r_squared = 1 - (sse / sst) if sst else 0.0
        raw_elasticity = Decimal(str(slope))
        elasticity = max(self._config.min_elasticity, min(self._config.max_elasticity, raw_elasticity))
        clamped = elasticity != raw_elasticity
        prices = [obs.price for obs in clean]
        confidence = min(Decimal("90"), Decimal("45") + Decimal(len(clean) * 4) + Decimal(str(max(0.0, r_squared))) * Decimal("25"))
        return DemandElasticityResult(
            method=DemandEstimationMethod.HISTORICAL_ELASTICITY,
            elasticity=_q6(elasticity),
            sample_count=len(clean),
            baseline_units=_q4(Decimal(sum(obs.net_units for obs in clean)) / Decimal(len(clean))),
            observation_start=min(obs.observed_date for obs in clean),
            observation_end=max(obs.observed_date for obs in clean),
            price_range=(_money(min(prices)), _money(max(prices))),
            quality_metrics={
                "r_squared": round(r_squared, 4),
                "mean_absolute_log_residual": round(mean(abs(residual) for residual in residuals), 4),
                "intercept": round(intercept, 6),
                "raw_elasticity": str(_q6(raw_elasticity)),
                "elasticity_clamped": clamped,
                "zero_unit_transformation": f"ln(units + {self._config.zero_unit_adjustment})",
                "rejected_observations": rejected,
            },
            confidence=_score(confidence),
            data_status=DemandEstimateDataStatus.SUFFICIENT,
            calculation_version=self._config.calculation_version,
            evidence={"formula": "ln(units + adjustment) = intercept + elasticity * ln(price)", "controls": []},
        )

    def _fallback_or_insufficient(self, *, clean: list[DemandObservation], rejected: list[dict[str, object]], reasons: list[str]) -> DemandElasticityResult:
        if self._config.allow_heuristic_fallback:
            baseline = None
            if clean:
                baseline = _q4(Decimal(sum(obs.net_units for obs in clean)) / Decimal(len(clean)))
            return DemandElasticityResult(
                method=DemandEstimationMethod.CONSERVATIVE_HEURISTIC,
                elasticity=_q6(self._config.conservative_elasticity_prior),
                sample_count=len(clean),
                baseline_units=baseline,
                observation_start=min((obs.observed_date for obs in clean), default=None),
                observation_end=max((obs.observed_date for obs in clean), default=None),
                price_range=None if not clean else (_money(min(obs.price for obs in clean)), _money(max(obs.price for obs in clean))),
                quality_metrics={"eligibility_failures": reasons, "rejected_observations": rejected},
                confidence=Decimal("35.00"),
                data_status=DemandEstimateDataStatus.LIMITED,
                calculation_version=self._config.calculation_version,
                evidence={
                    "assumed_elasticity": str(_q6(self._config.conservative_elasticity_prior)),
                    "not_learned_from_seller_data": True,
                },
            )
        return DemandElasticityResult(
            method=DemandEstimationMethod.INSUFFICIENT_DATA,
            elasticity=None,
            sample_count=len(clean),
            baseline_units=None,
            observation_start=min((obs.observed_date for obs in clean), default=None),
            observation_end=max((obs.observed_date for obs in clean), default=None),
            price_range=None,
            quality_metrics={"eligibility_failures": reasons, "rejected_observations": rejected},
            confidence=Decimal("0.00"),
            data_status=DemandEstimateDataStatus.INSUFFICIENT,
            calculation_version=self._config.calculation_version,
            evidence={"missing_required_evidence": reasons},
        )


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q4(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _q6(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _score(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("100"), value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
