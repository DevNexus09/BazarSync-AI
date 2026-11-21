from datetime import timedelta
from hashlib import sha256
import subprocess
import sys
from uuid import UUID

import pytest

from app.schemas.forecast_features import FEATURE_SCHEMA_SHA256, FEATURE_VERSION
from app.schemas.forecast_inference import (
    ApprovalStatus,
    ForecastInferenceResult,
    ForecastMode,
    ForecastModelManifest,
    ForecastModelRegistry,
    HorizonArtifact,
    HoldoutMetrics,
    InferenceFailure,
    InferenceLimits,
)
from app.schemas.statistical_forecast import ForecastResult
from app.services.catboost_features import (
    ENCODER_VERSION,
    MODEL_VERSION,
    flatten_feature_row,
)
from app.services.demand_regime_service import RegimeForecastService
from app.services.forecast_artifact_store import load_registry, verified_file
from app.services.forecast_inference_service import ForecastInferenceService
from app.services.historical_dataset_service import _opening
from app.services.statistical_forecast_service import StatisticalForecastService
from scripts.forecast_native_worker import apply_limits, runtime_dependencies
from test_statistical_forecast import DATE, SELLER, origin_case


@pytest.fixture
def case():
    return origin_case((5,) * 35)


@pytest.fixture
def forecaster():
    return RegimeForecastService(
        StatisticalForecastService(authorized_seller_id=SELLER)
    )


def manifest(release, digest, *, horizon=7, **updates):
    fields = dict(
        release=release,
        seller_id=SELLER,
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        feature_schema_sha256=FEATURE_SCHEMA_SHA256,
        encoder_version=ENCODER_VERSION,
        lineage_sha256="b" * 64,
        dependencies={},
        approval_status=ApprovalStatus.APPROVED,
        approved_at=_opening(DATE - timedelta(days=1)),
        trained_at=_opening(DATE - timedelta(days=151)),
        training_data_cutoff=_opening(DATE - timedelta(days=152)),
        artifacts=(
            HorizonArtifact(
                horizon_days=horizon,
                artifact_sha256=digest,
                validation=HoldoutMetrics(
                    scope="historical_holdout",
                    start_date=DATE - timedelta(days=150),
                    end_date=DATE - timedelta(days=40),
                    outcome_cutoff=_opening(DATE - timedelta(days=2)),
                    matched_rows=8,
                    nonoverlapping_origin_dates=3,
                    mae=1,
                    baseline_mae=2,
                ),
            ),
        ),
    )
    return ForecastModelManifest.model_validate(fields | updates)


def write_registry(root, *, active=None, previous=None):
    directory = root / str(SELLER)
    directory.mkdir(exist_ok=True)
    payload = (
        ForecastModelRegistry(seller_id=SELLER, active=active, previous=previous)
        .model_dump_json()
        .encode()
    )
    (directory / "registry.json").write_bytes(payload)
    return sha256(payload).hexdigest()


def forecast(service, case, *, horizon=7):
    return service.forecast(
        case.snapshot,
        forecast_origin=case.forecast_origin,
        horizon_days=horizon,
        generated_at=case.forecast_origin,
    )


def service_for(forecaster, root, digest, *, mode=ForecastMode.ENABLED, **options):
    return ForecastInferenceService(
        forecaster,
        mode=mode,
        artifact_root=root,
        registry_digest=digest,
        limits=InferenceLimits(**options),
    )


@pytest.fixture(scope="module")
def real_cmb(tmp_path_factory):
    catboost = pytest.importorskip("catboost")
    from app.services.forecast_feature_builder import ForecastFeatureBuilder

    case = origin_case((5,) * 35)
    row = ForecastFeatureBuilder(authorized_seller_id=SELLER).build(
        case.snapshot, forecast_origin=case.forecast_origin, horizon_days=7
    )
    record = flatten_feature_row(row)
    data = [
        [
            (value + i if name == "sales_lag_1d" else value)
            for name, value in record.items()
        ]
        for i in range(4)
    ]
    categories = [
        i for i, value in enumerate(record.values()) if isinstance(value, str)
    ]
    pool = catboost.Pool(
        data,
        label=[3, 4, 7, 9],
        cat_features=categories,
        feature_names=list(record),
        thread_count=1,
    )
    model = catboost.CatBoostRegressor(
        iterations=3, depth=2, thread_count=1, allow_writing_files=False, verbose=False
    )
    model.fit(pool)
    path = tmp_path_factory.mktemp("native") / "fixture.cbm"
    model.save_model(path)
    return path.read_bytes()


def install(root, release, data):
    directory = root / str(SELLER) / release
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "catboost-horizon-7.cbm"
    path.write_bytes(data)
    return path


