from __future__ import annotations

import json
import logging
from math import isfinite
from typing import Any

from app.ai.groq_client import GroqAPIError, GroqConfigurationError, generate_json_completion
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.lib.pricing.revenue_simulator import (
    DEFAULT_PRICE_ELASTICITY,
    RevenueSimulatorInput,
    calculate_revenue_simulation,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pricing", tags=["pricing-simulator"])
GROQ_PRICING_EXPLANATION_MODEL = "llama-3.1-8b-instant"

FALLBACK_EXPLANATION = {
    "banglaReasoning": "প্রস্তাবিত দামটি হিসাব অনুযায়ী সর্বোচ্চ সম্ভাব্য লাভ দেখাচ্ছে।",
    "businessExplanation": "এই দামে বিক্রি কিছুটা কমতে পারে, তবে প্রতি ইউনিটে লাভ বাড়ার কারণে মোট লাভ বাড়তে পারে।",
    "expectedImpact": "এটি একটি আনুমানিক পূর্বাভাস। বাস্তব ফলাফল বাজার, প্রতিযোগিতা ও গ্রাহকের চাহিদার উপর নির্ভর করবে।",
}


class PricingSimulationRequest(BaseModel):
    product_id: str | None = Field(default=None, alias="productId", max_length=120)
    product_name: str | None = Field(default=None, alias="productName", max_length=120)
    candidate_prices: list[float] = Field(alias="candidatePrices", min_length=1, max_length=20)
    unit_cost: float = Field(alias="unitCost", ge=0, le=1_000_000_000)
    baseline_price: float = Field(alias="baselinePrice", gt=0, le=1_000_000_000)
    baseline_monthly_units: float = Field(alias="baselineMonthlyUnits", gt=0, le=1_000_000_000)
    price_elasticity: float = Field(
        default=DEFAULT_PRICE_ELASTICITY,
        alias="priceElasticity",
    )

    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    @field_validator("candidate_prices")
    @classmethod
    def validate_candidate_prices(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("candidatePrices must contain at least one valid price.")
        if any(not isfinite(price) or price <= 0 for price in value):
            raise ValueError("candidatePrices must contain positive numbers only.")
        return value

    @field_validator("price_elasticity")
    @classmethod
    def validate_price_elasticity(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("priceElasticity must be a finite number.")
        if value > 0:
            raise ValueError(
                "priceElasticity must be zero or negative because price increases should not normally increase demand in this model."
            )
        return value


class PricingSimulationItem(BaseModel):
    price: float = Field(gt=0, le=1_000_000_000)
    estimated_units: int = Field(alias="estimatedUnits", ge=0, le=1_000_000_000)
    revenue: float = Field(le=1_000_000_000_000_000)
    profit: float = Field(ge=-1_000_000_000_000_000, le=1_000_000_000_000_000)
    margin: float = Field(ge=-1_000_000, le=1_000_000)
    warning: str | None = None

    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    @field_validator("revenue", "profit", "margin")
    @classmethod
    def validate_finite_metric(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Simulation values must be finite numbers.")
        return value


class PricingExplanationRequest(BaseModel):
    product_name: str = Field(alias="productName", min_length=1, max_length=120)
    baseline_price: float = Field(alias="baselinePrice", gt=0, le=1_000_000_000)
    recommended_price: float = Field(alias="recommendedPrice", gt=0, le=1_000_000_000)
    expected_revenue_impact: str = Field(alias="expectedRevenueImpact", min_length=1, max_length=32)
    expected_profit_impact: str = Field(alias="expectedProfitImpact", min_length=1, max_length=32)
    simulations: list[PricingSimulationItem] = Field(min_length=1, max_length=20)

    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)


@router.post("/simulate")
async def simulate_pricing(request: Request) -> JSONResponse:
    try:
        raw_payload: Any = await request.json()
        payload = PricingSimulationRequest.model_validate(raw_payload)
        result = calculate_revenue_simulation(
            RevenueSimulatorInput(
                product_id=payload.product_id,
                product_name=payload.product_name,
                candidate_prices=payload.candidate_prices,
                unit_cost=payload.unit_cost,
                baseline_price=payload.baseline_price,
                baseline_monthly_units=payload.baseline_monthly_units,
                price_elasticity=payload.price_elasticity,
            )
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": result})
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": "Request body must be valid JSON."},
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": _validation_message(exc)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(exc)},
        )
    except Exception:
        logger.exception("pricing_simulation_unexpected_error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": "Something went wrong while running the pricing simulation.",
            },
        )


@router.post("/explain")
async def explain_pricing(request: Request) -> JSONResponse:
    try:
        raw_payload: Any = await request.json()
        payload = PricingExplanationRequest.model_validate(raw_payload)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": "Request body must be valid JSON."},
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": _validation_message(exc)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(exc)},
        )

    try:
        explanation = await _generate_groq_pricing_explanation(payload)
    except (GroqAPIError, GroqConfigurationError):
        logger.warning("pricing_explanation_fallback reason=groq_unavailable")
        explanation = FALLBACK_EXPLANATION
    except Exception:
        logger.exception("pricing_explanation_unexpected_error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": "Something went wrong while creating the pricing explanation.",
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": explanation},
    )


async def _generate_groq_pricing_explanation(
    payload: PricingExplanationRequest,
) -> dict[str, str]:
    response = await generate_json_completion(
        _build_pricing_explanation_messages(payload),
        model=GROQ_PRICING_EXPLANATION_MODEL,
        temperature=0.2,
        max_tokens=500,
        schema_hint={
            "banglaReasoning": "প্রস্তাবিত দাম কেন বেছে নেওয়া হয়েছে",
            "businessExplanation": "ব্যবসার জন্য সহজ ব্যাখ্যা",
            "expectedImpact": "আনুমানিক প্রভাব ও সতর্কতা",
        },
        request_id="public-pricing-explain",
    )
    content = response["content"]
    return {
        "banglaReasoning": _safe_text(content.get("banglaReasoning"), FALLBACK_EXPLANATION["banglaReasoning"]),
        "businessExplanation": _safe_text(content.get("businessExplanation"), FALLBACK_EXPLANATION["businessExplanation"]),
        "expectedImpact": _safe_text(content.get("expectedImpact"), FALLBACK_EXPLANATION["expectedImpact"]),
    }


def _build_pricing_explanation_messages(
    payload: PricingExplanationRequest,
) -> list[dict[str, str]]:
    context = {
        "productName": payload.product_name,
        "baselinePrice": payload.baseline_price,
        "recommendedPrice": payload.recommended_price,
        "expectedRevenueImpact": payload.expected_revenue_impact,
        "expectedProfitImpact": payload.expected_profit_impact,
        "simulations": [
            {
                "price": item.price,
                "estimatedUnits": item.estimated_units,
                "revenue": item.revenue,
                "profit": item.profit,
                "margin": item.margin,
                "warning": item.warning,
            }
            for item in payload.simulations
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "You explain pricing simulator results for small sellers. "
                "Return only valid JSON. Write every value in Bangla. "
                "Use simple seller-friendly language. Explain why the recommended price was selected, "
                "the revenue impact, profit impact, and margin impact. Mention this is an estimate, not a guarantee. "
                "Avoid overpromising and never say the business will definitely earn more."
            ),
        },
        {
            "role": "user",
            "content": (
                "Use only this validated simulator context. Do not invent extra numbers or private data. "
                f"Context: {json.dumps(context, ensure_ascii=False)}"
            ),
        },
    ]


def _safe_text(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:1000]
    return fallback


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Request body is invalid."
    message = str(errors[0].get("msg") or "Request body is invalid.")
    return message.removeprefix("Value error, ")
