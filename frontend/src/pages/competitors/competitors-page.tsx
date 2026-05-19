import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/common/page-header"

const competitorHighlights = [
  {
    title: "Top price movers",
    description: "Track who is discounting fastest across your core SKUs.",
  },
  {
    title: "Share of shelf",
    description: "Measure visibility changes across Daraz and Facebook shops.",
  },
  {
    title: "Promotion calendar",
    description: "Monitor competitor campaigns ahead of payday peaks.",
  },
]

export default function CompetitorsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Competitor dashboards"
        description="Benchmark performance and pricing across the market."
        action={<Button size="sm">Compare now</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {competitorHighlights.map((card) => (
          <div key={card.title} className="rounded-xl border bg-background p-4">
            <h3 className="text-base font-semibold text-foreground">
              {card.title}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {card.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
