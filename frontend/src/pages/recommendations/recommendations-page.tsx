import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/common/page-header"

const recommendations = [
  {
    title: "Boost top-selling bundles",
    description: "AI predicts demand lift for combo offers on Eid season.",
  },
  {
    title: "Reallocate ad spend",
    description: "Shift 18% budget to high-converting categories this week.",
  },
  {
    title: "Recover lost conversions",
    description: "Trigger cart recovery for customers in Chattogram.",
  },
]

export default function RecommendationsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="AI recommendations"
        description="Prioritized actions to improve revenue and customer retention."
        action={<Button size="sm">Generate plan</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {recommendations.map((item) => (
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
