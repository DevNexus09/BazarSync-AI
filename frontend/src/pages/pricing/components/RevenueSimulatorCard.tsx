import { useState } from "react"
import { Bot, Calculator, Plus, Trash2 } from "lucide-react"

import { InlineAlert } from "@/components/common/inline-alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { revenueSimulationInputSchema } from "@/schemas/revenue-simulator"
import {
  generatePricingExplanation,
  simulateRevenue,
} from "@/services/revenue-simulator-service"
import type {
  PricingExplanation,
  RevenueSimulationInput,
  RevenueSimulationResult,
  RevenueSimulationRow,
} from "@/types/revenue-simulator"
import { getErrorMessage } from "@/utils/errors"

const DEFAULT_CANDIDATE_PRICES = ["299", "309", "319"]

export function RevenueSimulatorCard() {
  const [productName, setProductName] = useState("")
  const [unitCost, setUnitCost] = useState("")
  const [baselinePrice, setBaselinePrice] = useState("")
  const [baselineMonthlyUnits, setBaselineMonthlyUnits] = useState("")
  const [candidatePrices, setCandidatePrices] = useState(DEFAULT_CANDIDATE_PRICES)
  const [result, setResult] = useState<RevenueSimulationResult | null>(null)
  const [explanation, setExplanation] = useState<PricingExplanation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [explanationError, setExplanationError] = useState<string | null>(null)
  const [isSimulating, setIsSimulating] = useState(false)
  const [isExplaining, setIsExplaining] = useState(false)

  const handleSimulate = async () => {
    let payload: RevenueSimulationInput
    try {
      payload = buildSimulationPayload({
        productName,
        unitCost,
        baselinePrice,
        baselineMonthlyUnits,
        candidatePrices,
      })
    } catch (validationError) {
      setError(getErrorMessage(validationError, "Please check the form."))
      return
    }

    setIsSimulating(true)
    setError(null)
    setExplanationError(null)
    setExplanation(null)
    try {
      setResult(await simulateRevenue(payload))
    } catch (apiError) {
      setResult(null)
      setError(getErrorMessage(apiError, "Revenue simulation failed."))
    } finally {
      setIsSimulating(false)
    }
  }

  const handleGenerateExplanation = async () => {
    if (!result) {
      return
    }
    setIsExplaining(true)
    setExplanationError(null)
    try {
      setExplanation(
        await generatePricingExplanation({
          productName: productName.trim(),
          baselinePrice: result.baseline.price,
          recommendedPrice: result.recommendedPrice,
          expectedRevenueImpact: result.expectedRevenueImpact,
          expectedProfitImpact: result.expectedProfitImpact,
          simulations: result.simulations,
        })
      )
    } catch (apiError) {
      setExplanation(null)
      setExplanationError(
        getErrorMessage(apiError, "AI explanation could not be generated.")
      )
    } finally {
      setIsExplaining(false)
    }
  }

  const updateCandidatePrice = (index: number, value: string) => {
    setCandidatePrices((prices) =>
      prices.map((price, currentIndex) => (currentIndex === index ? value : price))
    )
  }

  const addCandidatePrice = () => {
    setCandidatePrices((prices) => [...prices, ""])
  }

  const removeCandidatePrice = (index: number) => {
    setCandidatePrices((prices) => {
      if (prices.length === 1) {
        return prices
      }
      return prices.filter((_, currentIndex) => currentIndex !== index)
    })
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
        <div className="mb-5 flex items-start gap-3">
          <div className="rounded-xl border border-border/70 bg-background/60 p-2">
            <Calculator className="size-5 text-primary" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-foreground">
              Revenue simulator
            </h3>
            <p className="text-sm text-muted-foreground">
              Test candidate prices before changing them. Estimates use your
              baseline sales and unit cost.
            </p>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <TextField
            id="product-name"
            label="Product Name"
            value={productName}
            onChange={setProductName}
            placeholder="Rice 5kg Pack"
          />
          <NumberField
            id="unit-cost"
            label="Unit Cost"
            value={unitCost}
            onChange={setUnitCost}
            placeholder="150"
          />
          <NumberField
            id="baseline-price"
            label="Baseline Price"
            value={baselinePrice}
            onChange={setBaselinePrice}
            placeholder="299"
          />
          <NumberField
            id="baseline-monthly-units"
            label="Baseline Monthly Units"
            value={baselineMonthlyUnits}
            onChange={setBaselineMonthlyUnits}
            placeholder="100"
          />
        </div>

        <div className="mt-5 space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-foreground">
                Candidate Prices
              </h3>
              <p className="text-sm text-muted-foreground">
                Add the prices you want to test.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={addCandidatePrice}>
              <Plus className="size-4" aria-hidden="true" />
              Add price
            </Button>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            {candidatePrices.map((price, index) => (
              <div key={index} className="flex items-end gap-2">
                <NumberField
                  id={`candidate-price-${index}`}
                  label={`Candidate price ${index + 1}`}
                  value={price}
                  onChange={(value) => updateCandidatePrice(index, value)}
                  placeholder="299"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={() => removeCandidatePrice(index)}
                  disabled={candidatePrices.length === 1}
                  aria-label={`Remove candidate price ${index + 1}`}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center">
          <Button
            type="button"
            onClick={handleSimulate}
            disabled={isSimulating}
            className="min-w-40"
          >
            <Calculator className="size-4" aria-hidden="true" />
            {isSimulating ? "Simulating..." : "Simulate Revenue"}
          </Button>
          {error ? <InlineAlert variant="error" message={error} /> : null}
        </div>
      </section>

      {result ? (
        <>
          <section className="grid gap-4 md:grid-cols-3">
            <SummaryCard
              label="Recommended Price"
              value={formatCurrency(result.recommendedPrice)}
            />
            <SummaryCard
              label="Expected Revenue Impact"
              value={result.expectedRevenueImpact}
            />
            <SummaryCard
              label="Expected Profit Impact"
              value={result.expectedProfitImpact}
            />
          </section>

          <section className="rounded-xl border border-border/70 bg-card shadow-sm">
            <div className="border-b border-border/60 p-4">
              <h3 className="text-base font-semibold text-foreground">
                Simulation results
              </h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-border/60">
                    <th className="px-4 py-3">Test Price</th>
                    <th className="px-4 py-3">Estimated Units</th>
                    <th className="px-4 py-3">Expected Revenue</th>
                    <th className="px-4 py-3">Expected Profit</th>
                    <th className="px-4 py-3">Profit Margin</th>
                    <th className="px-4 py-3">Note or Warning</th>
                  </tr>
                </thead>
                <tbody>
                  {result.simulations.map((row) => (
                    <ResultRow
                      key={row.price}
                      row={row}
                      recommendedPrice={result.recommendedPrice}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-foreground">
                  AI Explanation
                </h3>
                <p className="text-sm text-muted-foreground">
                  Generate a Bangla explanation based on this simulation result.
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={handleGenerateExplanation}
                disabled={!result || isExplaining}
              >
                <Bot className="size-4" aria-hidden="true" />
                {isExplaining ? "Generating..." : "Generate AI Explanation"}
              </Button>
            </div>

            {explanationError ? (
              <div className="mt-4">
                <InlineAlert variant="error" message={explanationError} />
              </div>
            ) : null}

            {explanation ? (
              <div className="mt-4 grid gap-4 lg:grid-cols-3">
                <ExplanationCard
                  title="Bangla Reasoning"
                  value={explanation.banglaReasoning}
                />
                <ExplanationCard
                  title="Business Explanation"
                  value={explanation.businessExplanation}
                />
                <ExplanationCard
                  title="Expected Impact"
                  value={explanation.expectedImpact}
                />
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  )
}

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
        {label}
      </label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  )
}

function NumberField(props: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <TextField
      {...props}
      onChange={(value) => props.onChange(value.replace(/[^\d.]/g, ""))}
    />
  )
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
    </div>
  )
}

function ResultRow({
  row,
  recommendedPrice,
}: {
  row: RevenueSimulationRow
  recommendedPrice: number
}) {
  const isRecommended = row.price === recommendedPrice
  return (
    <tr
      className={
        isRecommended
          ? "border-b border-border/40 bg-primary/10"
          : "border-b border-border/40"
      }
    >
      <td className="px-4 py-3 font-semibold text-foreground">
        <div className="flex items-center gap-2">
          {formatCurrency(row.price)}
          {isRecommended ? (
            <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-semibold text-primary-foreground">
              Recommended
            </span>
          ) : null}
        </div>
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {formatNumber(row.estimatedUnits)}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {formatCurrency(row.revenue)}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {formatCurrency(row.profit)}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {row.margin.toFixed(2)}%
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {row.warning ?? "No warning"}
      </td>
    </tr>
  )
}

function ExplanationCard({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/50 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <p className="mt-2 text-sm leading-6 text-foreground">{value}</p>
    </div>
  )
}

function buildSimulationPayload(input: {
  productName: string
  unitCost: string
  baselinePrice: string
  baselineMonthlyUnits: string
  candidatePrices: string[]
}): RevenueSimulationInput {
  const productName = input.productName.trim()
  const unitCost = parsePositiveNumber(input.unitCost, "Unit Cost", true)
  const baselinePrice = parsePositiveNumber(input.baselinePrice, "Baseline Price")
  const baselineMonthlyUnits = parsePositiveNumber(
    input.baselineMonthlyUnits,
    "Baseline Monthly Units"
  )
  const candidatePrices = input.candidatePrices.map((price, index) =>
    parsePositiveNumber(price, `Candidate price ${index + 1}`)
  )

  if (!productName) {
    throw new Error("Product Name is required.")
  }

  return revenueSimulationInputSchema.parse({
    productName,
    unitCost,
    baselinePrice,
    baselineMonthlyUnits,
    candidatePrices,
  })
}

function parsePositiveNumber(
  value: string,
  label: string,
  allowZero = false
): number {
  if (!value.trim()) {
    throw new Error(`${label} is required.`)
  }
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) {
    throw new Error(`${label} must be a valid number.`)
  }
  if (allowZero ? numericValue < 0 : numericValue <= 0) {
    throw new Error(
      allowZero ? `${label} cannot be negative.` : `${label} must be greater than 0.`
    )
  }
  return numericValue
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-BD", {
    style: "currency",
    currency: "BDT",
    maximumFractionDigits: 0,
  }).format(value)
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-BD").format(value)
}
