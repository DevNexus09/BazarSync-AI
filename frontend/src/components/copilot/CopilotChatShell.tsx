import { Bot, Maximize2, Minimize2, Minus } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"

export function CopilotChatShell({
  children,
  onClose,
  title = "AI Business Copilot",
  subtitle = "Seller-scoped business answers",
  actions,
  expanded = false,
  onToggleExpanded,
}: {
  children: ReactNode
  onClose: () => void
  title?: string
  subtitle?: string
  /** Header controls such as the language selector, history and new chat. */
  actions?: ReactNode
  expanded?: boolean
  onToggleExpanded?: () => void
}) {
  return (
    <section
      role="dialog"
      aria-modal="false"
      aria-labelledby="copilot-chat-title"
      className="copilot-root flex h-full flex-col overflow-hidden border-border/70 bg-card shadow-[0_18px_60px_rgb(var(--overlay)/.45)] sm:rounded-2xl sm:border"
    >
      <header className="flex items-center gap-2 border-b border-border/60 bg-background/60 px-3 py-2.5">
        <div className="hidden size-8 shrink-0 items-center justify-center rounded-full bg-primary/12 text-primary sm:flex">
          <Bot className="size-4" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 id="copilot-chat-title" className="truncate text-sm font-semibold text-foreground">
            {title}
          </h2>
          <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
        </div>
        {actions}
        {onToggleExpanded ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="hidden sm:inline-flex"
            aria-label="Full page"
            title={expanded ? "Back to side panel" : "Full page"}
            aria-pressed={expanded}
            onClick={onToggleExpanded}
          >
            {expanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </Button>
        ) : null}
        <Button type="button" variant="ghost" size="icon" aria-label="Close AI Business Copilot" onClick={onClose}>
          <Minus className="size-4" />
        </Button>
      </header>
      {children}
    </section>
  )
}
