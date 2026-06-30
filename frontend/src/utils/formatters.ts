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
