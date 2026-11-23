import { Info } from "lucide-react"
import { useId, type ReactNode } from "react"

import { cn } from "@/lib/utils"

export function KpiTile({
  label,
  value,
  delta,
  hint,
  onClick,
  className,
}: {
  label: string
  value: ReactNode
  delta?: ReactNode
  /** Short "what this means" text, shown on hover or focus and read by screen readers. */
  hint?: string
  onClick?: () => void
  className?: string
}) {
  const hintId = useId()
  const body = (
    <>
      <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
        {label}
        {hint ? (
          <span className="group/hint relative inline-flex rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" tabIndex={onClick ? undefined : 0}>
            <Info aria-hidden className="size-3.5" />
            <span
              id={hintId}
              role="tooltip"
              className="pointer-events-none absolute left-1/2 top-full z-20 mt-1 hidden w-48 -translate-x-1/2 rounded-md border border-border bg-popover px-2 py-1 text-xs font-normal text-popover-foreground shadow-lg group-hover/hint:block group-focus-within/tile:block"
            >
              {hint}
            </span>
          </span>
        ) : null}
      </span>
      <span className="mt-1 block text-2xl font-semibold text-foreground">{value}</span>
      {delta ? <span className="mt-0.5 block text-xs text-muted-foreground">{delta}</span> : null}
    </>
  )
  const classes = cn("group/tile glass-panel-muted block w-full p-3 text-left", className)
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      aria-describedby={hint ? hintId : undefined}
      className={cn(classes, "transition hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")}
    >
      {body}
    </button>
  ) : (
    <div className={classes} aria-describedby={hint ? hintId : undefined}>
      {body}
    </div>
  )
}
