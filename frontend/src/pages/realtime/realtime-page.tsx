import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/common/page-header"

const monitoringTiles = [
  {
    title: "Live category heatmap",
    description: "See which categories are surging in real time.",
  },
  {
    title: "Order velocity",
    description: "Track orders per minute for top-performing SKUs.",
  },
  {
    title: "Seller sentiment",
    description: "Monitor review shifts and chat feedback continuously.",
  },
]

export default function RealtimePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Realtime monitoring"
        description="Live visibility into demand, pricing, and seller signals."
        action={<Button size="sm">Start monitoring</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {monitoringTiles.map((item) => (
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
