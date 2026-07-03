export function buildDefaultCandidateInput(currentPrice: number | null | undefined) {
  if (!currentPrice || currentPrice <= 0) {
    return ""
  }
  return [
    currentPrice * 0.9,
    currentPrice * 0.95,
    currentPrice,
    currentPrice * 1.05,
    currentPrice * 1.1,
  ]
    .map((value) => roundMoney(value).toString())
    .join(", ")
}

export function parseCandidatePrices(input: string): number[] {
  const values = input
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean)
    .map(Number)

  if (values.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("Candidate prices must be positive numbers.")
  }

  return [...new Set(values.map(roundMoney))].sort((a, b) => a - b)
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100
}
