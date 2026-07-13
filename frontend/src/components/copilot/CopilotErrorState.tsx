import { AlertTriangle } from "lucide-react"

export function CopilotErrorState({ message }: { message?: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-red-100"
    >
      <div className="flex items-center gap-2 font-semibold">
        <AlertTriangle className="size-3.5" aria-hidden="true" />
        Copilot could not answer right now.
      </div>
      <p className="mt-1 text-red-100/90">
        {message ?? "Please try again."}
      </p>
    </div>
  )
}

