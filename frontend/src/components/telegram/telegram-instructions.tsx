import { useEffect, useState } from "react"
import { CheckCircle2, Copy, RefreshCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/common/error-state"
import { getErrorMessage } from "@/utils/errors"

export type TelegramInstructionsProps = {
  token?: string
  expiresAt?: string | null
  botUsername?: string | null
  isLoading: boolean
  error?: unknown
  onRefresh: () => void
}

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return "soon"
  }
  return new Date(value).toLocaleString()
}

export function TelegramInstructions({
  token,
  expiresAt,
  botUsername,
  isLoading,
  error,
  onRefresh,
}: TelegramInstructionsProps) {
  const [copied, setCopied] = useState(false)
  const command = token ? `/connect ${token}` : "/connect <token>"
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  useEffect(() => {
    if (!copied) {
      return
    }
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  if (isLoading) {
    return (
      <div className="glass-panel p-5">
        <div className="h-5 w-40 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 space-y-2">
          <div className="h-6 w-full animate-pulse rounded bg-muted/30" />
          <div className="h-6 w-4/5 animate-pulse rounded bg-muted/30" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <ErrorState
        title="Unable to load connect instructions"
        message={getErrorMessage(error)}
        action={
          <Button variant="outline" size="sm" onClick={onRefresh}>
            Retry
          </Button>
        }
      />
    )
  }

  return (
    <div className="glass-panel p-5">
      <h3 className="text-sm font-semibold text-foreground">
        Bot connection instructions
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Follow these steps to link your Telegram account to BazarSync AI alerts.
      </p>

      <div className="mt-4 space-y-3 text-xs text-muted-foreground">
        {[
          "Open Telegram",
          `Search: ${botUsername ?? "@bazarsync_bot"}`,
          "Press Start on the bot",
          "Return to the dashboard",
        ].map((step, index) => (
          <div
            key={step}
            className="flex items-center gap-2 rounded-lg border border-border/60 bg-card/60 px-3 py-2"
          >
            <span className="flex size-5 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
              {index + 1}
            </span>
            <span>{step}</span>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-lg border border-border/60 bg-card/60 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
          <CheckCircle2 className="size-4 text-emerald-300" />
          Send this command in Telegram
        </div>
        <div className="mt-2 flex flex-col gap-2 rounded-md border border-border/60 bg-background/60 p-3">
          <code className="text-xs text-foreground">{command}</code>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="xs" onClick={handleCopy}>
              <Copy className="size-3.5" />
              {copied ? "Copied" : "Copy command"}
            </Button>
            <Button variant="ghost" size="xs" onClick={onRefresh}>
              <RefreshCcw className="size-3.5" />
              Generate new token
            </Button>
          </div>
        </div>
        {!token ? (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Click “Connect Telegram Bot” to generate a secure token.
          </p>
        ) : null}
        <p className="mt-2 text-[11px] text-muted-foreground">
          Token expires {formatDateTime(expiresAt)}.
        </p>
      </div>
    </div>
  )
}
