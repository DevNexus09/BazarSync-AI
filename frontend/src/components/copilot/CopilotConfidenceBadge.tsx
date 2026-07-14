import { cn } from "@/lib/utils"
import type { CopilotConfidence } from "@/types/copilot"

const confidenceStyles: Record<CopilotConfidence, string> = {
  HIGH: "border-success/40 bg-success/15 text-success",
  MEDIUM: "border-info/40 bg-info/15 text-info",
  LOW: "border-warning/40 bg-warning/15 text-warning",
  NO_CONTEXT: "border-border-strong/40 bg-muted/60 text-muted-foreground",
}

export function CopilotConfidenceBadge({
  confidence,
}: {
  confidence: CopilotConfidence
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        confidenceStyles[confidence]
      )}
    >
      Confidence: {confidence.replace("_", " ")}
    </span>
  )
}
