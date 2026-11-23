import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import {
  Bot,
  Calculator,
  CircleAlert,
  LineChart,
  ShieldCheck,
} from "lucide-react"

import { InlineAlert } from "@/components/common/inline-alert"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PricingSetupRequiredCard } from "@/components/pricing/PricingSetupRequiredCard"
import { usePricingSimulator } from "@/hooks/use-pricing-simulator"
import { useProducts } from "@/hooks/use-products"
import type { RevenueSimulationScenario } from "@/types/pricing-simulator"
import { getErrorMessage } from "@/utils/errors"
import {
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatOptionalCurrency,
  formatPercent,
} from "@/utils/formatters"
import {
  buildDefaultCandidateInput,
  parseCandidatePrices,
} from "@/utils/pricing-simulator"
import { simulationNeedsFeeSetup } from "@/utils/pricing-setup"

export default function PricingPage() {
  const [searchParams] = useSearchParams()
  const [selectedProductId, setSelectedProductId] = useState(
    () => searchParams.get("productId") ?? ""
  )
  const [candidateInput, setCandidateInput] = useState("")
  const [horizonDays, setHorizonDays] = useState(30)
  const [formError, setFormError] = useState<string | null>(null)

  const { data: products, isLoading: productsLoading, error: productsError } =
    useProducts()
  const activeProductId = selectedProductId || products?.[0]?.id || ""
  const selectedProduct = products?.find((product) => product.id === activeProductId)

  const {
    simulation,
    explanation,
    simulate,
    explain,
    isSimulating,
    isExplaining,
    simulationError,
    explanationError,
  } = usePricingSimulator(activeProductId || null)

  const effectiveCandidateInput =
    candidateInput || buildDefaultCandidateInput(selectedProduct?.sellingPrice)
  const activeSimulation =
    simulation?.productId === activeProductId ? simulation : null
  const activeExplanation =
    explanation?.simulation.productId === activeProductId ? explanation : null

  const canSubmit = Boolean(activeProductId) && !productsLoading

  const runSimulation = () => {
    try {
      const candidatePrices = parseCandidatePrices(effectiveCandidateInput)
      setFormError(null)
      simulate({
        candidatePrices,
        forecastHorizonDays: horizonDays,
      })
    } catch (error) {
      setFormError(getErrorMessage(error, "Check the candidate prices."))
    }
  }

  const runExplanation = () => {
    try {
      const candidatePrices = parseCandidatePrices(effectiveCandidateInput)
      setFormError(null)
      explain({
        candidatePrices,
        forecastHorizonDays: horizonDays,
      })
    } catch (error) {
      setFormError(getErrorMessage(error, "Check the candidate prices."))
    }
  }

  const bestScenario = activeSimulation?.scenarios
    .filter((scenario) => scenario.isAllowed && scenario.expectedProfit !== null)
    .sort((a, b) => (b.expectedProfit ?? 0) - (a.expectedProfit ?? 0))[0]
  const showFeeSetupRequired = simulationNeedsFeeSetup(activeSimulation)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pricing analytics"
        description="Preview revenue, contribution profit, and margin safety before changing a product price."
        action={
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" disabled={!activeProductId}>
              <Link
                to={`/app/pricing/fee-policies${
                  activeProductId ? `?productId=${activeProductId}` : ""
                }`}
              >
                Market Policy Fee
              </Link>
            </Button>
            <Button
              onClick={runSimulation}
              disabled={!canSubmit || isSimulating}
              className="min-w-36"
            >
              {isSimulating ? "Simulating..." : "Run simulation"}
            </Button>
          </div>
        }
      />

      <section className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <div className="space-y-2">
            <label
              htmlFor="pricing-product"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Product
            </label>
            {products && products.length > 0 ? (
              <select
                id="pricing-product"
                value={activeProductId}
                onChange={(event) => {
                  setSelectedProductId(event.target.value)
                  setCandidateInput("")
                  setFormError(null)
                }}
                className="h-11 w-full rounded-xl border border-border/70 bg-card/70 px-3 text-sm text-foreground outline-none focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30"
                disabled={productsLoading}
              >
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.title}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id="pricing-product"
                value={selectedProductId}
                onChange={(event) => setSelectedProductId(event.target.value)}
                placeholder="Enter product id"
                disabled={productsLoading}
              />
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Current price"
              value={formatOptionalCurrency(selectedProduct?.sellingPrice)}
            />
            <Metric
              label="Unit cost"
              value={formatOptionalCurrency(selectedProduct?.costPrice)}
            />
            <Metric
              label="Stock"
              value={
                selectedProduct
                  ? `${formatNumber(selectedProduct.stockQuantity)} units`
                  : "Not selected"
              }
            />
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.5fr_220px]">
          <div className="space-y-2">
            <label
              htmlFor="candidate-prices"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Candidate prices
            </label>
            <textarea
              id="candidate-prices"
              value={effectiveCandidateInput}
              onChange={(event) => setCandidateInput(event.target.value)}
              placeholder="Example: 290, 320, 349, 399"
              className="min-h-24 w-full rounded-xl border border-border/70 bg-card/70 px-3 py-2 text-sm text-foreground outline-none focus-visible:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30"
            />
            <p className="text-xs text-muted-foreground">
              Separate prices with commas, spaces, or new lines. Values are sent
              to the backend margin guard before simulation.
            </p>
          </div>

          <div className="space-y-2">
            <label
              htmlFor="forecast-horizon"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Forecast horizon
            </label>
            <Input
              id="forecast-horizon"
              type="number"
              min={1}
              max={365}
              value={horizonDays}
              onChange={(event) => setHorizonDays(Number(event.target.value))}
            />
            <Button
              type="button"
              variant="outline"
              onClick={runExplanation}
              disabled={!activeSimulation || isExplaining}
              className="mt-4 w-full"
            >
              <Bot className="size-4" aria-hidden="true" />
              {isExplaining ? "Explaining..." : "Explain with AI"}
            </Button>
          </div>
        </div>
      </section>

      {formError ? <InlineAlert variant="error" message={formError} /> : null}
      {productsError ? (
        <InlineAlert
          variant="error"
          message={getErrorMessage(productsError, "We couldn't load products.")}
        />
      ) : null}
      {simulationError ? (
        <InlineAlert
          variant="error"
          message={getErrorMessage(
            simulationError,
            "Simulation failed. Make sure pricing analytics has been generated for this product."
          )}
        />
      ) : null}
      {explanationError ? (
        <InlineAlert
          variant="error"
          message={getErrorMessage(
            explanationError,
            "AI explanation failed. The deterministic simulation is still available."
          )}
        />
      ) : null}

      {showFeeSetupRequired ? (
        <PricingSetupRequiredCard
          productId={activeProductId}
          productName={selectedProduct?.title}
          marketplace="Daraz Bangladesh"
          category={selectedProduct?.category}
          currency="BDT"
        />
      ) : null}

      {activeSimulation ? (
        <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
          <section className="rounded-xl border border-border/70 bg-card shadow-sm">
            <div className="flex flex-col gap-2 border-b border-border/60 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-foreground">
                  Simulation results
                </h3>
                <p className="text-sm text-muted-foreground">
                  Last calculated {formatDateTime(activeSimulation.calculatedAt)}
                </p>
              </div>
              <span className="rounded-full border border-border/70 px-3 py-1 text-xs font-semibold text-muted-foreground">
                {activeSimulation.demandMethod.replaceAll("_", " ")}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-border/60">
                    <th className="px-4 py-3">Candidate</th>
                    <th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Units</th>
                    <th className="px-4 py-3">Revenue</th>
                    <th className="px-4 py-3">Profit</th>
                    <th className="px-4 py-3">Margin</th>
                    <th className="px-4 py-3">Safety</th>
                    <th className="px-4 py-3">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {activeSimulation.scenarios.map((scenario) => (
                    <ScenarioRow key={scenario.candidatePrice} scenario={scenario} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <aside className="space-y-4">
            <div className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Calculator className="size-4 text-primary" aria-hidden="true" />
                Baseline
              </div>
              <div className="mt-4 grid gap-3">
                <Metric
                  label="Baseline units"
                  value={
                    activeSimulation.baselineUnits === null
                      ? "Insufficient data"
                      : formatNumber(activeSimulation.baselineUnits)
                  }
                />
                <Metric
                  label="Baseline revenue"
                  value={formatOptionalCurrency(
                    activeSimulation.baselineExpectedRevenue
                  )}
                />
                <Metric
                  label="Baseline profit"
                  value={formatOptionalCurrency(
                    activeSimulation.baselineExpectedProfit
                  )}
                />
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <LineChart className="size-4 text-primary" aria-hidden="true" />
                Best allowed profit scenario
              </div>
              {bestScenario ? (
                <div className="mt-4 space-y-3">
                  <Metric
                    label="Candidate price"
                    value={formatCurrency(bestScenario.candidatePrice)}
                  />
                  <Metric
                    label="Expected profit"
                    value={formatOptionalCurrency(bestScenario.expectedProfit)}
                  />
                  <Metric
                    label="Profit impact"
                    value={formatOptionalCurrency(bestScenario.profitImpact)}
                  />
                </div>
              ) : (
                <p className="mt-4 text-sm text-muted-foreground">
                  No candidate passed the margin guard.
                </p>
              )}
            </div>

            {activeExplanation ? (
              <div className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Bot className="size-4 text-primary" aria-hidden="true" />
                  AI explanation
                </div>
                <p className="mt-3 text-sm text-foreground">
                  {activeExplanation.summary}
                </p>
                <p className="mt-2 text-sm text-muted-foreground">
                  {activeExplanation.explanation}
                </p>
                {activeExplanation.risks.length > 0 ? (
                  <ListBlock title="Risks" items={activeExplanation.risks} />
                ) : null}
                {activeExplanation.nextSteps.length > 0 ? (
                  <ListBlock
                    title="Next steps"
                    items={activeExplanation.nextSteps}
                  />
                ) : null}
              </div>
            ) : null}
          </aside>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border/70 bg-card p-8 text-center">
          <ShieldCheck className="mx-auto size-8 text-muted-foreground" aria-hidden="true" />
          <h3 className="mt-3 text-sm font-semibold text-foreground">
            No simulation yet
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose a product, enter candidate prices, and run the simulator.
          </p>
        </div>
      )}
    </div>
  )
}

function ScenarioRow({ scenario }: { scenario: RevenueSimulationScenario }) {
  const blocked = !scenario.isAllowed
  return (
    <tr className="border-b border-border/40 last:border-0">
      <td className="px-4 py-3 font-medium text-foreground">
        {formatCurrency(scenario.candidatePrice)}
      </td>
      <td className="px-4 py-3">
        <span className="rounded-full border border-border/70 px-2 py-1 text-xs font-semibold text-muted-foreground">
          {scenario.action.replace("_", " ")}
        </span>
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {scenario.expectedUnits === null
          ? "Not projected"
          : formatNumber(scenario.expectedUnits)}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {formatOptionalCurrency(scenario.expectedRevenue)}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {formatOptionalCurrency(scenario.expectedProfit)}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {scenario.marginRate === null
          ? "Unavailable"
          : formatPercent(scenario.marginRate * 100)}
      </td>
      <td className="px-4 py-3">
        {blocked ? (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-destructive">
            <CircleAlert className="size-3.5" aria-hidden="true" />
            {scenario.rejectionReasons[0]?.replaceAll("_", " ") ?? "Blocked"}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-success">
            <ShieldCheck className="size-3.5" aria-hidden="true" />
            Allowed
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-muted-foreground">
        {formatNumber(scenario.confidenceScore)}%
      </td>
    </tr>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/50 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold text-foreground">{value}</p>
    </div>
  )
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mt-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}
