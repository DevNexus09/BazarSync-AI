import type { DeadStockProduct } from "@/types/dead-stock"
import type { InventoryIntelligenceItem } from "@/types/inventory-intelligence"

import { t } from "./inventory-i18n"

const DAY_MS = 86_400_000
/** Statuses where the seller already acted, so the item leaves the to-do list. */
const HANDLED = new Set(["ORDERED", "DISMISSED"])

export type TodoPriority = "out_of_stock" | "before_lead_time" | "deadline_soon" | "dead_stock"
export type TodoItem = {
  key: string
  productId: string
  priority: TodoPriority
  tone: "danger" | "warning" | "info"
  text: string
}

export function daysUntil(isoDate: string | null | undefined, today: Date): number | null {
  if (!isoDate) return null
  const target = Date.parse(`${isoDate.slice(0, 10)}T00:00:00Z`)
  const start = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
  return Number.isNaN(target) ? null : Math.round((target - start) / DAY_MS)
}

export function shortDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(`${isoDate.slice(0, 10)}T00:00:00Z`),
  )
}

/** "Runs out in 6 days (26 Nov)", "Out of stock", or null when not predicted. */
export function runsOutText(item: Pick<InventoryIntelligenceItem, "daysRemaining" | "predictedStockoutDate">): string | null {
  if (item.daysRemaining == null) return null
  if (item.daysRemaining <= 0) return t("outOfStock")
  const days = Math.max(1, Math.floor(item.daysRemaining))
  const unit = days === 1 ? t("day") : t("days")
  return item.predictedStockoutDate
    ? t("runsOutOn", { days, unit, date: shortDate(item.predictedStockoutDate) })
    : t("runsOut", { days, unit })
}

const isOut = (item: InventoryIntelligenceItem) => item.daysRemaining != null && item.daysRemaining <= 0
const openReorder = (item: InventoryIntelligenceItem) =>
  item.reorderAction === "REORDER" && !HANDLED.has(item.recommendationStatus ?? "")

/**
 * Ranked "To do today": out of stock > runs out before new stock can arrive >
 * reorder deadline within 3 days > dead stock holding the most cash.
 */
export function buildTodoList(
  items: InventoryIntelligenceItem[],
  deadStock: DeadStockProduct[],
  today: Date,
  limit = 8,
): TodoItem[] {
  const out: TodoItem[] = []
  const seen = new Set<string>()
  const add = (item: TodoItem) => {
    if (!seen.has(item.productId)) {
      seen.add(item.productId)
      out.push(item)
    }
  }
  const byDays = (a: InventoryIntelligenceItem, b: InventoryIntelligenceItem) => (a.daysRemaining ?? 0) - (b.daysRemaining ?? 0)
  const active = items.filter((item) => !HANDLED.has(item.recommendationStatus ?? ""))

  for (const item of active.filter(isOut)) {
    const text = openReorder(item) && item.recommendedQuantity
      ? t("todoOutOrder", { name: item.productName, quantity: item.recommendedQuantity })
      : t("todoOut", { name: item.productName })
    add({ key: `out-${item.productId}`, productId: item.productId, priority: "out_of_stock", tone: "danger", text })
  }
  for (const item of active
    .filter((item) => !isOut(item) && item.daysRemaining != null && item.supplierLeadTimeDays != null && item.daysRemaining < item.supplierLeadTimeDays)
    .sort(byDays)) {
    add({
      key: `lead-${item.productId}`,
      productId: item.productId,
      priority: "before_lead_time",
      tone: "danger",
      text: t("todoBeforeLead", { name: item.productName, runway: runsOutText(item)?.toLowerCase() ?? "", lead: item.supplierLeadTimeDays ?? 0 }),
    })
  }
  for (const item of active
    .filter((item) => openReorder(item) && (daysUntil(item.reorderDeadline, today) ?? Infinity) <= 3)
    .sort((a, b) => (a.reorderDeadline ?? "").localeCompare(b.reorderDeadline ?? ""))) {
    const by = daysUntil(item.reorderDeadline, today)! <= 0 ? t("todoDeadlineToday") : t("todoDeadlineBy", { date: shortDate(item.reorderDeadline!) })
    add({
      key: `deadline-${item.productId}`,
      productId: item.productId,
      priority: "deadline_soon",
      tone: "warning",
      text: t("todoDeadline", { name: item.productName, quantity: item.recommendedQuantity ?? t("todoMore"), by }),
    })
  }
  for (const product of deadStock
    .filter((row) => row.classification === "DEAD_STOCK" && row.lockedCapital != null && row.lockedCapital > 0)
    .sort((a, b) => (b.lockedCapital ?? 0) - (a.lockedCapital ?? 0))) {
    const idle = product.daysSinceLastSale == null ? t("idleSlow") : t("idleDays", { days: product.daysSinceLastSale })
    const text = product.primaryRecommendation
      ? t("todoDeadAction", { name: product.productName, idle, action: recoveryActionLabel(product.primaryRecommendation) })
      : t("todoDead", { name: product.productName, idle })
    add({ key: `dead-${product.productId}`, productId: product.productId, priority: "dead_stock", tone: "info", text })
  }
  return out.slice(0, limit)
}

