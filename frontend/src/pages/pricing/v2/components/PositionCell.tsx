import { ArrowDown, ArrowUp, HelpCircle, Minus } from "lucide-react"

import type { MarketPosition } from "@/services/pricing-v2-service"

import { positionLabel } from "../pricing-math"

const ICONS = { ABOVE_MARKET: ArrowUp, BELOW_MARKET: ArrowDown, AT_MARKET: Minus, NO_MARKET_DATA: HelpCircle }

export function PositionCell({ position, rate }: { position: MarketPosition; rate: string | null }) {
  const Icon = ICONS[position]
  return (
    <span className={position === "NO_MARKET_DATA" ? "inline-flex items-center gap-1 text-muted-foreground" : "inline-flex items-center gap-1"}>
      <Icon aria-hidden className="size-3.5" />
      {positionLabel(position, rate)}
    </span>
  )
}
