import { Sparkles } from "lucide-react"

export function CopilotEmptyState() {
  return (
    <div className="flex flex-col items-center px-4 py-10 text-center">
      <div className="rounded-full border border-primary/20 bg-primary/10 p-2.5 text-primary">
        <Sparkles className="size-5" aria-hidden="true" />
      </div>
      <h3 className="mt-3 text-sm font-semibold text-foreground">Ask your AI Business Copilot</h3>
      <p className="mt-1 max-w-xs text-xs leading-5 text-muted-foreground">
        Get answers from your inventory, pricing, competitor, promotion, and business memory data.
      </p>
    </div>
  )
}
