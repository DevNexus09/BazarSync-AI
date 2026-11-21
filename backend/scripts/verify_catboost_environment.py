"""Fail-fast dependency and CPU-only CatBoost training smoke check."""

from importlib.metadata import version
import argparse
import json
import math
import platform
import sys

from catboost import CatBoostRegressor  # type: ignore[import-untyped]

from app.services.catboost_forecast_service import CATBOOST_VERSION


EXPECTED = {
    "catboost": CATBOOST_VERSION,
    "numpy": "2.4.6",
    "pandas": "3.0.3",
    "scipy": "1.17.1",
}


def verify() -> dict[str, object]:
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("The Task 11 training image requires CPython 3.14.")
    installed = {name: version(name) for name in EXPECTED}
    if installed != EXPECTED:
        raise RuntimeError(f"Training dependency mismatch: {installed!r}")
    model = CatBoostRegressor(
        iterations=3,
        depth=2,
        loss_function="Poisson",
        task_type="CPU",
        thread_count=1,
        random_seed=20261116,
        bootstrap_type="No",
        random_strength=0,
        allow_writing_files=False,
        verbose=False,
    )
    model.fit(
        [[0.0, "a"], [1.0, "a"], [2.0, "b"], [3.0, "b"]], [0, 1, 2, 4], cat_features=[1]
    )
    prediction = float(model.predict([[1.5, "a"]])[0])
    if not math.isfinite(prediction) or prediction < 0:
        raise RuntimeError("CatBoost dependency smoke produced an invalid prediction.")
    return {
        "status": "ok",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "dependencies": installed,
        "task_type": "CPU",
        "thread_count": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    content = json.dumps(verify(), indent=2, sort_keys=True)
    if args.output:
        from pathlib import Path

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
