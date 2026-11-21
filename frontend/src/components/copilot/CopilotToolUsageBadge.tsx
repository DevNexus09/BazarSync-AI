import { Wrench } from "lucide-react"

import { domainLabel, toolLabel } from "@/components/copilot/copilot-i18n"
import { cn } from "@/lib/utils"
import type { CopilotToolUsed } from "@/types/copilot"

export function CopilotToolUsageBadge({ tool }: { tool: CopilotToolUsed }) {
  const succeeded = tool.status.toUpperCase() === "SUCCEEDED"
  const rawName = tool.name ?? tool.tool_name ?? "tool"
  const name = toolLabel(rawName)
  const title = [
    `${name}: ${tool.status}`,
    tool.domain ? `Domain: ${domainLabel(tool.domain)}` : null,
    typeof tool.evidence_count === "number" ? `Evidence: ${tool.evidence_count}` : null,
    typeof tool.missing_data_count === "number" ? `Missing: ${tool.missing_data_count}` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        succeeded ? "border-success/30 bg-success/10 text-success" : "border-warning/30 bg-warning/10 text-warning"
      )}
      title={title}
    >
      <Wrench className="size-3" aria-hidden="true" />
      <span className="truncate">{name}</span>
      {tool.domain ? <span className="text-muted-foreground">{domainLabel(tool.domain)}</span> : null}
      <span className="text-muted-foreground">{tool.status}</span>
    </span>
  )
}
