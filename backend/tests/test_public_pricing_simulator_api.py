from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.groq_client import GroqConfigurationError
from app.api.pricing_simulator_public import router


class PublicPricingSimulatorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_simulate_pricing_success(self) -> None:
        response = self.client.post(
            "/api/pricing/simulate",
            json={
                "productId": "product_123",
                "productName": "Rice 5kg Pack",
                "candidatePrices": [299, 309, 319],
                "unitCost": 150,
                "baselinePrice": 299,
                "baselineMonthlyUnits": 100,
                "priceElasticity": -1.2,
            },
        )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(
            [299, 309, 319],
            [item["price"] for item in body["data"]["simulations"]],
        )
        self.assertEqual(319, body["data"]["recommendedPrice"])
        self.assertIn("expectedRevenueImpact", body["data"])
        self.assertIn("expectedProfitImpact", body["data"])

    def test_simulate_pricing_validation_error(self) -> None:
        response = self.client.post(
            "/api/pricing/simulate",
            json={
                "candidatePrices": [],
                "unitCost": 150,
                "baselinePrice": 299,
                "baselineMonthlyUnits": 100,
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.json()["success"])
        self.assertIn("at least 1", response.json()["error"])

    def test_simulate_pricing_rejects_positive_elasticity(self) -> None:
        response = self.client.post(
            "/api/pricing/simulate",
            json={
                "candidatePrices": [299],
                "unitCost": 150,
                "baselinePrice": 299,
                "baselineMonthlyUnits": 100,
                "priceElasticity": 1.2,
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertIn("priceElasticity must be zero or negative", response.json()["error"])

    def test_get_method_not_allowed(self) -> None:
        response = self.client.get("/api/pricing/simulate")

        self.assertEqual(405, response.status_code)

    def test_explain_pricing_success(self) -> None:
        async def fake_groq(*args, **kwargs):
            return {
                "content": {
                    "banglaReasoning": "দামটি লাভের হিসাবে ভালো।",
                    "businessExplanation": "বিক্রি কমলেও লাভ বাড়তে পারে।",
                    "expectedImpact": "এটি নিশ্চিত ফলাফল নয়।",
                }
            }

        with patch(
            "app.api.pricing_simulator_public.generate_json_completion",
            fake_groq,
        ):
            response = self.client.post(
                "/api/pricing/explain",
                json=_explain_payload(),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "success": True,
                "data": {
                    "banglaReasoning": "দামটি লাভের হিসাবে ভালো।",
                    "businessExplanation": "বিক্রি কমলেও লাভ বাড়তে পারে।",
                    "expectedImpact": "এটি নিশ্চিত ফলাফল নয়।",
                },
            },
            response.json(),
        )

    def test_explain_pricing_fallback_when_groq_missing(self) -> None:
        async def missing_key(*args, **kwargs):
            raise GroqConfigurationError("GROQ_API_KEY is missing.")

        with patch(
            "app.api.pricing_simulator_public.generate_json_completion",
            missing_key,
        ):
            response = self.client.post(
                "/api/pricing/explain",
                json=_explain_payload(),
            )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["success"])
        self.assertIn("প্রস্তাবিত দামটি", response.json()["data"]["banglaReasoning"])

    def test_explain_pricing_validation_error(self) -> None:
        response = self.client.post(
            "/api/pricing/explain",
            json={
                "productName": "",
                "baselinePrice": 299,
                "recommendedPrice": 319,
                "expectedRevenueImpact": "-1.85%",
                "expectedProfitImpact": "+4.35%",
                "simulations": [],
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.json()["success"])

def _explain_payload() -> dict[str, object]:
    return {
        "productName": "Rice 5kg Pack",
        "baselinePrice": 299,
        "recommendedPrice": 319,
        "expectedRevenueImpact": "-1.85%",
        "expectedProfitImpact": "+4.35%",
        "simulations": [
            {
                "price": 299,
                "estimatedUnits": 100,
                "revenue": 29900,
                "profit": 14900,
                "margin": 49.83,
            },
            {
                "price": 319,
                "estimatedUnits": 92,
                "revenue": 29348,
                "profit": 15548,
                "margin": 52.98,
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
