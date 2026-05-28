import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import type { PaginationMeta, TelegramAlertRecord } from "@/types/telegram"
import { cn } from "@/lib/utils"

type TelegramAlertHistoryProps = {
  alerts: TelegramAlertRecord[]
  meta?: PaginationMeta
  page: number
  onPageChange: (page: number) => void
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

const statusStyles: Record<string, string> = {
  delivered: "bg-emerald-100 text-emerald-700",
  failed: "bg-rose-100 text-rose-700",
  pending: "bg-amber-100 text-amber-700",
  duplicate: "bg-muted text-muted-foreground",
}

const toTitleCase = (value: string) =>
  value.replace(/\b\w/g, (char) => char.toUpperCase())

export function TelegramAlertHistory({
  alerts,
  meta,
  page,
  onPageChange,
  isLoading,
  isError,
  onRetry,
}: TelegramAlertHistoryProps) {
  if (isLoading) {
    return (
      <div className="rounded-xl border bg-background p-5 shadow-sm">
        <div className="h-5 w-40 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={`telegram-alert-skeleton-${index}`}
              className="h-10 rounded-lg bg-muted/30"
            />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        title="Telegram alerts unavailable"
        message="We couldn't load Telegram alert history."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  return (
    <div className="rounded-xl border bg-background p-5 shadow-sm">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Recent Telegram alerts
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Latest alerts delivered through BazarSync AI Telegram.
          </p>
        </div>
        <span className="text-xs text-muted-foreground">
          {meta?.total ?? alerts.length} total
        </span>
      </div>

      {alerts.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed bg-muted/30 p-4 text-xs text-muted-foreground">
          No Telegram alerts sent yet. Alerts will appear here once delivery starts.
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg border">
          <div className="min-w-[720px]">
            <div className="grid grid-cols-[1.2fr_1fr_1fr_1fr_0.9fr] gap-2 bg-muted/40 px-4 py-2 text-[11px] font-semibold uppercase text-muted-foreground">
              <span>Alert Type</span>
              <span>Product</span>
              <span>Action</span>
              <span>Sent Time</span>
              <span>Status</span>
            </div>
            {alerts.map((alert) => (
              <div
                key={alert.id}
                className="grid grid-cols-[1.2fr_1fr_1fr_1fr_0.9fr] gap-2 border-t px-4 py-3 text-xs text-muted-foreground"
              >
                <span className="font-semibold text-foreground">
                  {toTitleCase(alert.alertType)}
                </span>
                <span className="truncate">{alert.product}</span>
                <span>{toTitleCase(alert.action)}</span>
                <span>{new Date(alert.sentAt).toLocaleString()}</span>
                <span
                  className={cn(
                    "inline-flex w-fit items-center rounded-full px-2.5 py-1 text-[11px] font-semibold",
                    statusStyles[alert.deliveryStatus] ?? "bg-muted text-muted-foreground"
                  )}
                >
                  {toTitleCase(alert.deliveryStatus)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {meta ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            Page {meta.page} of {meta.totalPages}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="xs"
              onClick={() => onPageChange(Math.max(1, page - 1))}
              disabled={!meta.hasPrev}
            >
              <ChevronLeft className="size-3.5" />
              Prev
            </Button>
            <Button
              variant="outline"
              size="xs"
              onClick={() => onPageChange(page + 1)}
              disabled={!meta.hasNext}
            >
              Next
              <ChevronRight className="size-3.5" />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
