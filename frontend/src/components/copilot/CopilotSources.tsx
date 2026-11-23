import type { ReactNode } from "react"
import { ChevronRight, CircleSlash, Database, History } from "lucide-react"

import { t, toolLabel, type CopilotStringKey, type CopilotUiLanguage } from "@/components/copilot/copilot-i18n"
import { cn } from "@/lib/utils"
import type { CopilotLocalMessage } from "@/types/copilot"

type AssistantMessage = Extract<CopilotLocalMessage, { role: "assistant" }>

const freshnessTone: Record<string, string> = {
  FRESH: "border-success/30 bg-success/10 text-success",
  STALE: "border-warning/35 bg-warning/10 text-warning",
  MISSING: "border-destructive/30 bg-destructive/10 text-destructive",
}

/** What the answer was built from, collapsed by default so the answer stays first. */
export function CopilotSources({ message, language }: { message: AssistantMessage; language: CopilotUiLanguage }) {
  const tools = message.toolsUsed.filter((tool) => tool.tool_name || tool.name)
  const memory = message.evidence
  const missing = message.missingData.filter((item) => item.message)
  if (!tools.length && !memory.length && !missing.length) {
    return null
  }

  return (
    <details className="group mt-3 rounded-xl border border-border/60 bg-background/50 text-xs open:bg-background/80">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-xl px-2.5 py-2 font-medium text-muted-foreground transition hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform duration-200 group-open:rotate-90 motion-reduce:transition-none" aria-hidden="true" />
        {t(language, "sources")}
        <span className="rounded-full bg-muted px-1.5 tabular-nums text-[11px] text-foreground/80">{tools.length + memory.length}</span>
      </summary>
      <div className="space-y-3 border-t border-border/50 px-2.5 pb-2.5 pt-2">
        {tools.length ? (
          <SourceGroup icon={<Database className="size-3.5" aria-hidden="true" />} title={t(language, "sourcesData")}>
            {tools.map((tool, index) => (
              <li key={`${tool.tool_name ?? tool.name}-${index}`} className="flex items-baseline justify-between gap-2">
                <span className="text-foreground">{toolLabel(String(tool.tool_name ?? tool.name))}</span>
                {tool.status !== "SUCCEEDED" ? <span className="text-muted-foreground">{t(language, "unavailable")}</span> : null}
              </li>
            ))}
          </SourceGroup>
        ) : null}
        {memory.length ? (
          <SourceGroup icon={<History className="size-3.5" aria-hidden="true" />} title={t(language, "sourcesMemory")}>
            {memory.map((item) => (
              <li key={item.evidence_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="min-w-0 flex-1 text-foreground">{item.title}</span>
                {item.event_time ? <time className="tabular-nums text-muted-foreground">{item.event_time.slice(0, 10)}</time> : null}
                {item.freshness ? <FreshnessBadge status={item.freshness} language={language} /> : null}
              </li>
            ))}
          </SourceGroup>
        ) : null}
        {missing.length ? (
          <SourceGroup icon={<CircleSlash className="size-3.5" aria-hidden="true" />} title={t(language, "notRecorded")}>
            {missing.map((item, index) => (
              <li key={`${item.key ?? "missing"}-${index}`} className="text-muted-foreground">
                {item.message}
              </li>
            ))}
          </SourceGroup>
        ) : null}
      </div>
    </details>
  )
}

function SourceGroup({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
        {icon}
        {title}
      </h4>
      <ul className="space-y-1 pl-5">{children}</ul>
    </section>
  )
}

function FreshnessBadge({ status, language }: { status: string; language: CopilotUiLanguage }) {
  const key = (["FRESH", "STALE", "MISSING"].includes(status) ? `fresh${status}` : "freshUNKNOWN") as CopilotStringKey
  return (
    <span className={cn("rounded-full border px-1.5 text-[10.5px] font-medium", freshnessTone[status] ?? "border-border/70 text-muted-foreground")}>
      {t(language, key)}
    </span>
  )
}
