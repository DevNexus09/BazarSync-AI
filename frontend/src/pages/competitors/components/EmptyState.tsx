import { Button } from "@/components/ui/button"

type EmptyStateProps = {
  title?: string
  message?: string
  actionLabel?: string
  onAction?: () => void
}

export function EmptyState({
  title = "No competitor data yet",
  message = "Run the scraper to start monitoring competitor performance.",
  actionLabel = "Run Scraper",
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex w-full flex-col items-center justify-center gap-3 glass-surface relative rounded-[24px] px-6 py-10 text-center">
      <div className="text-sm font-semibold text-foreground">{title}</div>
      <div className="text-sm text-muted-foreground">{message}</div>
      {onAction ? (
        <Button size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  )
}
