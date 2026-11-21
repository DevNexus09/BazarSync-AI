import { AlertTriangle, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"

export function CopilotErrorState({
  title = "Copilot could not answer right now.",
  message,
  retryLabel = "Retry",
  onRetry,
}: {
  title?: string
  message?: string
  retryLabel?: string
  onRetry?: () => void
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive"
    >
      <div className="flex items-center gap-2 font-semibold">
        <AlertTriangle className="size-3.5" aria-hidden="true" />
        {title}
      </div>
      <p className="mt-1 text-foreground/80">{message ?? "Please try again."}</p>
      {onRetry ? (
        <Button type="button" size="sm" variant="outline" className="mt-2 h-7 gap-1.5 text-xs" onClick={onRetry}>
          <RotateCcw className="size-3" aria-hidden="true" />
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}
