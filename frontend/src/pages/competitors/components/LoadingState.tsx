import { cn } from "@/lib/utils"

type LoadingStateProps = {
  label?: string
  rows?: number
  className?: string
}

const skeletonRow = (index: number) => (
  <div
    key={`competitor-skeleton-${index}`}
    className="grid grid-cols-8 gap-4 px-4 py-3"
  >
    <div className="col-span-2 h-4 rounded bg-muted" />
    <div className="h-4 rounded bg-muted" />
    <div className="h-4 rounded bg-muted" />
    <div className="h-4 rounded bg-muted" />
    <div className="h-4 rounded bg-muted" />
    <div className="h-4 rounded bg-muted" />
    <div className="h-4 rounded bg-muted" />
  </div>
)

export function LoadingState({
  label = "Loading competitor intelligence...",
  rows = 5,
  className,
}: LoadingStateProps) {
  return (
    <div className={cn("space-y-4", className)}>
      <div className="hidden overflow-hidden rounded-xl border bg-background shadow-sm md:block">
        <div className="h-10 bg-muted/40" />
        <div className="divide-y animate-pulse">{Array.from({ length: rows }).map((_, index) => skeletonRow(index))}</div>
      </div>

      <div className="grid gap-4 md:hidden">
        {Array.from({ length: Math.min(rows, 4) }).map((_, index) => (
          <div key={`competitor-card-skeleton-${index}`} className="rounded-xl border bg-background p-4 shadow-sm">
            <div className="h-4 w-2/3 rounded bg-muted" />
            <div className="mt-4 grid grid-cols-2 gap-3">
              {Array.from({ length: 4 }).map((__, metricIndex) => (
                <div key={`competitor-metric-${index}-${metricIndex}`}>
                  <div className="h-3 w-16 rounded bg-muted" />
                  <div className="mt-2 h-4 w-20 rounded bg-muted" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  )
}
