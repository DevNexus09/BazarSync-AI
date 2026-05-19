import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/common/page-header"

const pricingInsights = [
  {
    title: "Elasticity curves",
    description: "Simulate price changes and forecast demand impact.",
  },
  {
    title: "Margin guardrails",
    description: "Protect profit while matching aggressive competitors.",
  },
  {
    title: "Bundle opportunity",
    description: "Identify cross-sell pairings with high ROI.",
  },
]

export default function PricingPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Pricing analytics"
        description="Understand price sensitivity and optimize for margin."
        action={<Button size="sm">Run simulation</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {pricingInsights.map((item) => (
          <div key={item.title} className="rounded-xl border bg-background p-4">
            <h3 className="text-base font-semibold text-foreground">
              {item.title}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {item.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
