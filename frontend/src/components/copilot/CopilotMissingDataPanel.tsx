import { AlertTriangle } from "lucide-react"

import type { CopilotMissingData } from "@/types/copilot"

export function CopilotMissingDataPanel({
  missingData,
}: {
  missingData: CopilotMissingData[]
}) {
  if (!missingData.length) {
    return null
  }

  return (
    <div className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-2 text-xs text-amber-200">
      <div className="mb-1 flex items-center gap-1.5 font-semibold">
        <AlertTriangle className="size-3.5" aria-hidden="true" />
        Missing business data
      </div>
      <div className="space-y-2">
        {Object.entries(groupByDomain(missingData)).map(([domain, items]) => (
          <section key={domain}>
            <p className="mb-1 font-medium text-amber-100">{domain}</p>
            <ul className="space-y-1">
              {items.map((item, index) => (
                <li key={`${item.key ?? "missing"}-${index}`} className="rounded bg-background/70 p-1.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{item.message}</span>
                    <span className={item.blocking ? "rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-200" : "rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-100"}>
                      {item.blocking ? "Blocking" : "Optional"}
                    </span>
                  </div>
                  {item.source_table ? (
                    <p className="mt-0.5 text-amber-200/80">Source: {item.source_table}</p>
                  ) : null}
                  {item.required_for?.length ? (
                    <p className="mt-0.5 text-amber-100/80">
                      Required for: {item.required_for.join(", ")}
                    </p>
                  ) : null}
                  {item.next_action ? (
                    <p className="mt-0.5 text-amber-100">Next: {item.next_action}</p>
                  ) : null}
                  {item.setup_href ? (
                    <a className="mt-1 inline-block underline" href={item.setup_href}>
                      Open setup
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}

function groupByDomain(items: CopilotMissingData[]) {
  return items.reduce<Record<string, CopilotMissingData[]>>((groups, item) => {
    const domain = item.domain || "UNKNOWN"
    groups[domain] = [...(groups[domain] ?? []), item]
    return groups
  }, {})
}
