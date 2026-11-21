import { render, screen } from "@testing-library/react"
import { expect, it } from "vitest"

import { RecommendationCard } from "./recommendation-card"

it("displays the evidence confidence label without projecting lift from urgency", () => {
  render(<RecommendationCard recommendation={{
    id: "recommendation-a",
    title: "Hold price recommendation",
    summary: "Evidence is incomplete.",
    action: "hold",
    status: "new",
    priority: "low",
    confidence: 0.5,
    confidenceLabel: "LOW",
    expectedLift: 0.8,
    product: "Fixture product",
    createdAt: "2026-11-15T00:00:00Z",
  }} />)

  expect(screen.getByText("Confidence").nextElementSibling).toHaveTextContent("LOW")
  expect(screen.queryByText("50%")).not.toBeInTheDocument()
  expect(screen.queryByText("Expected lift")).not.toBeInTheDocument()
})
