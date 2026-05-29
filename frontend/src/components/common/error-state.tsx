import type { ReactNode } from "react"

type ErrorStateProps = {
  title?: string
  message?: string
  action?: ReactNode
}

export function ErrorState({
  title = "Something went wrong",
  message = "Please try again.",
  action,
}: ErrorStateProps) {
  return (
  <div className="flex w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border/60 bg-card/60 p-6 text-center">
      <div className="text-sm font-semibold text-foreground">{title}</div>
      <div className="text-sm text-muted-foreground">{message}</div>
      {action ? <div>{action}</div> : null}
    </div>
  )
}
