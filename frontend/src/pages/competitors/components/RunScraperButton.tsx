import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type RunScraperButtonProps = {
  onRun: () => void
  isRunning?: boolean
  isSuccess?: boolean
  disabled?: boolean
  errorMessage?: string | null
  className?: string
}

export function RunScraperButton({
  onRun,
  isRunning = false,
  isSuccess = false,
  disabled = false,
  errorMessage,
  className,
}: RunScraperButtonProps) {
  if (isSuccess) {
    return (
      <div className={cn("space-y-2", className)}>
        <div className="inline-flex h-10 items-center justify-center rounded-lg border border-emerald-400/40 bg-emerald-500/15 px-4 text-sm font-semibold text-emerald-300 shadow-sm">
          Success
        </div>
      </div>
    )
  }

  return (
    <div className={cn("space-y-2", className)}>
      <Button
        onClick={onRun}
        disabled={disabled || isRunning}
        className="min-w-[122px]"
      >
        {isRunning ? (
          <span className="flex items-center justify-center gap-2">
            <span
              className="size-4 animate-spin rounded-full border-2 border-primary-foreground/30 border-t-primary-foreground"
              aria-hidden="true"
            />
            <span>Scraping...</span>
          </span>
        ) : (
          "Run Scraper"
        )}
      </Button>
      {errorMessage ? (
        <p className="text-xs text-destructive">{errorMessage}</p>
      ) : null}
    </div>
  )
}
