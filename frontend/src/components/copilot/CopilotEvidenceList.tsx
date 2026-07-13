import { ChevronDown, FileText } from "lucide-react"

import type { CopilotEvidence } from "@/types/copilot"

export function CopilotEvidenceList({
  evidence,
}: {
  evidence: CopilotEvidence[]
}) {
  if (!evidence.length) {
    return null
  }

  return (
    <details className="rounded-lg border border-border/60 bg-background/70 p-2">
      <summary className="cursor-pointer text-xs font-semibold text-foreground">
        Evidence ({evidence.length})
      </summary>
      <ul className="mt-2 space-y-2">
        {evidence.map((item) => (
          <li key={item.evidence_id} className="text-xs text-muted-foreground">
            <details className="group rounded-md border border-border/40 bg-background/40 p-2">
              <summary className="flex cursor-pointer list-none gap-2">
                <FileText className="mt-0.5 size-3.5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate font-medium text-foreground">
                      {item.title || item.evidence_id}
                    </span>
                    {item.domain ? (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        {item.domain}
                      </span>
                    ) : null}
                    {item.freshness ? (
                      <span className={freshnessClass(item.freshness)}>
                        {item.freshness}
                      </span>
                    ) : null}
                  </div>
                  <p className="truncate">
                    {item.source_table || item.source_type} · {item.evidence_id}
                    {item.product_name ? ` · ${item.product_name}` : ""}
                    {item.event_time ? ` · ${formatDate(item.event_time)}` : ""}
                  </p>
                </div>
                <ChevronDown className="mt-0.5 size-3 shrink-0 transition group-open:rotate-180" />
              </summary>
              <div className="mt-2 space-y-1 pl-5">
                {item.summary ? <p>{item.summary}</p> : null}
                {item.snippet ? (
                  <blockquote className="rounded border-l-2 border-primary/60 bg-muted/30 px-2 py-1 text-foreground">
                    {item.snippet}
                  </blockquote>
                ) : null}
                <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1">
                  <dt>Source</dt>
                  <dd className="break-all">
                    {item.source_table || item.source_type}
                    {item.source_id ? `:${item.source_id}` : ""}
                  </dd>
                  {item.confidence ? (
                    <>
                      <dt>Confidence</dt>
                      <dd>{item.confidence}</dd>
                    </>
                  ) : null}
                  {item.path || item.url ? (
                    <>
                      <dt>Path</dt>
                      <dd className="break-all">{item.path || item.url}</dd>
                    </>
                  ) : null}
                </dl>
              </div>
            </details>
          </li>
        ))}
      </ul>
    </details>
  )
}

function freshnessClass(status: string) {
  const normalized = status.toUpperCase()
  if (normalized === "FRESH") {
    return "rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-200"
  }
  if (normalized === "STALE" || normalized === "MISSING") {
    return "rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-200"
  }
  return "rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
