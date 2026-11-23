import { HelpCircle, Loader2, MessageCircle, Unplug } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import type {
  TelegramConnectionState,
  TelegramConnectionStatus,
} from "@/types/telegram"

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

const SETUP_STEPS = [
  { title: "Get your code", body: "Click Connect Telegram to create a one-time command." },
  { title: "Open the bot", body: "Find the BazarSync AI bot in Telegram and press Start." },
  { title: "Send the command", body: "Paste the command in the chat. This page updates on its own." },
]

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
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
            <MessageCircle aria-hidden className="size-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-foreground">
              {isConnected ? "Telegram is connected" : "Connect your Telegram"}
            </h3>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {isConnected
                ? `Alerts are delivered to ${resolveTelegramHandle(status)}.`
                : "Get price, stock and competitor alerts on your phone the moment they happen."}
            </p>
          </div>
        </div>
        <TelegramStatusBadge state={state} />
      </div>

      {isConnected ? null : (
        <ol className="mt-5 grid gap-3 sm:grid-cols-3">
          {SETUP_STEPS.map((step, index) => (
            <li key={step.title} className="glass-panel-muted flex gap-3 p-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
                {index + 1}
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">{step.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      )}

      {errorMessage ? (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
        >
          {errorMessage}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button onClick={onConnect} disabled={isConnecting} variant={isConnected ? "outline" : "default"}>
          {isConnecting ? (
            <Loader2 aria-hidden className="size-4 animate-spin" />
          ) : (
            <MessageCircle aria-hidden className="size-4" />
          )}
          {isConnected ? "Reconnect" : "Connect Telegram"}
        </Button>
        {isConnected ? (
          <Button variant="ghost" onClick={onDisconnect} disabled={isDisconnecting}>
            <Unplug aria-hidden className="size-4" />
            {isDisconnecting ? "Disconnecting..." : "Disconnect"}
          </Button>
        ) : null}
        <Button variant="link" className="ml-auto" onClick={onShowInstructions}>
          <HelpCircle aria-hidden className="size-4" />
          How it works
        </Button>
      </div>
    </Card>
  )
}
