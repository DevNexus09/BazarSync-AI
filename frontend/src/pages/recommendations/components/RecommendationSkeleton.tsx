import { cn } from "@/lib/utils"

type RecommendationSkeletonProps = {
  className?: string
}

export function RecommendationSkeleton({ className }: RecommendationSkeletonProps) {
  return (
    <div className={cn("space-y-4", className)} role="status" aria-label="Loading recommendation">
      <div className="rounded-xl border bg-background p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="h-3 w-24 rounded bg-muted" />
            <div className="h-5 w-48 rounded bg-muted" />
          </div>
          <div className="h-8 w-24 rounded-full bg-muted" />
        </div>
        <div className="mt-5 space-y-2">
          <div className="h-3 w-32 rounded bg-muted" />
          <div className="h-16 w-full rounded bg-muted" />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={`recommendation-stat-skeleton-${index}`}
            className="rounded-xl border bg-background p-4 shadow-sm"
          >
            <div className="h-3 w-28 rounded bg-muted" />
            <div className="mt-3 h-5 w-20 rounded bg-muted" />
            <div className="mt-2 h-3 w-24 rounded bg-muted" />
          </div>
        ))}
      </div>

      <div className="rounded-xl border bg-background p-4 shadow-sm">
        <div className="h-3 w-32 rounded bg-muted" />
        <div className="mt-3 h-6 w-40 rounded bg-muted" />
        <div className="mt-2 h-3 w-48 rounded bg-muted" />
      </div>
    </div>
  )
}
