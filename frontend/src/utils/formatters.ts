export function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-BD", {
    style: "currency",
    currency: "BDT",
    maximumFractionDigits: 0,
  }).format(value)
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-BD").format(value)
}

export function formatPercent(value: number) {
  return `${value.toFixed(1)}%`
}
