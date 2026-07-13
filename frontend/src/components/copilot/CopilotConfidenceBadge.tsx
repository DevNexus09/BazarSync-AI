import { cn } from "@/lib/utils"
import type { CopilotConfidence } from "@/types/copilot"

const confidenceStyles: Record<CopilotConfidence, string> = {
  HIGH: "border-emerald-400/40 bg-emerald-500/15 text-emerald-200",
  MEDIUM: "border-sky-400/40 bg-sky-500/15 text-sky-200",
  LOW: "border-amber-400/40 bg-amber-500/15 text-amber-100",
  NO_CONTEXT: "border-slate-400/40 bg-slate-500/15 text-slate-200",
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

