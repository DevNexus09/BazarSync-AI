"""End-to-end Business Copilot accuracy eval against a seeded seller (outside request handlers).

Runs each golden question through ``CopilotOrchestrator.ask`` with the current settings
(real tools, real database, configured LLM providers) and checks that every expected fact
appears in the answer. Live LLM calls may cost money; questions run sequentially.

    python scripts/copilot_eval.py --seller-id <uuid>
    python scripts/copilot_eval.py --seller-id <uuid> --only rev_october,stock_in_week

The orchestrator persists one Copilot conversation per question for that seller, exactly
like the API does. Results go to ``artifacts/copilot_eval/<timestamp>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

FIXTURE = BACKEND / "tests" / "fixtures" / "copilot_golden_questions.json"
OUTPUT_DIR = BACKEND / "artifacts" / "copilot_eval"
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def normalize(text: str) -> str:
    text = (text or "").translate(BANGLA_DIGITS).casefold()
    # "290,360.28" and "2,90,360.28" (lakh grouping) both become "290360.28".
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return " ".join(text.split())


def _numbers(text: str) -> list[Decimal]:
    return [Decimal(token) for token in NUMBER_RE.findall(text)]


def value_present(expected: str, answer: str) -> bool:
    """Numbers match exactly or at the same rounding the answer used; text matches as a substring."""
    norm_answer = normalize(answer)
    norm_expected = normalize(expected)
    try:
        target = Decimal(norm_expected)
    except InvalidOperation:
        return norm_expected in norm_answer
    for number in _numbers(norm_answer):
        exponent = number.as_tuple().exponent
        places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        # Sign is ignored: "fell by 17,287.94" restates a change of -17287.94.
        if abs(number) == abs(target.quantize(Decimal(1).scaleb(-places))):
            return True
    return False


def grade(case: dict[str, Any], answer: str, tools: list[str]) -> dict[str, Any]:
    facts = []
    for fact in case.get("expected_facts", []):
        options = fact.get("any_of") or [fact["value"]]
        facts.append({"label": fact["label"], "expected": options, "found": any(value_present(option, answer) for option in options)})
    forbidden = [value for value in case.get("must_not_contain", []) if normalize(value) in normalize(answer)]
    expected_tools = case.get("expected_tools_any") or []
    return {
        "passed": all(fact["found"] for fact in facts) and not forbidden,
        "facts": facts,
        "forbidden_found": forbidden,
        "tool_match": (not expected_tools) or any(tool in tools for tool in expected_tools),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.copilot.orchestrator import CopilotOrchestrator, CopilotOrchestratorRequest

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]
    seller_id = UUID(args.seller_id)
    rows = []
    for case in cases:
        started = time.monotonic()
        with SessionLocal() as session:
            try:
                result = await CopilotOrchestrator(db=session).ask(
                    CopilotOrchestratorRequest(
                        seller_id=seller_id,
                        user_id=seller_id,
                        question=case["question"],
                        requested_language="auto",
                        include_tool_trace=True,
                    )
                )
                answer = result.answer
                tools = [str(item.get("tool_name") or item.get("name") or "") for item in result.tools_used]
                error = None
            except Exception as exc:  # noqa: BLE001 - one crashing question is a failed row, not a failed run
                session.rollback()
                answer, tools, error = "", [], f"{exc.__class__.__name__}: {exc}"
        row = {"id": case["id"], "question": case["question"], "answer": answer, "tools": tools, "error": error, "latency_ms": int((time.monotonic() - started) * 1000)}
        row.update(grade(case, answer, tools))
        if error:
            row["passed"] = False
        rows.append(row)
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {case['id']:<28} tools={'ok' if row['tool_match'] else 'miss'}  {row['latency_ms']}ms")
        if not row["passed"] and args.verbose:
            print(f"      answer: {answer[:300]!r}  error={error}")
    passed = sum(row["passed"] for row in rows)
    summary = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "seller_id": str(seller_id),
        "total": len(rows),
        "passed": passed,
        "score": round(passed / len(rows), 4) if rows else 0.0,
        "tool_match_rate": round(sum(row["tool_match"] for row in rows) / len(rows), 4) if rows else 0.0,
        "rows": rows,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nscore {passed}/{len(rows)} = {summary['score']:.0%}  tool match {summary['tool_match_rate']:.0%}  -> {path}")
    return summary


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--seller-id", required=True)
    cli.add_argument("--only", help="Comma-separated question ids.")
    cli.add_argument("--verbose", action="store_true", help="Print failing answers.")
    asyncio.run(run(cli.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
