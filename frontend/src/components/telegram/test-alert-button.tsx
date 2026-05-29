import { useEffect, useState } from "react"
import { CheckCircle2, Loader2, Send, XCircle } from "lucide-react"
import { useMutation } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { sendTelegramTestAlert } from "@/services/telegram-service"
import { cn } from "@/lib/utils"
import { getErrorMessage } from "@/utils/errors"

type TestAlertButtonProps = {
  enabled: boolean
}

type ToastState = {
  message: string
  tone: "success" | "error"
}

export function TestAlertButton({ enabled }: TestAlertButtonProps) {
  const [toast, setToast] = useState<ToastState | null>(null)
  const mutation = useMutation({
    mutationFn: () => sendTelegramTestAlert(),
    onSuccess: () =>
      setToast({
        message: "Test alert sent to your Telegram account.",
        tone: "success",
      }),
    onError: (error) =>
      setToast({
        message: getErrorMessage(error, "Unable to send Telegram test alert."),
        tone: "error",
      }),
  })

  useEffect(() => {
    if (!toast) {
      return
    }
    const timer = window.setTimeout(() => setToast(null), 3500)
    return () => window.clearTimeout(timer)
  }, [toast])

  return (
    <div className="glass-panel p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Test alert</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Send a live Telegram alert to confirm delivery.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={!enabled || mutation.isPending}
        >
          {mutation.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Send className="size-4" />
          )}
          {mutation.isPending ? "Sending..." : "Send Test Alert"}
        </Button>
      </div>
      {!enabled ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Connect your Telegram account to enable test alerts.
        </p>
      ) : null}

      {toast ? (
        <div
          className={cn(
            "mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold",
            toast.tone === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
              : "border-rose-500/30 bg-rose-500/10 text-rose-200"
          )}
          role="status"
          aria-live="polite"
        >
          {toast.tone === "success" ? (
            <CheckCircle2 className="size-4" />
          ) : (
            <XCircle className="size-4" />
          )}
          {toast.message}
        </div>
      ) : null}
    </div>
  )
}
