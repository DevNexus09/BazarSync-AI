import { Wrench } from "lucide-react"

import { cn } from "@/lib/utils"
import type { CopilotToolUsed } from "@/types/copilot"

export function CopilotToolUsageBadge({ tool }: { tool: CopilotToolUsed }) {
  const succeeded = tool.status.toUpperCase() === "SUCCEEDED"
  const name = tool.name ?? tool.tool_name ?? "tool"
  const title = [
    `${name}: ${tool.status}`,
    tool.domain ? `Domain: ${tool.domain}` : null,
    typeof tool.evidence_count === "number" ? `Evidence: ${tool.evidence_count}` : null,
    typeof tool.missing_data_count === "number" ? `Missing: ${tool.missing_data_count}` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        succeeded
          ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
          : "border-amber-400/30 bg-amber-500/10 text-amber-100"
      )}
      title={title}
    >
      <Wrench className="size-3" aria-hidden="true" />
      <span className="truncate">{name}</span>
      {tool.domain ? <span className="text-muted-foreground">{tool.domain}</span> : null}
      <span className="text-muted-foreground">{tool.status}</span>
    </span>
  )
}
