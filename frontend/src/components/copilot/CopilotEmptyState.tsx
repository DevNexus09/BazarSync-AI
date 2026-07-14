import { Sparkles } from "lucide-react"

import { CopilotSuggestedQuestions } from "@/components/copilot/CopilotSuggestedQuestions"

export function CopilotEmptyState({
  onSuggestedQuestion,
  disabled,
}: {
  onSuggestedQuestion: (question: string) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-4 rounded-xl border border-border/60 bg-muted/20 p-4">
      <div className="flex items-start gap-3">
        <div className="rounded-full border border-info/30 bg-info/15 p-2 text-info">
          <Sparkles className="size-4" aria-hidden="true" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Ask your AI Business Copilot
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Get answers from your inventory, pricing, competitor, promotion, and
            business memory data.
          </p>
        </div>
      </div>
      <CopilotSuggestedQuestions
        onSelect={onSuggestedQuestion}
        disabled={disabled}
      />
    </div>
  )
}
