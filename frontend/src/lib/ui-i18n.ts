/**
 * Shared UI strings for the pricing and inventory pages. English ships now; add `bn`
 * entries to translate (same shape as components/copilot/copilot-i18n.ts).
 */
export type UiLanguage = "en" | "bn"

export type Entry = { en: string; bn?: string }

const strings = {
  updated: { en: "Updated {time}" },
  lastUpdated: { en: "Last updated" },
  neverUpdated: { en: "Not calculated yet" },
  stale: { en: "Stale" },
  refresh: { en: "Refresh" },
  howCalculated: { en: "How we calculated this" },
  formula: { en: "Formula" },
  version: { en: "Version" },
  assumptions: { en: "Assumptions" },
  search: { en: "Search" },
  rowsPerPage: { en: "Rows per page" },
  previous: { en: "Previous" },
  next: { en: "Next" },
  pageOf: { en: "Page {page} of {pages}" },
  noResults: { en: "No matching rows" },
  close: { en: "Close" },
  unavailable: { en: "Unavailable" },
  nextStep: { en: "Next: {action}" },
  statusLow: { en: "Low risk" },
  statusMedium: { en: "Medium risk" },
  statusHigh: { en: "High risk" },
  statusCritical: { en: "Critical" },
  statusSufficient: { en: "Good data" },
  statusLimited: { en: "Limited data" },
  statusInsufficient: { en: "Not enough data" },
  statusStale: { en: "Out of date" },
  statusNoAction: { en: "OK" },
  statusMonitor: { en: "Keep an eye on" },
  statusReorder: { en: "Reorder" },
  statusUrgentReorder: { en: "Reorder now" },
  statusExpedite: { en: "Rush order" },
  statusHealthy: { en: "Selling well" },
  statusSlowMoving: { en: "Slow" },
  statusAtRisk: { en: "At risk" },
  statusDeadStock: { en: "Dead stock" },
  statusPriceLower: { en: "Lower price" },
  statusPriceRaise: { en: "Raise price" },
  statusHold: { en: "Hold" },
  trackRecordReorder: { en: "Track record: our reorder dates were right {percent}% of the time in the last {days} days ({count} orders checked)." },
  trackRecordPricing: { en: "Track record: prices you applied from our suggestions moved profit the way we predicted {percent}% of the time in the last {days} days ({count} checked)." },
} satisfies Record<string, Entry>

export type UiStringKey = keyof typeof strings

/** Build a lookup for a feature's own string map; same fallback and `{name}` filling as `ui`. */
export function createStrings<T extends Record<string, Entry>>(map: T) {
  return (key: keyof T, params?: Record<string, string | number>, language: UiLanguage = "en"): string =>
    fill((language === "bn" && map[key].bn) || map[key].en, params)
}

function fill(text: string, params?: Record<string, string | number>): string {
  return params ? text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match)) : text
}

/** Look up a string, falling back to English, and fill `{name}` placeholders. */
export function ui(
  key: UiStringKey,
  params?: Record<string, string | number>,
  language: UiLanguage = "en",
): string {
  const entry: Entry = strings[key]
  return fill((language === "bn" && entry.bn) || entry.en, params)
}
