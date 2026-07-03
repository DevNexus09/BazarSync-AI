import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { PricingSetupRequiredCard } from "./PricingSetupRequiredCard"

describe("PricingSetupRequiredCard", () => {
  it("renders friendly missing fee data guidance", () => {
    render(
      <MemoryRouter>
        <PricingSetupRequiredCard productId="product-1" productName="Rice 5kg" />
      </MemoryRouter>
    )

    expect(screen.getByText("Pricing setup incomplete")).toBeInTheDocument()
    expect(screen.getByText("Marketplace fee data is missing.")).toBeInTheDocument()
    expect(
      screen.getByText("Add a fee policy to unlock revenue and profit simulation.")
    ).toBeInTheDocument()
  })

  it("links to fee setup with product id query param", () => {
    render(
      <MemoryRouter>
        <PricingSetupRequiredCard productId="product-1" />
      </MemoryRouter>
    )

    expect(screen.getByRole("link", { name: /set up marketplace fees/i })).toHaveAttribute(
      "href",
      "/app/pricing/fee-setup?productId=product-1&marketplace=Daraz+Bangladesh&currency=BDT"
    )
  })
})
