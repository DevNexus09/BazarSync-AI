import {
  BellOff,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  XCircle,
  type LucideIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardBody, CardHeader } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { TONE_CLASSES, type StatusTone } from "@/components/ui/status"
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

const DELIVERY_STYLES: Record<string, { tone: StatusTone; icon: LucideIcon }> = {
  delivered: { tone: "success", icon: CheckCircle2 },
  failed: { tone: "danger", icon: XCircle },
  pending: { tone: "warning", icon: Clock },
  duplicate: { tone: "neutral", icon: Copy },
}

const toTitleCase = (value: string) =>
  value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())

function DeliveryBadge({ status }: { status: string }) {
  const { tone, icon: Icon } = DELIVERY_STYLES[status] ?? { tone: "neutral", icon: Clock }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASSES[tone]
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {toTitleCase(status)}
    </span>
  )
}

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
      <div className="glass-panel p-5">
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
    <Card>
      <CardHeader
        title="Alert history"
        description="Every alert sent to your Telegram, newest first."
        actions={
          <span className="text-sm text-muted-foreground">
            {meta?.total ?? alerts.length} total
          </span>
        }
      />

      {alerts.length === 0 ? (
        <CardBody>
          <EmptyState
            icon={BellOff}
            title="No alerts sent yet"
            message="Once Telegram is connected, alerts will show up here as they are delivered."
          />
        </CardBody>
      ) : (
        <ul className="divide-y divide-border/60">
          {alerts.map((alert) => (
            <li
              key={alert.id}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">
                  {alert.product}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {toTitleCase(alert.alertType)} · {toTitleCase(alert.action)} ·{" "}
                  <time dateTime={alert.sentAt}>
                    {new Date(alert.sentAt).toLocaleString()}
                  </time>
                </p>
              </div>
              <DeliveryBadge status={alert.deliveryStatus} />
            </li>
          ))}
        </ul>
      )}

      {meta && meta.totalPages > 1 ? (
        <div className="flex border-t border-border/60 px-4 py-3 flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
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
    </Card>
  )
}
