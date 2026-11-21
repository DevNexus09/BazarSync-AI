"""Seller-scoped routing with an isolated, bounded native prediction process."""

from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Literal
from uuid import UUID

from app.schemas.demand_regime import DemandRegime, RegimeSelectionPolicy
from app.schemas.forecast_features import (
    FEATURE_SCHEMA_SHA256,
    FEATURE_VERSION,
    ForecastHorizon,
    ForecastSourceSnapshot,
)
from app.schemas.forecast_inference import (
    ApprovalStatus,
    ForecastInferenceResult,
    ForecastMode,
    ForecastModelManifest,
    InferenceAttempt,
    InferenceFailure,
    InferenceLimits,
    ModelSlot,
    NativeInferenceReply,
    NativeInferenceRequest,
)
from app.schemas.statistical_forecast import BaselineConfig, ForecastResult
from app.services.catboost_features import ENCODER_VERSION, MODEL_VERSION
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_artifact_store import load_registry
from app.services.forecast_backtesting_service import HORIZONS
from app.services.statistical_forecast_service import StatisticalForecastService

MAX_REQUEST = 256 * 1024
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class ForecastInferenceService:
    @classmethod
    def enabled_runtime(
        cls, seller_id: UUID, config: BaselineConfig
    ) -> "ForecastInferenceService":
        native_path = os.getenv("FORECAST_INFERENCE_PYTHON")
        native_python = Path(native_path) if native_path else None
        if native_python is not None and not native_python.is_absolute():
            raise ValueError("Inference interpreter must be an absolute path.")
        return cls(
            RegimeForecastService(
                StatisticalForecastService(
                    authorized_seller_id=seller_id, config=config
                )
            ),
            mode=ForecastMode.ENABLED,
            artifact_root=Path(os.getenv("FORECAST_ARTIFACT_ROOT", "/models")),
            registry_digest=os.getenv("FORECAST_REGISTRY_SHA256"),
            native_python=native_python,
        )

    def __init__(
        self,
        forecaster: RegimeForecastService,
        *,
        mode: ForecastMode = ForecastMode.DISABLED,
        artifact_root: Path | None = None,
        registry_digest: str | None = None,
        limits: InferenceLimits | None = None,
        native_python: Path | None = None,
    ) -> None:
        self.forecaster = forecaster
        self.seller_id = forecaster.baselines.seller_id
        self.mode = ForecastMode(mode)
        self.artifact_root = artifact_root
        self.registry_digest = registry_digest
        self.limits = limits or InferenceLimits()
        self._native_python = str(native_python) if native_python else sys.executable
        self._capacity = BoundedSemaphore(self.limits.max_concurrent)
        self._lock = Lock()
        self._counters: Counter[str] = Counter()

    def health_metrics(self) -> dict[str, int]:
        """Process-local counters without seller IDs, paths, or demand values."""
        with self._lock:
            return dict(self._counters)

    def _count(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[key] += amount

    @staticmethod
    def _eligibility(
        model: ForecastModelManifest, horizon: ForecastHorizon, origin: datetime
    ) -> InferenceFailure | None:
        if model.approval_status != ApprovalStatus.APPROVED:
            return InferenceFailure.MODEL_NOT_APPROVED
        if model.approved_at is None or model.approved_at >= origin:
            return InferenceFailure.MODEL_NOT_AVAILABLE_AT_ORIGIN
        if model.model_version != MODEL_VERSION:
            return InferenceFailure.UNSUPPORTED_VERSION
        if not any(entry.horizon_days == horizon for entry in model.artifacts):
            return InferenceFailure.UNSUPPORTED_HORIZON
        if (model.feature_version, model.feature_schema_sha256) != (
            FEATURE_VERSION,
            FEATURE_SCHEMA_SHA256,
        ) or model.encoder_version != ENCODER_VERSION:
            return InferenceFailure.FEATURE_SCHEMA_MISMATCH
        return None

    def _native(
        self, request: NativeInferenceRequest, root: Path, digest: str
    ) -> NativeInferenceReply:
        data = request.model_dump_json().encode()
        if len(data) > MAX_REQUEST:
            return NativeInferenceReply(failure=InferenceFailure.MODEL_INELIGIBLE)
        if not self._capacity.acquire(blocking=False):
            return NativeInferenceReply(failure=InferenceFailure.BUSY)
        start = monotonic()
        try:
            result = subprocess.run(
                [
                    self._native_python,
                    "-m",
                    "scripts.forecast_native_worker",
                    str(root),
                    digest,
                ],
                cwd=BACKEND_ROOT,
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.limits.timeout_seconds,
                check=True,
                env={
                    "LANG": "C.UTF-8",
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "VECLIB_MAXIMUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            return NativeInferenceReply.model_validate_json(result.stdout)
        except subprocess.TimeoutExpired:
            return NativeInferenceReply(failure=InferenceFailure.TIMEOUT)
        except (OSError, ValueError, subprocess.CalledProcessError):
            return NativeInferenceReply(failure=InferenceFailure.WORKER_FAILURE)
        finally:
            self._count("native_attempts")
            self._count("native_duration_ms_total", round((monotonic() - start) * 1000))
            self._capacity.release()

    def forecast(
        self,
        snapshot: ForecastSourceSnapshot,
        *,
        forecast_origin: datetime,
        horizon_days: ForecastHorizon,
        policy: RegimeSelectionPolicy | None = None,
        generated_at: datetime | None = None,
    ) -> ForecastInferenceResult:
        if snapshot.seller_id != self.seller_id:
            raise PermissionError("Forecast snapshot outside authorized seller scope.")
        if horizon_days not in HORIZONS:
            raise ValueError("Unsupported forecast horizon. Use 7, 14, or 30 days.")
        baseline = self.forecaster.forecast(
            snapshot,
            forecast_origin=forecast_origin,
            horizon_days=horizon_days,
            policy=policy,
            generated_at=generated_at or datetime.now(timezone.utc),
        )
        point = baseline.forecast
        if self.mode == ForecastMode.DISABLED:
            return self._fallback(point, "ML_DISABLED", baseline.evidence.regime)
        if (
            baseline.evidence.regime != DemandRegime.REGULAR
            or point.expected_units is None
        ):
            return self._fallback(
                point, "ML_REQUIRES_REGULAR_VERIFIED_HISTORY", baseline.evidence.regime
            )

        root, digest = self.artifact_root, self.registry_digest
        try:
            if root is None or digest is None:
                raise ValueError("Registry is not configured.")
            registry = load_registry(root, self.seller_id, digest)
        except (ValueError, OSError, PermissionError):
            self._count(InferenceFailure.REGISTRY_UNAVAILABLE)
            return self._fallback(
                point, "REGISTRY_UNAVAILABLE", baseline.evidence.regime
            )

        candidates: tuple[tuple[ModelSlot, ForecastModelManifest | None], ...] = (
            ("active", registry.active),
            ("previous", registry.previous),
        )
        attempts: list[InferenceAttempt] = []
        row = None
        for slot, model in candidates:
            if model is None:
                continue
            failure = self._eligibility(model, horizon_days, point.forecast_origin)
            if failure is not None:
                attempts.append(InferenceAttempt(slot=slot, failure=failure))
                self._count(f"{slot}.{failure}")
                continue
            if row is None:
                try:
                    row = self.forecaster.baselines.features.build(
                        snapshot,
                        forecast_origin=point.forecast_origin,
                        horizon_days=horizon_days,
                    )
                except ValueError:
                    failure = InferenceFailure.FEATURE_SCHEMA_MISMATCH
                    self._count(f"{slot}.{failure}")
                    attempts.append(InferenceAttempt(slot=slot, failure=failure))
                    break
            reply = self._native(
                NativeInferenceRequest(row=row, slot=slot, limits=self.limits),
                root,
                digest,
            )
            attempts.append(InferenceAttempt(slot=slot, failure=reply.failure))
            if reply.units is None:
                self._count(f"{slot}.{reply.failure}")
                continue
            self._count(f"{slot}.success")
            ml = ForecastResult.model_validate(
                point.model_dump()
                | {
                    "expected_units": reply.units,
                    "model_name": model.model_name,
                    "model_version": f"{model.model_version}@{model.release}",
                    "fallback_reason": "ACTIVE_MODEL_UNAVAILABLE"
                    if slot == "previous"
                    else None,
                    "prediction_interval": None,
                }
            )
            if self.mode == ForecastMode.SHADOW:
                self._count("shadow_success")
                return ForecastInferenceResult(
                    mode=self.mode,
                    forecast=point,
                    source="baseline",
                    shadow_forecast=ml,
                    shadow_source=slot,
                    attempts=tuple(attempts),
                    selection_reason="SHADOW_BASELINE_AUTHORITATIVE",
                    demand_regime=baseline.evidence.regime,
                )
            return ForecastInferenceResult(
                mode=self.mode,
                forecast=ml,
                source=slot,
                attempts=tuple(attempts),
                selection_reason="APPROVED_MODEL",
                demand_regime=baseline.evidence.regime,
                lead_time_calibration=next(
                    (
                        calibration
                        for artifact in model.artifacts
                        if artifact.horizon_days == horizon_days
                        for calibration in artifact.reorder_calibrations
                        if calibration.product_id == point.product_id
                    ),
                    None,
                ),
            )
        return self._fallback(
            point, "NO_USABLE_APPROVED_MODEL", baseline.evidence.regime, tuple(attempts)
        )

    def _fallback(
        self,
        point: ForecastResult,
        reason: str,
        regime: DemandRegime,
        attempts: tuple[InferenceAttempt, ...] = (),
    ) -> ForecastInferenceResult:
        source: Literal["baseline", "insufficient_data"] = (
            "insufficient_data" if point.expected_units is None else "baseline"
        )
        self._count(source)
        return ForecastInferenceResult(
            mode=self.mode,
            forecast=point,
            source=source,
            attempts=attempts,
            selection_reason=reason,
            demand_regime=regime,
        )
