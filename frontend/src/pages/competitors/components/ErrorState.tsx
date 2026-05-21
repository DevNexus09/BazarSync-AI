import type { ReactNode } from "react"

import { ErrorState as BaseErrorState } from "@/components/common/error-state"
import { Button } from "@/components/ui/button"

type ErrorStateProps = {
  title?: string
  message?: string
  onRetry?: () => void
  retryLabel?: string
  action?: ReactNode
}

export function ErrorState({
  title = "Unable to load competitors",
  message = "Please try again.",
  onRetry,
  retryLabel = "Retry",
  action,
}: ErrorStateProps) {
  const fallbackAction = onRetry ? (
    <Button variant="outline" onClick={onRetry}>
      {retryLabel}
    </Button>
  ) : undefined

  return (
    <BaseErrorState
      title={title}
      message={message}
      action={action ?? fallbackAction}
    />
  )
}