export function recoveryActionLabel(action: string): string {
  const labels: Record<string, string> = {
    BUNDLE: t("recoveryBundle"),
    DISCOUNT: t("recoveryDiscount"),
    FLASH_SALE: t("recoveryFlashSale"),
    SEO_FIX: t("recoverySeoFix"),
    HOLD: t("recoveryHold"),
    MANUAL_REVIEW: t("recoveryManualReview"),
  }
  return labels[action] ?? action.toLowerCase().replace(/_/g, " ")
}

export type InventoryKpis = { outOfStock: number; runsOutWithinWeek: number; reorderNow: number }

export function inventoryKpis(items: InventoryIntelligenceItem[]): InventoryKpis {
  return {
    outOfStock: items.filter(isOut).length,
    runsOutWithinWeek: items.filter((item) => !isOut(item) && item.daysRemaining != null && item.daysRemaining < 7).length,
    reorderNow: items.filter(openReorder).length,
  }
}

export type DataHealth = { defaultedLeadTime: InventoryIntelligenceItem[]; insufficientData: InventoryIntelligenceItem[] }

export function dataHealth(items: InventoryIntelligenceItem[]): DataHealth {
  return {
    defaultedLeadTime: items.filter((item) => item.supplierLeadTimeDefaulted === true),
    insufficientData: items.filter((item) => item.dataStatus === "INSUFFICIENT"),
  }
}

/** Share of the bar to fill, with the lead-time marker on a scale of max(runway, lead time) × 1.25. */
export function runwayScale(daysRemaining: number | null, leadTimeDays: number | null) {
  if (daysRemaining == null) return null
  const days = Math.max(0, daysRemaining)
  const scale = Math.max(days, leadTimeDays ?? 0, 1) * 1.25
  return {
    fill: Math.min(100, (days / scale) * 100),
    leadMarker: leadTimeDays == null ? null : Math.min(100, (leadTimeDays / scale) * 100),
    beforeLeadTime: leadTimeDays != null && days < leadTimeDays,
  }
}

export type UrgencyFilter = "all" | "out" | "week" | "reorder" | "ok"

export function matchesUrgency(item: InventoryIntelligenceItem, filter: UrgencyFilter): boolean {
  const days = item.daysRemaining
  switch (filter) {
    case "out":
      return days != null && days <= 0
    case "week":
      return days != null && days > 0 && days < 7
    case "reorder":
      return item.reorderAction === "REORDER" && item.recommendationStatus === "OPEN"
    case "ok":
      return item.reorderAction !== "REORDER"
    default:
      return true
  }
}

export function toCsv(rows: InventoryIntelligenceItem[]): string {
  const escape = (value: unknown) => {
    const text = value == null ? "" : String(value)
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const header = [t("colProduct"), t("category"), t("csvDaysLeft"), t("csvLead"), t("csvQuantity"), t("csvOrderBy"), t("csvStatus")]
  const lines = rows.map((row) =>
    [row.productName, row.category, row.daysRemaining, row.supplierLeadTimeDays, row.reorderAction === "REORDER" ? row.recommendedQuantity : "", row.reorderDeadline, row.recommendationStatus].map(escape).join(","),
  )
  return [header.join(","), ...lines].join("\n")
}
