import { AlertTriangle } from "lucide-react"
import { Link } from "react-router-dom"

import { domainLabel, t, type CopilotUiLanguage } from "@/components/copilot/copilot-i18n"
import type { CopilotMissingData } from "@/types/copilot"

export function CopilotMissingDataPanel({
  missingData,
  language = "en",
}: {
  missingData: CopilotMissingData[]
  language?: CopilotUiLanguage
}) {
  if (!missingData.length) {
    return null
  }

  return (
    <div className="rounded-lg border border-warning/40 bg-warning/10 p-2 text-xs text-foreground">
      <div className="mb-1 flex items-center gap-1.5 font-semibold text-warning">
        <AlertTriangle className="size-3.5" aria-hidden="true" />
        Missing business data
      </div>
      <div className="space-y-2">
        {Object.entries(groupByDomain(missingData)).map(([domain, items]) => (
          <section key={domain}>
            <p className="mb-1 font-medium">{domain === "UNKNOWN" ? "UNKNOWN" : domainLabel(domain, language)}</p>
            <ul className="space-y-1">
              {items.map((item, index) => (
                <li key={`${item.key ?? "missing"}-${index}`} className="rounded bg-background/70 p-1.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{item.message}</span>
                    <span
                      className={
                        item.blocking
                          ? "rounded bg-destructive/15 px-1.5 py-0.5 text-[10px] text-destructive"
                          : "rounded bg-warning/15 px-1.5 py-0.5 text-[10px] text-warning"
                      }
                    >
                      {item.blocking ? "Blocking" : "Optional"}
                    </span>
                  </div>
                  {item.source_table ? (
                    <p className="mt-0.5 text-muted-foreground">Source: {item.source_table}</p>
                  ) : null}
                  {item.required_for?.length ? (
                    <p className="mt-0.5 text-muted-foreground">Required for: {item.required_for.join(", ")}</p>
                  ) : null}
                  {item.next_action ? <p className="mt-0.5">Next: {item.next_action}</p> : null}
                  {item.setup_href ? <SetupLink href={item.setup_href} label={t(language, "openSetup")} /> : null}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}

function SetupLink({ href, label }: { href: string; label: string }) {
  // In-app paths use the router (no full reload); anything else stays a plain link.
  if (href.startsWith("/") && !href.startsWith("//")) {
    return (
      <Link className="mt-1 inline-block underline" to={href}>
        {label}
      </Link>
    )
  }
  return (
    <a className="mt-1 inline-block underline" href={href} rel="noreferrer">
      {label}
    </a>
  )
}

function groupByDomain(items: CopilotMissingData[]) {
  return items.reduce<Record<string, CopilotMissingData[]>>((groups, item) => {
    const domain = item.domain || "UNKNOWN"
    groups[domain] = [...(groups[domain] ?? []), item]
    return groups
  }, {})
}
