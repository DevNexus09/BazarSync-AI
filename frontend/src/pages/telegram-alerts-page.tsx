import { useState } from "react"

import { PageHeader } from "@/components/common/page-header"
import { KpiTile } from "@/components/ui/kpi-tile"
import { TelegramConnectCard } from "@/components/telegram/telegram-connect-card"
import { TelegramInstructionsModal } from "@/components/telegram/telegram-instructions-modal"
import { TelegramAlertHistory } from "@/components/telegram/telegram-alert-history"
import { ProductSnapshotCard } from "@/components/telegram/product-snapshot-card"
import { TestAlertButton } from "@/components/telegram/test-alert-button"
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

  const healthLabel = health.isLoading
    ? "Checking..."
    : health.isError || health.data?.status !== "ok"
      ? "Offline"
      : "Online"

  const lastAlertSentAt = status.data?.lastAlertSentAt

  const handleConnect = () => {
    connectToken.mutate()
    setInstructionsOpen(true)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Telegram Alerts"
        description="Receive BazarSync AI alerts in Telegram and check that every one was delivered."
      />

      <TelegramConnectCard
        status={status.data}
        state={connectionState}
        isConnecting={connectToken.isPending}
        isDisconnecting={disconnect.isPending}
        errorMessage={status.isError ? getErrorMessage(status.error) : null}
        onConnect={handleConnect}
        onDisconnect={() => disconnect.mutate()}
        onShowInstructions={() => setInstructionsOpen(true)}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          label="Alerts sent"
          value={alerts.meta?.total ?? (alerts.isLoading ? "—" : alerts.alerts.length)}
          hint="All Telegram alerts sent to your account."
        />
        <KpiTile
          label="Last alert"
          value={lastAlertSentAt ? new Date(lastAlertSentAt).toLocaleDateString() : "Not yet"}
          delta={lastAlertSentAt ? new Date(lastAlertSentAt).toLocaleTimeString() : undefined}
        />
        <KpiTile
          label="Bot status"
          value={healthLabel}
          delta={botUsername}
          hint="Whether the BazarSync AI bot is reachable right now."
        />
        <KpiTile
          label="Connected since"
          value={
            status.data?.connectedAt
              ? new Date(status.data.connectedAt).toLocaleDateString()
              : "Not connected"
          }
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <TelegramAlertHistory
          alerts={alerts.alerts}
          meta={alerts.meta}
          page={alerts.page}
          onPageChange={alerts.setPage}
          isLoading={alerts.isLoading}
          isError={alerts.isError}
          onRetry={() => alerts.refetch()}
        />
        <div className="space-y-6">
          <TestAlertButton enabled={isConnected} />
          <ProductSnapshotCard isConnected={isConnected} />
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
