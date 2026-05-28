import { Info, MessageCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import type {
  TelegramConnectionState,
  TelegramConnectionStatus,
} from "@/types/telegram"

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return "Not yet"
  }
  return new Date(value).toLocaleString()
}

const resolveTelegramHandle = (status?: TelegramConnectionStatus | null) => {
  if (!status) {
    return "Not connected"
  }
  if (status.telegramUsername) {
    return `@${status.telegramUsername.replace(/^@/, "")}`
  }
  const name = [status.telegramFirstName, status.telegramLastName]
    .filter(Boolean)
    .join(" ")
  return name || "Telegram user"
}

type TelegramConnectCardProps = {
  status?: TelegramConnectionStatus | null
  state: TelegramConnectionState
  isConnecting: boolean
  isDisconnecting?: boolean
  errorMessage?: string | null
  onConnect: () => void
  onDisconnect: () => void
  onShowInstructions: () => void
}

export function TelegramConnectCard({
  status,
  state,
  isConnecting,
  isDisconnecting = false,
  errorMessage,
  onConnect,
  onDisconnect,
  onShowInstructions,
}: TelegramConnectCardProps) {
  const isConnected = status?.isConnected ?? false

  return (
    <div className="rounded-xl border bg-background p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Telegram connection
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Link your Telegram account to receive BazarSync AI alerts instantly.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onShowInstructions}
            aria-label="Bot connection instructions"
            title="Bot connection instructions"
          >
            <Info className="size-4" />
          </Button>
          <TelegramStatusBadge state={state} />
        </div>
      </div>

      <div className="mt-4 space-y-2 text-xs text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>Connected account</span>
          <span className="font-semibold text-foreground">
            {resolveTelegramHandle(status)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Last alert sent</span>
          <span className="font-semibold text-foreground">
            {formatDateTime(status?.lastAlertSentAt)}
          </span>
        </div>
        {errorMessage ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
            {errorMessage}
          </div>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" onClick={onConnect} disabled={isConnecting}>
          <MessageCircle className="size-4" />
          {isConnected ? "Reconnect Telegram Bot" : "Connect Telegram Bot"}
        </Button>
        {isConnected ? (
          <Button
            variant="outline"
            size="sm"
            onClick={onDisconnect}
            disabled={isDisconnecting}
          >
            Disconnect
          </Button>
        ) : null}
      </div>
    </div>
  )
}
