import { useState } from "react"
import { ShieldCheck } from "lucide-react"

import { PageHeader } from "@/components/common/page-header"
import { TelegramConnectCard } from "@/components/telegram/telegram-connect-card"
import { TelegramInstructionsModal } from "@/components/telegram/telegram-instructions-modal"
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import { TelegramAlertHistory } from "@/components/telegram/telegram-alert-history"
import { ProductSnapshotCard } from "@/components/telegram/product-snapshot-card"
import { useTelegramConnection } from "@/hooks/useTelegramConnection"
import { useTelegramAlerts } from "@/hooks/useTelegramAlerts"
import type { TelegramConnectionState } from "@/types/telegram"
import { getErrorMessage } from "@/utils/errors"

const resolveConnectionState = (
  isConnected: boolean,
  isLoading: boolean,
  isError: boolean
): TelegramConnectionState => {
  if (isError) {
    return "error"
  }
  if (isLoading) {
    return "connecting"
  }
  return isConnected ? "connected" : "not_connected"
}

export default function TelegramAlertsPage() {
  const { status, health, connectToken, disconnect } = useTelegramConnection()
  const alerts = useTelegramAlerts()
  const [isInstructionsOpen, setInstructionsOpen] = useState(false)

  const isConnected = status.data?.isConnected ?? false
  const connectionState = resolveConnectionState(
    isConnected,
    status.isLoading || connectToken.isPending,
    status.isError
  )
  const botUsername =
    status.data?.botUsername ?? connectToken.data?.botUsername ?? "@bazarsync_bot"

  const healthLabel =
    health.isLoading
      ? "Checking bot health..."
      : health.isError || health.data?.status !== "ok"
        ? "Bot offline"
        : "Bot online"

  return (
    <div className="space-y-6">
      <PageHeader
        title="Telegram Alerts"
        description="Manage BazarSync AI Telegram connections and delivery preferences."
      />

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-6">
          <TelegramConnectCard
            status={status.data}
            state={connectionState}
            isConnecting={connectToken.isPending}
            isDisconnecting={disconnect.isPending}
            errorMessage={status.isError ? getErrorMessage(status.error) : null}
            onConnect={() => connectToken.mutate()}
            onDisconnect={() => disconnect.mutate()}
            onShowInstructions={() => setInstructionsOpen(true)}
          />
          <TelegramAlertHistory
            alerts={alerts.alerts}
            meta={alerts.meta}
            page={alerts.page}
            onPageChange={alerts.setPage}
            isLoading={alerts.isLoading}
            isError={alerts.isError}
            onRetry={() => alerts.refetch()}
          />
        </div>

        <div className="space-y-6">
          <div className="rounded-xl border bg-background p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  Connection status
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Track your Telegram connection health in real time.
                </p>
              </div>
              <TelegramStatusBadge state={connectionState} />
            </div>
            <div className="mt-4 space-y-2 text-xs text-muted-foreground">
              <div className="flex items-center justify-between">
                <span>Bot</span>
                <span className="font-semibold text-foreground">{botUsername}</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Health</span>
                <span className="font-semibold text-foreground">{healthLabel}</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Connected since</span>
                <span className="font-semibold text-foreground">
                  {status.data?.connectedAt
                    ? new Date(status.data.connectedAt).toLocaleString()
                    : "Not connected"}
                </span>
              </div>
            </div>
          </div>

          <ProductSnapshotCard isConnected={isConnected} />

          <div className="rounded-xl border bg-background p-5 shadow-sm">
            <div className="flex items-start gap-3">
              <div className="flex size-9 items-center justify-center rounded-full bg-primary/10 text-primary">
                <ShieldCheck className="size-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  Alert preferences
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Control which alerts are delivered to Telegram. Preferences will be
                  persisted in a future release.
                </p>
              </div>
            </div>
            <div className="mt-4 space-y-3 text-xs text-muted-foreground">
              {[
                { id: "pricing-alerts", label: "Pricing and undercut alerts" },
                { id: "stock-alerts", label: "Stock risk alerts" },
                { id: "opportunity-alerts", label: "Revenue opportunity alerts" },
              ].map((item) => (
                <label
                  key={item.id}
                  htmlFor={item.id}
                  className="flex items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2"
                >
                  <input
                    id={item.id}
                    type="checkbox"
                    defaultChecked
                    className="size-4 rounded border-muted"
                  />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>

      <TelegramInstructionsModal
        open={isInstructionsOpen}
        onClose={() => setInstructionsOpen(false)}
        token={connectToken.data?.token}
        expiresAt={connectToken.data?.expiresAt ?? null}
        botUsername={botUsername}
        isLoading={connectToken.isPending}
        error={connectToken.error}
        onRefresh={() => connectToken.mutate()}
      />
    </div>
  )
}
