import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type RunScraperButtonProps = {
  onRun: () => void
  isRunning?: boolean
  disabled?: boolean
  statusMessage?: string | null
  errorMessage?: string | null
  className?: string
}

export function RunScraperButton({
  onRun,
  isRunning = false,
  disabled = false,
  statusMessage,
  errorMessage,
  className,
}: RunScraperButtonProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <Button onClick={onRun} disabled={disabled || isRunning}>
        {isRunning ? (
          <span className="flex items-center gap-2">
            <span className="size-3 animate-spin rounded-full border border-primary/30 border-t-primary" />
            Running scraper
          </span>
        ) : (
          "Run Scraper"
        )}
      </Button>
      {errorMessage ? (
        <p className="text-xs text-destructive">{errorMessage}</p>
      ) : statusMessage ? (
        <p className="text-xs text-emerald-600">{statusMessage}</p>
      ) : null}
    </div>
  )
}
