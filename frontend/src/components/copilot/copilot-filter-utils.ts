import type { CopilotSourceMode } from "@/types/copilot"

export type CopilotDateRangeKey =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "this_month"
  | "last_month"
  | "custom"

export type CopilotDateRangeValue = {
  key: CopilotDateRangeKey
  fromDate: string
  toDate: string
}

export const copilotSourceModes: Array<{
  value: CopilotSourceMode
  label: string
}> = [
  { value: "current", label: "Use current database data" },
  { value: "memory", label: "Use business memory" },
  { value: "both", label: "Use both" },
]

export function resolveDateRange(
  key: CopilotDateRangeKey,
  previous?: CopilotDateRangeValue
): CopilotDateRangeValue {
  if (key === "custom") {
    const today = formatDate(new Date())
    return {
      key,
      fromDate: previous?.fromDate || today,
      toDate: previous?.toDate || today,
    }
  }

  const now = new Date()
  const start = new Date(now)
  const end = new Date(now)

  if (key === "yesterday") {
    start.setDate(start.getDate() - 1)
    end.setDate(end.getDate() - 1)
  }

  if (key === "last_7_days") {
    start.setDate(start.getDate() - 6)
  }

  if (key === "last_30_days") {
    start.setDate(start.getDate() - 29)
  }

  if (key === "this_month") {
    start.setDate(1)
  }

  if (key === "last_month") {
    start.setMonth(start.getMonth() - 1, 1)
    end.setDate(0)
  }

  return {
    key,
    fromDate: formatDate(start),
    toDate: formatDate(end),
  }
}

function formatDate(date: Date) {
  return date.toISOString().slice(0, 10)
}
