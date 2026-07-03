import { describe, expect, it } from "vitest"

import {
  buildDefaultCandidateInput,
  parseCandidatePrices,
} from "./pricing-simulator"

describe("pricing simulator utils", () => {
  it("parses, rounds, deduplicates, and sorts candidate prices", () => {
    expect(parseCandidatePrices("320, 290\n320 400.126")).toEqual([
      290,
      320,
      400.13,
    ])
  })

  it("rejects invalid candidate prices", () => {
    expect(() => parseCandidatePrices("300, -10")).toThrow(
      "Candidate prices must be positive numbers."
    )
  })

  it("builds default candidate prices around current price", () => {
    expect(buildDefaultCandidateInput(100)).toBe("90, 95, 100, 105, 110")
  })
})
