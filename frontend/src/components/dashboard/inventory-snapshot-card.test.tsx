import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, it } from "vitest"

import { InventorySnapshotCard } from "./inventory-snapshot-card"

const inventory = {
  totalActiveProducts: 10,
  lowRiskProducts: 4,
  mediumRiskProducts: 3,
  highRiskProducts: 1,
  criticalRiskProducts: 1,
  insufficientDataProducts: 1,
  productsRequiringReorder: 2,
  productsAlreadyOutOfStock: 0,
  lastCalculationTime: null,
  dataFreshnessStatus: "FRESH",
}

it("totals risk segments and shows unavailable margin as a dash", () => {
  render(
    <MemoryRouter>
      <InventorySnapshotCard inventory={inventory} isLoading={false} isError={false} />
    </MemoryRouter>
  )

  expect(screen.getByText("products").previousElementSibling).toHaveTextContent("10")
  expect(screen.getByText("Critical").nextElementSibling).toHaveTextContent("1")
  expect(screen.getByText("Margin at risk").nextElementSibling).toHaveTextContent("—")
})

it("explains how to get data when nothing is scored yet", () => {
  render(
    <MemoryRouter>
      <InventorySnapshotCard
        inventory={{ ...inventory, lowRiskProducts: 0, mediumRiskProducts: 0, highRiskProducts: 0, criticalRiskProducts: 0, insufficientDataProducts: 0 }}
        isLoading={false}
        isError={false}
      />
    </MemoryRouter>
  )

  expect(screen.getByText(/No inventory risk calculated yet/)).toBeInTheDocument()
})
