import { ui } from "@/lib/ui-i18n"
import { cn } from "@/lib/utils"

import { resolveStatus, TONE_CLASSES, type StatusKind } from "./status"

/** Status shown with icon, text and colour, so colour is never the only signal. */
export function StatusBadge({
  kind,
  value,
  className,
}: {
  kind: StatusKind
  value: string | null | undefined
  className?: string
}) {
  if (!value) {
    return null
  }
  const status = resolveStatus(kind, value)
  const Icon = status.icon
  return (
    <span
      data-tone={status.tone}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASSES[status.tone],
        className,
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {"label" in status ? ui(status.label) : status.text}
    </span>
  )
}
