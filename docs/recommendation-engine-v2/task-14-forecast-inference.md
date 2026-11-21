# Task 14 · Versioned forecast inference

`ForecastInferenceService` returns the existing `ForecastResult` inside an internal routing envelope. The envelope includes the selected source, attempts, and an optional shadow result. It uses the Task 9 feature builder and Task 12 statistical fallback. Successful native predictions carry the Task 11 algorithm version plus the immutable release ID, for example `catboost-demand-v1@release-20261116`. This preserves model identity when consumers use the Task 13 interval calibrator.

| Mode | Result |
| --- | --- |
| `disabled` (default) | Statistical forecast or explicit insufficient data. The service skips registry and model loading. |
| `shadow` | Statistical forecast remains authoritative. A successful model forecast is returned separately for the offline caller. |
| `enabled` | Active approved release, previous approved release, then statistical forecast or explicit insufficient data. |

The CatBoost path requires regular demand with usable verified history. Intermittent, declining, and cold-start products retain the Task 12 result. The current recommendation API, decision engine, and general Celery configuration continue on their existing paths. The mode is configured only for this independent process.

## Deployment and artifact trust

Use the dedicated opt-in Compose file and inference image. The image uses the pinned Python 3.14.4 CPU environment and the same dependency lock as Task 11. It runs as UID/GID 10001, with one CPU, a 768 MiB container limit, a read-only root filesystem, no network, no published port, and a bounded temporary filesystem. This service is a one-shot CLI suited to a dedicated offline inference worker. Inference imports the shared feature encoder and the native CatBoost reader. Training commands, training subprocesses, database credentials, and broker access are absent from the inference job.

Keep model files on persistent, operator-controlled host storage and mount the directory read-only. A durable host volume or provisioned copy from a restricted artifact store fits this layout. Each deployment's model directory and inputs must be readable by the container UID. Keep one seller's job inputs and registry credentials scoped to that seller. Use JSON for the registry and native CBM for the binary.

```text
/models/
  <seller-uuid>/
    registry.json
    <immutable-release-id>/
      catboost-horizon-7.cbm
      catboost-horizon-14.cbm
      catboost-horizon-30.cbm
```

Only declared horizons need files. The registry is provisioned with a SHA-256 pin via `FORECAST_REGISTRY_SHA256` from the trusted deployment configuration. The parent and the native worker verify the pin against the exact registry bytes. The worker then verifies the per-horizon artifact's SHA-256 before passing a private copy of those same bytes to the native decoder. Relative paths are derived from the authorized seller UUID, the validated release ID and the supported horizon. Symlinks, nonregular files and oversized files are rejected. SHA-256 checks depend on keeping the approval registry and its pin under operator control. An ordinary forecast caller supplies no release ID, file path, digest, or approval decision. [CatBoost native model format](https://catboost.ai/docs/en/concepts/python-reference_catboostranker_load_model) · [Compose resource and mount settings](https://docs.docker.com/reference/compose-file/services/)

Each approved attempt runs in its own process. The defaults are a five-second wall timeout, four seconds of CPU time, a 1 GiB Linux address-space ceiling, one CatBoost prediction thread, one concurrent native attempt per service instance, and a 32 MiB binary limit. The Compose memory cap also covers the whole job. A timeout terminates the child and releases capacity. A forecast can attempt at most two native processes in sequence. The service exposes process-local counts and cumulative native duration through `health_metrics()` and the CLI output. Metrics contain no path, seller ID, or demand data. A caller running multiple job instances should keep queue concurrency within the deployment's total resource budget.

## Promotion and rollback

1. Train a seller-scoped Task 11 model in the separate training environment. Record the actual latest training outcome cutoff from `training_data_cutoff` in the training metadata. Older artifacts with an unknown cutoff need verified provenance before approval.
2. Attach per-horizon validation from a separate, mature seller holdout. Record the Dhaka origin range, latest label extract cutoff, matched evaluation row count, model and baseline MAE, and available WAPE, MASE and bias. Approval requires historical holdout scope, strictly lower MAE on matched rows, at least three matched rows, and sequential training, holdout and label-availability cutoffs. Operators must verify the underlying evaluation before marking an entry approved. Synthetic or baseline-retained Task 11 runs are ineligible.
3. Stage the CBM files under a new immutable release. Compute the hash of each exact CBM. Build a `ForecastModelManifest` with the seller, release, algorithm version, training timestamp and cutoff, supported horizon artifacts, Task 9 feature version and schema digest, exact runtime dependency versions and approval timestamp. `runtime_dependencies()` in the worker lists the version keys checked against the inference image.
4. Validate and publish a `ForecastModelRegistry` with the new manifest in `active` and the prior approved release in `previous`. Publish the registry atomically and roll out its new digest in the trusted job configuration. Smoke-test in shadow mode on an eligible authorized snapshot whose origin follows the approval timestamp. The registry version is `forecast-registry-v1`.
5. Roll back immediately by selecting `disabled` or deploying a registry with the previous approved release as active and its new registry digest. Preserve the old binaries on durable storage. Mark revoked releases accordingly and omit them from the active rollout. The service automatically bypasses a failed or unsupported active model during any enabled forecast.

The live recommendation integration is outside this task. No registry with real seller approval ships in the repository.

The [Phase 4 audit](phase-4-release-readiness.md) adds release evidence requirements. Supply the Task 11 `lineage_sha256` and `encoder_version` in the manifest and the per-horizon `nonoverlapping_origin_dates` in the validation metrics. Approved releases need at least three nonoverlapping origin dates within the declared holdout window. The inference process starts with application secrets and dotenv absent.

## Invoking the isolated job

Set `FORECAST_MODEL_HOST_DIR` and `FORECAST_INPUT_HOST_DIR` to existing private directories and provision the seller's registry pin in `FORECAST_REGISTRY_SHA256`. The example runs the offline job in shadow mode.

```sh
FORECAST_ML_MODE=shadow docker compose -f docker-compose.forecast.yml --profile forecast \
  run --rm forecast-inference --seller-id <authorized-seller-uuid> \
  --snapshot /inputs/snapshot.json --origin 2026-11-16T06:00:00Z --horizon 7
```

The command can also run from `backend` using `python -m scripts.infer_forecast` in the pinned inference environment. Set `FORECAST_ARTIFACT_ROOT` to the absolute durable model directory in that case. `--baseline-policy` accepts an earlier Task 12 policy from the same seller. The inference image includes the native statistical baselines. If an optional StatsForecast model is unavailable, the Task 12 fallback remains available.

Verification loaded a real CatBoost CBM and exercised active, previous, shadow, corruption, missing files and timeout paths on macOS ARM64 with CPython 3.14.4. The approved manifests in tests represent simulated operator approval. The Linux image build and execution require a container runtime and remain unverified in this workspace.
