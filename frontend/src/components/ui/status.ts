import {
  AlertOctagon,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clock,
  Eye,
  HelpCircle,
  Minus,
  PackageX,
  ShoppingCart,
  Truck,
  Turtle,
  type LucideIcon,
} from "lucide-react"

import type { UiStringKey } from "@/lib/ui-i18n"

export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral"

export type StatusKind = "risk" | "data" | "reorder" | "deadStock" | "pricing"

export type StatusStyle = { tone: StatusTone; icon: LucideIcon; label: UiStringKey }

/** The one place that maps backend status values to tone, icon and label. */
export const STATUS_MAP: Record<StatusKind, Record<string, StatusStyle>> = {
  risk: {
    LOW: { tone: "success", icon: CheckCircle2, label: "statusLow" },
    MEDIUM: { tone: "warning", icon: AlertTriangle, label: "statusMedium" },
    HIGH: { tone: "danger", icon: AlertTriangle, label: "statusHigh" },
    CRITICAL: { tone: "danger", icon: AlertOctagon, label: "statusCritical" },
  },
  data: {
    SUFFICIENT: { tone: "success", icon: CheckCircle2, label: "statusSufficient" },
    LIMITED: { tone: "warning", icon: AlertTriangle, label: "statusLimited" },
    INSUFFICIENT: { tone: "neutral", icon: HelpCircle, label: "statusInsufficient" },
    STALE: { tone: "warning", icon: Clock, label: "statusStale" },
  },
  reorder: {
    NO_ACTION: { tone: "success", icon: CheckCircle2, label: "statusNoAction" },
    HOLD: { tone: "success", icon: CheckCircle2, label: "statusNoAction" },
    MONITOR: { tone: "info", icon: Eye, label: "statusMonitor" },
    REORDER: { tone: "warning", icon: ShoppingCart, label: "statusReorder" },
    URGENT_REORDER: { tone: "danger", icon: ShoppingCart, label: "statusUrgentReorder" },
    EXPEDITE: { tone: "danger", icon: Truck, label: "statusExpedite" },
  },
  deadStock: {
    HEALTHY: { tone: "success", icon: CheckCircle2, label: "statusHealthy" },
    SLOW_MOVING: { tone: "info", icon: Turtle, label: "statusSlowMoving" },
    AT_RISK: { tone: "warning", icon: AlertTriangle, label: "statusAtRisk" },
    DEAD_STOCK: { tone: "danger", icon: PackageX, label: "statusDeadStock" },
    INSUFFICIENT_DATA: { tone: "neutral", icon: HelpCircle, label: "statusInsufficient" },
  },
  pricing: {
    PRICE_LOWER: { tone: "info", icon: ArrowDown, label: "statusPriceLower" },
    PRICE_RAISE: { tone: "success", icon: ArrowUp, label: "statusPriceRaise" },
    HOLD: { tone: "neutral", icon: Minus, label: "statusHold" },
  },
}

export const TONE_CLASSES: Record<StatusTone, string> = {
  success: "border-success bg-success/10 text-success font-semibold",
  warning: "border-warning bg-warning/10 text-warning font-semibold",
  danger: "border-danger bg-danger/10 text-danger font-semibold",
  info: "border-info bg-info/10 text-info font-semibold",
  neutral: "border-border bg-muted/40 text-muted-foreground",
}

/** Unknown values still render (neutral, readable label) instead of crashing or hiding. */
export function resolveStatus(kind: StatusKind, value: string): StatusStyle | { tone: StatusTone; icon: LucideIcon; text: string } {
  return (
    STATUS_MAP[kind][value] ?? {
      tone: "neutral",
      icon: HelpCircle,
      text: value.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
    }
  )
}
