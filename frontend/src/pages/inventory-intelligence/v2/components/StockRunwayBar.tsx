import { cn } from "@/lib/utils"
import type { InventoryIntelligenceItem } from "@/types/inventory-intelligence"

import { runsOutText, runwayScale } from "../inventory-logic"
import { t } from "../inventory-i18n"

/** Days of stock left against the supplier lead time: red when stock runs out before new stock can arrive. */
export function StockRunwayBar({ item }: { item: Pick<InventoryIntelligenceItem, "daysRemaining" | "predictedStockoutDate" | "supplierLeadTimeDays"> }) {
  const scale = runwayScale(item.daysRemaining, item.supplierLeadTimeDays ?? null)
  if (!scale) {
    return <span className="text-sm text-muted-foreground">{t("notEnoughSales")}</span>
  }
  const label = runsOutText(item) ?? ""
  return (
    <div className="min-w-40 space-y-1">
      <div className="relative h-2 rounded-full bg-muted/50" role="img" aria-label={item.supplierLeadTimeDays != null ? t("runwayAria", { runway: label, lead: item.supplierLeadTimeDays }) : label}>
        <div
          className={cn("h-2 rounded-full", scale.beforeLeadTime ? "bg-danger" : "bg-success")}
          style={{ width: `${Math.max(scale.fill, 2)}%` }}
        />
        {scale.leadMarker != null ? (
          <div className="absolute -top-1 h-4 w-0.5 bg-foreground" style={{ left: `${scale.leadMarker}%` }} />
        ) : null}
      </div>
      <div className="flex justify-between gap-2 text-xs">
        <span className={scale.beforeLeadTime ? "font-medium text-danger" : "text-foreground"}>{label}</span>
        {item.supplierLeadTimeDays != null ? <span className="text-muted-foreground">{t("leadShort", { days: item.supplierLeadTimeDays })}</span> : null}
      </div>
    </div>
  )
}
