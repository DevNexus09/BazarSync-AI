from __future__ import annotations

from decimal import Decimal
import json

from app.ai.groq_client import generate_json_completion
from app.schemas.revenue_simulator import RevenueSimulationResponse

SCHEMA_HINT = {
    "summary": "One concise English business summary.",
    "explanation": "Plain-language explanation of the simulated outcomes.",
    "risks": ["Risk or limitation from the provided simulation."],
    "next_steps": ["Recommended next step."],
}


class PricingSimulatorExplanationService:
    async def explain(self, simulation: RevenueSimulationResponse) -> dict[str, object]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You explain deterministic pricing simulation results for a seller. "
                    "Return JSON only. Do not invent numbers, do not recommend applying a price, "
                    "and do not expose secrets or internal IDs."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Explain this pricing simulation in short, practical business language. "
                    "Use only the JSON context.\n"
                    f"{json.dumps(_json_ready(simulation.model_dump()), default=str)}"
                ),
            },
        ]
        result = await generate_json_completion(
            messages,
            temperature=0.15,
            max_tokens=700,
            schema_hint=SCHEMA_HINT,
            request_id=f"pricing-simulator:{simulation.product_id}",
        )
        content = result["content"]
        return {
            "summary": str(content.get("summary") or "Simulation explanation generated."),
            "explanation": str(content.get("explanation") or ""),
            "risks": _string_list(content.get("risks")),
            "next_steps": _string_list(content.get("next_steps")),
            "model": result.get("model"),
        }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()][:5]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _json_ready(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
