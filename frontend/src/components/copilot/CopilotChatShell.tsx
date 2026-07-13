import { Bot, Minus } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"

export function CopilotChatShell({
  children,
  onClose,
}: {
  children: ReactNode
  onClose: () => void
}) {
  return (
    <section
      role="dialog"
      aria-modal="false"
      aria-labelledby="copilot-chat-title"
      className="flex h-full flex-col overflow-hidden rounded-t-2xl border border-border/70 bg-card shadow-[0_18px_60px_rgba(2,6,23,0.45)] sm:rounded-2xl"
    >
      <header className="flex items-center gap-3 border-b border-border/60 bg-background/60 px-4 py-3">
        <div className="flex size-9 items-center justify-center rounded-full bg-primary/12 text-primary">
          <Bot className="size-4" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h2
            id="copilot-chat-title"
            className="truncate text-sm font-semibold text-foreground"
          >
            AI Business Copilot
          </h2>
          <p className="text-xs text-muted-foreground">Seller-scoped business answers</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Close AI Business Copilot"
          onClick={onClose}
        >
          <Minus className="size-4" />
        </Button>
      </header>
      {children}
    </section>
  )
}
