import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/common/page-header"

const alertTracks = [
  {
    title: "Low stock alerts",
    description: "Auto-notify ops when inventory drops below threshold.",
  },
  {
    title: "Price undercutting",
    description: "Instant alerts when competitors drop prices.",
  },
  {
    title: "Campaign spikes",
    description: "WhatsApp notifications for sudden demand surges.",
  },
]

export default function AlertsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="WhatsApp alerts"
        description="Reach sellers instantly with critical marketplace signals."
        action={<Button size="sm">Create alert</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {alertTracks.map((item) => (
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
