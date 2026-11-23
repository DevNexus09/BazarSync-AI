export function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-BD", {
    style: "currency",
    currency: "BDT",
    maximumFractionDigits: 0,
  }).format(value)
}

export function formatOptionalCurrency(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "Not available"
  }
  return formatCurrency(value)
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-BD").format(value)
}

export function formatPercent(value: number) {
  return `${value.toFixed(1)}%`
}

export function formatOptionalPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "Not available"
  }
  return formatPercent(value)
}

export function formatDateTime(value?: string | null) {
  if (!value) {
    return "Not available"
  }
  return new Intl.DateTimeFormat("en-BD", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

/** Decimal string or number from the API. Strings are formatted exactly, never through a float. */
export type DecimalValue = string | number

/** Money for display, e.g. "৳349.50". Returns null for missing values so callers can say why. */
export function formatMoney(
  value: DecimalValue | null | undefined,
  currency = "BDT",
): string | null {
  if (value == null || value === "") {
    return null
  }
  if (typeof value === "string" && !/^-?\d+(\.\d+)?$/.test(value.trim())) {
    return null
  }
  // Intl formats a numeric string as an exact decimal (ES2023 Intl.NumberFormat v3).
  return new Intl.NumberFormat("en-BD", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    trailingZeroDisplay: "stripIfInteger",
  }).format(
    (typeof value === "string" ? value.trim() : value) as Intl.StringNumericLiteral,
  )
}

/** "2 hours ago", "in 3 days". Rounds to the largest whole unit. */
export function formatRelativeTime(
  value: string | Date | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!value) {
    return null
  }
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000)
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ]
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) {
      return rtf.format(Math.round(seconds / size), unit)
    }
  }
  return rtf.format(0, "second")
}

/** Age of a timestamp in hours, or null when unknown. */
export function hoursSince(
  value: string | Date | null | undefined,
  now: Date = new Date(),
): number | null {
  if (!value) {
    return null
  }
  const time = (value instanceof Date ? value : new Date(value)).getTime()
  return Number.isNaN(time) ? null : (now.getTime() - time) / 3_600_000
}