def test_artifact_load_shadow_and_repeated_consistency(
    tmp_path, forecaster, case, real_cmb
):
    active = manifest(
        "release-2", sha256(real_cmb).hexdigest(), dependencies=runtime_dependencies()
    )
    install(tmp_path, active.release, real_cmb)
    digest = write_registry(tmp_path, active=active)
    service = service_for(forecaster, tmp_path, digest)
    first = forecast(service, case)
    assert first.source == "active", first.attempts
    assert (
        first.forecast.model_name == "catboost"
        and first.forecast.model_version.endswith("@release-2")
    )
    assert (
        ForecastResult.model_validate_json(first.forecast.model_dump_json())
        == first.forecast
    )
    assert forecast(service, case) == first
    assert service.health_metrics()["active.success"] == 2
    shadow = forecast(
        service_for(forecaster, tmp_path, digest, mode=ForecastMode.SHADOW), case
    )
    assert shadow.source == "baseline" and shadow.forecast.expected_units == 35
    assert shadow.shadow_forecast == first.forecast and shadow.shadow_source == "active"


def test_corrupt_active_previous_then_missing_fallback(
    tmp_path, forecaster, case, real_cmb
):
    digest = sha256(real_cmb).hexdigest()
    active = manifest("release-2", digest, dependencies=runtime_dependencies())
    previous = manifest("release-1", digest, dependencies=runtime_dependencies())
    install(tmp_path, active.release, b"damaged")
    prev_path = install(tmp_path, previous.release, real_cmb)
    service = service_for(
        forecaster, tmp_path, write_registry(tmp_path, active=active, previous=previous)
    )
    result = forecast(service, case)
    assert result.source == "previous"
    assert [attempt.failure for attempt in result.attempts] == [
        InferenceFailure.ARTIFACT_REJECTED,
        None,
    ]
    assert result.forecast.fallback_reason == "ACTIVE_MODEL_UNAVAILABLE"
    prev_path.unlink()
    result = forecast(service, case)
    assert result.source == "baseline" and result.forecast.expected_units == 35
    assert result.attempts[-1].failure == InferenceFailure.ARTIFACT_MISSING


@pytest.mark.parametrize(
    ("changes", "failure"),
    [
        ({"feature_schema_sha256": "a" * 64}, InferenceFailure.FEATURE_SCHEMA_MISMATCH),
        ({"encoder_version": "different"}, InferenceFailure.FEATURE_SCHEMA_MISMATCH),
        ({"model_version": "unknown"}, InferenceFailure.UNSUPPORTED_VERSION),
        ({"horizon": 14}, InferenceFailure.UNSUPPORTED_HORIZON),
        (
            {"approval_status": ApprovalStatus.REVOKED},
            InferenceFailure.MODEL_NOT_APPROVED,
        ),
        (
            {"approved_at": _opening(DATE + timedelta(days=1))},
            InferenceFailure.MODEL_NOT_AVAILABLE_AT_ORIGIN,
        ),
    ],
)
def test_unsupported_manifests_use_baseline(
    tmp_path, forecaster, case, changes, failure
):
    approved = manifest("version-1", "c" * 64, **changes)
    service = service_for(
        forecaster, tmp_path, write_registry(tmp_path, active=approved)
    )
    result = forecast(service, case)
    assert result.source == "baseline" and result.attempts[0].failure == failure
    assert "native_attempts" not in service.health_metrics()


def test_disabled_default_sparse_and_foreign_inputs(forecaster, case):
    service = ForecastInferenceService(forecaster)
    assert forecast(service, case).selection_reason == "ML_DISABLED"
    enabled = ForecastInferenceService(forecaster, mode=ForecastMode.ENABLED)
    assert (
        forecast(enabled, origin_case((None,) * 3, age=3)).source == "insufficient_data"
    )
    sparse = forecast(enabled, origin_case((0,) * 29 + (3,)))
    assert sparse.source == "baseline" and not sparse.attempts
    with pytest.raises(ValueError, match="horizon"):
        forecast(service, case, horizon=21)
    with pytest.raises(PermissionError):
        enabled.forecast(
            case.snapshot.model_copy(update={"seller_id": UUID(int=999)}),
            forecast_origin=case.forecast_origin,
            horizon_days=7,
        )


def test_registry_integrity_and_symlink(tmp_path, forecaster, case):
    digest = write_registry(tmp_path, active=manifest("fixture", "f" * 64))
    directory = tmp_path / str(SELLER)
    path = directory / "registry.json"
    moved = directory / "alias.json"
    path.rename(moved)
    path.symlink_to(moved)
    assert (
        forecast(service_for(forecaster, tmp_path, digest), case).selection_reason
        == "REGISTRY_UNAVAILABLE"
    )
    path.unlink()
    path.write_bytes(moved.read_bytes() + b" ")
    assert (
        forecast(service_for(forecaster, tmp_path, digest), case).selection_reason
        == "REGISTRY_UNAVAILABLE"
    )
    path.write_bytes(
        ForecastModelRegistry(seller_id=UUID(int=999)).model_dump_json().encode()
    )
    with pytest.raises(PermissionError):
        load_registry(tmp_path, SELLER, sha256(path.read_bytes()).hexdigest())


