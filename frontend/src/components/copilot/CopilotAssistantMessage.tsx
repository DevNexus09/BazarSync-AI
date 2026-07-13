import { CopilotActionProposalCard } from "@/components/copilot/CopilotActionProposalCard"
import { CopilotConfidenceBadge } from "@/components/copilot/CopilotConfidenceBadge"
import { CopilotEvidenceList } from "@/components/copilot/CopilotEvidenceList"
import { CopilotMissingDataPanel } from "@/components/copilot/CopilotMissingDataPanel"
import { CopilotToolUsageBadge } from "@/components/copilot/CopilotToolUsageBadge"
import type { CopilotActionProposal, CopilotLocalMessage } from "@/types/copilot"

const noContextNextActions = [
  "Add product setup data",
  "Import sales records",
  "Run memory indexing",
  "Set up marketplace fees",
  "Add visibility metrics",
]

export function CopilotAssistantMessage({
  message,
  onProposalChange,
}: {
  message: Extract<CopilotLocalMessage, { role: "assistant" }>
  onProposalChange?: (proposal: CopilotActionProposal) => void
}) {
  return (
    <article className="rounded-2xl rounded-bl-md border border-border/60 bg-card p-3 text-sm text-foreground shadow-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <CopilotConfidenceBadge confidence={message.confidence} />
        {message.domainsUsed.map((domain) => (
          <span
            key={domain}
            className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground"
          >
            {domain}
          </span>
        ))}
      </div>
      <div className="whitespace-pre-wrap leading-6">{message.content}</div>
      {message.memoryCoverageWarning ? (
        <div className="mt-3 rounded-lg border border-amber-400/40 bg-amber-500/10 p-2 text-xs text-amber-200">
          Some business history is not indexed yet. Answers may rely on current
          database data only.
        </div>
      ) : null}
      {message.confidence === "NO_CONTEXT" ? (
        <div className="mt-3 rounded-lg border border-amber-400/40 bg-amber-500/10 p-2 text-xs text-amber-200">
          <p className="font-semibold">
            Not enough seller-specific business data was found to answer this
            reliably.
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-4">
            {noContextNextActions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {message.recommendedNextSteps.length ? (
        <div className="mt-3">
          <p className="text-xs font-semibold text-muted-foreground">Next steps</p>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {message.recommendedNextSteps.map((step, index) => (
              <li key={`${step}-${index}`}>{step}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="mt-3 space-y-2">
        <CopilotMissingDataPanel missingData={message.missingData} />
        {message.dataFreshness.some((item) =>
          ["STALE", "MISSING", "UNKNOWN"].includes(item.status?.toUpperCase?.() ?? "")
        ) ? (
          <div className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-2 text-xs text-amber-200">
            <p className="font-semibold">Data freshness warnings</p>
            <ul className="mt-1 space-y-1">
              {message.dataFreshness
                .filter((item) =>
                  ["STALE", "MISSING", "UNKNOWN"].includes(item.status?.toUpperCase?.() ?? "")
                )
                .map((item, index) => (
                  <li key={`${item.domain}-${item.source_table ?? "source"}-${index}`}>
                    {item.domain}
                    {item.source_table ? ` · ${item.source_table}` : ""}: {item.message}
                  </li>
                ))}
            </ul>
          </div>
        ) : null}
        {message.toolsUsed.length ? (
          <div className="flex flex-wrap gap-1.5">
            {message.toolsUsed.map((tool) => (
              <CopilotToolUsageBadge
                key={`${tool.name ?? tool.tool_name}-${tool.status}`}
                tool={tool}
              />
            ))}
          </div>
        ) : null}
        <CopilotEvidenceList evidence={message.evidence} />
        {message.actionProposal ? (
          <CopilotActionProposalCard
            proposal={message.actionProposal}
            onStatusChange={onProposalChange}
          />
        ) : null}
      </div>
    </article>
  )
}
