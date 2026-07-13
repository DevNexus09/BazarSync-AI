from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.evaluation.copilot_evaluation_dataset import EVALUATION_CASES  # noqa: E402
from tests.evaluation.copilot_evaluation_harness import (  # noqa: E402
    assert_dataset_requirements,
    evaluate_dataset,
)


def main() -> int:
    assert_dataset_requirements()
    scorecard, _ = evaluate_dataset()
    report = scorecard.to_dict()
    report["critical_gates"] = {
        "request_contract": scorecard.request_contract_pass_rate == 1.0,
        "current_only_mode": scorecard.current_only_success_rate == 1.0,
        "memory_only_mode": scorecard.memory_only_success_rate == 1.0,
        "both_mode": scorecard.both_mode_success_rate == 1.0,
        "action_safety": scorecard.action_safety_pass_rate == 1.0,
        "dataset_requirements": len(EVALUATION_CASES) == scorecard.total_cases,
    }
    report["production_gate_status"] = "PASS" if all(report["critical_gates"].values()) else "FAIL"
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["production_gate_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