def test_artifact_store_rejects_symlink_components_and_oversize(tmp_path):
    content = b"0123456789"
    path = install(tmp_path, "actual", content)
    digest = sha256(content).hexdigest()
    components = (str(SELLER), "actual", path.name)
    assert verified_file(tmp_path, components, digest, 10) == content
    with pytest.raises(ValueError, match="size"):
        verified_file(tmp_path, components, digest, 9)
    (tmp_path / str(SELLER) / "alias").symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(OSError):
        verified_file(tmp_path, (str(SELLER), "alias", path.name), digest, 10)


def test_worker_rejects_dependency_mismatch(tmp_path, forecaster, case):
    pytest.importorskip("catboost")
    active = manifest(
        "fixture", "a" * 64, dependencies=runtime_dependencies() | {"python": "0.0.0"}
    )
    service = service_for(forecaster, tmp_path, write_registry(tmp_path, active=active))
    result = forecast(service, case)
    assert (
        result.source == "baseline"
        and result.attempts[0].failure == InferenceFailure.DEPENDENCY_MISMATCH
    )


def test_process_timeout_and_capacity(tmp_path, forecaster, case, monkeypatch):
    digest = write_registry(tmp_path, active=manifest("fixture", "f" * 64))
    service = service_for(forecaster, tmp_path, digest, timeout_seconds=0.05)
    actual_run = subprocess.run

    def stalled(_args, **kwargs):
        return actual_run(
            [sys.executable, "-c", "import time; time.sleep(10)"], **kwargs
        )

    monkeypatch.setattr(subprocess, "run", stalled)
    result = forecast(service, case)
    assert (
        result.source == "baseline"
        and result.attempts[0].failure == InferenceFailure.TIMEOUT
    )
    assert service.health_metrics()["active.timeout"] == 1
    assert service._capacity.acquire(blocking=False)
    try:
        assert forecast(service, case).attempts[0].failure == InferenceFailure.BUSY
    finally:
        service._capacity.release()


def test_native_limits_do_not_raise_kernel_hard_caps(monkeypatch):
    import resource

    calls = {}
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        resource,
        "getrlimit",
        lambda kind: (
            (3, 3)
            if kind == resource.RLIMIT_CPU
            else (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
        ),
    )
    monkeypatch.setattr(
        resource, "setrlimit", lambda kind, values: calls.update({kind: values})
    )
    apply_limits(InferenceLimits(cpu_seconds=4, address_space_mib=768))
    assert calls[resource.RLIMIT_CPU] == (3, 3)
    assert calls[resource.RLIMIT_AS] == (768 * 1024**2,) * 2
    assert calls[resource.RLIMIT_CORE] == (0, 0)


def test_unqualified_holdout_cannot_be_approved():
    valid = manifest("fixture", "f" * 64)
    artifact = valid.artifacts[0]
    for metrics in (
        {"scope": "synthetic"},
        {"mae": 4},
        {"start_date": DATE - timedelta(days=160)},
        {"start_date": DATE - timedelta(days=45)},
        {"nonoverlapping_origin_dates": 1},
    ):
        with pytest.raises(ValueError, match="historical holdout"):
            ForecastModelManifest.model_validate(
                valid.model_dump()
                | {
                    "artifacts": [
                        artifact.model_dump()
                        | {"validation": artifact.validation.model_dump() | metrics}
                    ]
                }
            )


def test_offline_entrypoints_do_not_require_app_settings():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scripts.infer_forecast, scripts.forecast_native_worker, sys; "
            "assert 'app.core.config' not in sys.modules",
        ],
        env={"PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_cli_default_path_without_registry(tmp_path, case, monkeypatch, capsys):
    import json
    from scripts.infer_forecast import main

    source = tmp_path / "snapshot.json"
    source.write_text(case.snapshot.model_dump_json())
    monkeypatch.delenv("FORECAST_ML_MODE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "infer",
            "--seller-id",
            str(SELLER),
            "--snapshot",
            str(source),
            "--origin",
            case.forecast_origin.isoformat(),
            "--horizon",
            "7",
        ],
    )
    main()
    response = json.loads(capsys.readouterr().out)
    assert (
        ForecastInferenceResult.model_validate(response["result"]).source == "baseline"
    )
    assert response["health"] == {"baseline": 1}
