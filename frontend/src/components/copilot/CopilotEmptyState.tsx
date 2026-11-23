import { Sparkles } from "lucide-react"

export function CopilotEmptyState() {
  return (
    <div className="flex flex-col items-center px-4 py-10 text-center">
      <div className="relative">
        <div aria-hidden="true" className="absolute inset-0 rounded-2xl bg-primary/40 blur-xl" />
        <div className="relative flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-primary/60 text-primary-foreground shadow-lg">
          <Sparkles className="size-6" aria-hidden="true" />
        </div>
      </div>
      <h3 className="mt-5 text-base font-semibold text-foreground">Ask your AI Business Copilot</h3>
      <p className="mt-1.5 max-w-sm text-sm leading-6 text-muted-foreground">
        Get answers from your inventory, pricing, competitor, promotion, and business memory data.
      </p>
    </div>
  )
}
