"""Isolated one-shot CatBoost prediction. Invoked by ForecastInferenceService."""

from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
import math
from pathlib import Path
import platform
import resource
import sys
from tempfile import TemporaryDirectory

from app.schemas.forecast_features import FEATURE_SCHEMA_SHA256, FEATURE_VERSION
from app.schemas.forecast_inference import (
    ApprovalStatus,
    InferenceFailure,
    InferenceLimits,
    NativeInferenceReply,
    NativeInferenceRequest,
)
from app.services.catboost_features import (
    CATBOOST_VERSION,
    ENCODER_VERSION,
    MODEL_VERSION,
    flatten_feature_row,
)
from app.services.forecast_artifact_store import MIB, load_registry, verified_file

MAX_REQUEST = 256 * 1024
PACKAGES = ("catboost", "numpy", "pandas", "scipy", "pydantic")


def runtime_dependencies() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in PACKAGES},
    }


def apply_limits(limits: InferenceLimits) -> None:
    def cap(kind: int, requested: int) -> None:
        _, hard = resource.getrlimit(kind)
        effective = (
            min(hard, requested) if hard != resource.RLIM_INFINITY else requested
        )
        resource.setrlimit(kind, (effective, effective))

    cap(resource.RLIMIT_CPU, limits.cpu_seconds)
    cap(resource.RLIMIT_CORE, 0)
    if sys.platform == "linux":
        cap(resource.RLIMIT_AS, limits.address_space_mib * MIB)


def predict(
    request: NativeInferenceRequest, root: Path, registry_digest: str
) -> NativeInferenceReply:
    row = request.row
    try:
        registry = load_registry(root, row.seller_id, registry_digest)
    except (OSError, ValueError, PermissionError):
        return NativeInferenceReply(failure=InferenceFailure.REGISTRY_UNAVAILABLE)
    model = registry.active if request.slot == "active" else registry.previous
    if model is None:
        return NativeInferenceReply(failure=InferenceFailure.MODEL_NOT_APPROVED)
    artifact = next(
        (entry for entry in model.artifacts if entry.horizon_days == row.horizon_days),
        None,
    )
    if (
        model.seller_id != row.seller_id
        or model.approval_status != ApprovalStatus.APPROVED
    ):
        return NativeInferenceReply(failure=InferenceFailure.MODEL_NOT_APPROVED)
    if model.approved_at is None or model.approved_at >= row.forecast_origin:
        return NativeInferenceReply(
            failure=InferenceFailure.MODEL_NOT_AVAILABLE_AT_ORIGIN
        )
    if model.model_version != MODEL_VERSION:
        return NativeInferenceReply(failure=InferenceFailure.UNSUPPORTED_VERSION)
    if artifact is None:
        return NativeInferenceReply(failure=InferenceFailure.UNSUPPORTED_HORIZON)
    if (model.feature_version, model.feature_schema_sha256) != (
        FEATURE_VERSION,
        FEATURE_SCHEMA_SHA256,
    ) or model.encoder_version != ENCODER_VERSION:
        return NativeInferenceReply(failure=InferenceFailure.FEATURE_SCHEMA_MISMATCH)
    try:
        dependencies = runtime_dependencies()
    except PackageNotFoundError:
        return NativeInferenceReply(failure=InferenceFailure.DEPENDENCY_MISMATCH)
    if (
        platform.python_implementation() != "CPython"
        or sys.version_info[:2] != (3, 14)
        or dependencies["catboost"] != CATBOOST_VERSION
        or dependencies != model.dependencies
    ):
        return NativeInferenceReply(failure=InferenceFailure.DEPENDENCY_MISMATCH)
    if not row.quality.sufficient_history:
        return NativeInferenceReply(failure=InferenceFailure.MODEL_INELIGIBLE)
    try:
        record = flatten_feature_row(row)
    except ValueError:
        return NativeInferenceReply(failure=InferenceFailure.FEATURE_SCHEMA_MISMATCH)
    try:
        data = verified_file(
            root,
            (
                str(model.seller_id),
                model.release,
                f"catboost-horizon-{row.horizon_days}.cbm",
            ),
            artifact.artifact_sha256,
            request.limits.artifact_mib * MIB,
        )
    except FileNotFoundError:
        return NativeInferenceReply(failure=InferenceFailure.ARTIFACT_MISSING)
    except (OSError, ValueError):
        return NativeInferenceReply(failure=InferenceFailure.ARTIFACT_REJECTED)

    from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

    with TemporaryDirectory(prefix="forecast-model-") as temporary:
        path = Path(temporary) / "verified.cbm"
        path.write_bytes(data)
        estimator = CatBoostRegressor()
        estimator.load_model(path, format="cbm")
    categoricals = [
        index for index, value in enumerate(record.values()) if isinstance(value, str)
    ]
    if (
        list(record) != estimator.feature_names_
        or categoricals != estimator.get_cat_feature_indices()
    ):
        return NativeInferenceReply(failure=InferenceFailure.FEATURE_SCHEMA_MISMATCH)
    pool = Pool(
        [list(record.values())],
        feature_names=list(record),
        cat_features=categoricals,
        thread_count=1,
    )
    value = float(estimator.predict(pool, thread_count=1, task_type="CPU")[0])
    if not math.isfinite(value) or value < 0:
        return NativeInferenceReply(failure=InferenceFailure.WORKER_FAILURE)
    return NativeInferenceReply(units=Decimal(str(value)))


def main() -> None:
    try:
        request = NativeInferenceRequest.model_validate_json(
            sys.stdin.buffer.read(MAX_REQUEST + 1)
        )
        apply_limits(request.limits)
        reply = predict(request, Path(sys.argv[1]), sys.argv[2])
    except Exception:
        # Native crashes are handled by the parent process exit path as well.
        reply = NativeInferenceReply(failure=InferenceFailure.WORKER_FAILURE)
    print(reply.model_dump_json())


if __name__ == "__main__":
    main()
