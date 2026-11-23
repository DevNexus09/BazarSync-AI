import { History } from "lucide-react"

import { useTrackRecord } from "@/hooks/use-track-record"
import { ui, type UiStringKey } from "@/lib/ui-i18n"
import type { OutcomeType } from "@/services/recommendation-outcome-service"

const COPY: Record<OutcomeType, UiStringKey> = { REORDER: "trackRecordReorder", PRICING: "trackRecordPricing" }

/** Shown only once enough outcomes exist to mean something. */
export function TrackRecordLine({ type }: { type: OutcomeType }) {
  const record = useTrackRecord(type)
  const data = record.data
  if (!data?.enabled || !data.overall.reliable || data.overall.hitRate == null) {
    return null
  }
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <History aria-hidden className="size-4" />
      {ui(COPY[type], { percent: Math.round(data.overall.hitRate * 100), days: data.days, count: data.overall.outcomes })}
    </p>
  )
}
