import { Maximize2, Minimize2, Sparkles, X } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

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
      className="copilot-root flex h-full flex-col overflow-hidden border-border/70 bg-card shadow-[0_24px_70px_rgb(var(--overlay)/.5)] sm:rounded-2xl sm:border"
    >
      <header
        className={cn(
          "flex items-center gap-2.5 border-b border-border/60 bg-gradient-to-b from-primary/10 to-transparent px-3 pb-2.5 pt-[max(0.625rem,env(safe-area-inset-top))]",
          expanded && "sm:px-5 sm:py-3"
        )}
      >
        <div className="relative flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary/60 text-primary-foreground shadow-sm">
          <Sparkles className="size-4" aria-hidden="true" />
          <span
            aria-hidden="true"
            className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-card bg-emerald-400"
          />
        </div>
        <div className="min-w-0 flex-1">
          <h2 id="copilot-chat-title" className="truncate text-sm font-semibold leading-5 text-foreground">
            {title}
          </h2>
          <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
        </div>
        {actions}
        <span aria-hidden="true" className="mx-0.5 hidden h-5 w-px bg-border/70 sm:block" />
        {onToggleExpanded ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="hidden size-8 text-muted-foreground hover:text-foreground sm:inline-flex"
            aria-label="Full page"
            title={expanded ? "Back to side panel" : "Full page"}
            aria-pressed={expanded}
            onClick={onToggleExpanded}
          >
            {expanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </Button>
        ) : null}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground"
          aria-label="Close AI Business Copilot"
          title="Close"
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </header>
      {children}
    </section>
  )
}
