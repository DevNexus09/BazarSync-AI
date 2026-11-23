import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"

import { ui } from "@/lib/ui-i18n"
import { formatDateTime } from "@/utils/formatters"

/** Collapsed home for internal detail (formula, version, freshness, assumptions). */
export function HowCalculated({
  formula,
  version,
  calculatedAt,
  assumptions,
  children,
}: {
  formula?: string | null
  version?: string | null
  calculatedAt?: string | null
  assumptions?: string[]
  children?: ReactNode
}) {
  return (
    <details className="group rounded-lg border border-border/60 bg-muted/20 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-1 px-3 py-2 font-medium text-foreground">
        <ChevronRight aria-hidden className="size-4 transition group-open:rotate-90" />
        {ui("howCalculated")}
      </summary>
      <dl className="grid gap-x-4 gap-y-1 px-3 pb-3 text-muted-foreground sm:grid-cols-[auto_1fr]">
        {formula ? (
          <>
            <dt className="font-medium text-foreground">{ui("formula")}</dt>
            <dd className="break-words font-mono text-xs">{formula}</dd>
          </>
        ) : null}
        {version ? (
          <>
            <dt className="font-medium text-foreground">{ui("version")}</dt>
            <dd>{version}</dd>
          </>
        ) : null}
        {calculatedAt ? (
          <>
            <dt className="font-medium text-foreground">{ui("lastUpdated")}</dt>
            <dd>{formatDateTime(calculatedAt)}</dd>
          </>
        ) : null}
        {assumptions?.length ? (
          <>
            <dt className="font-medium text-foreground">{ui("assumptions")}</dt>
            <dd>
              <ul className="list-disc pl-4">
                {assumptions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>
      {children ? <div className="px-3 pb-3">{children}</div> : null}
    </details>
  )
}
