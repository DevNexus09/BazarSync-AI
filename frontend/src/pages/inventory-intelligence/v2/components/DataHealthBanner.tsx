import { AlertTriangle } from "lucide-react"
import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import type { InventoryIntelligenceItem } from "@/types/inventory-intelligence"

import { dataHealth } from "../inventory-logic"
import { t } from "../inventory-i18n"

/** One line per data gap with a fix; renders nothing when data is healthy. */
export function DataHealthBanner({ items }: { items: InventoryIntelligenceItem[] }) {
  const { defaultedLeadTime, insufficientData } = dataHealth(items)
  const lines = [
    defaultedLeadTime.length
      ? {
          key: "lead",
          text: t("healthLead", { count: defaultedLeadTime.length, products: defaultedLeadTime.length === 1 ? t("healthLeadOne") : t("healthLeadMany") }),
          href: defaultedLeadTime.length === 1 ? `/app/products/${defaultedLeadTime[0].productId}/edit` : "/app/products",
          fix: t("addLeadTime"),
        }
      : null,
    insufficientData.length
      ? {
          key: "sales",
          text: t("healthSales", { count: insufficientData.length, products: insufficientData.length === 1 ? t("healthSalesOne") : t("healthSalesMany") }),
          href: "/app/sales/import",
          fix: t("importSales"),
        }
      : null,
  ].filter((line): line is NonNullable<typeof line> => line != null)

  if (!lines.length) return null
  return (
    <div className="space-y-2" role="region" aria-label={t("dataHealth")}>
      {lines.map((line) => (
        <div key={line.key} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <span className="flex items-center gap-2 text-foreground">
            <AlertTriangle aria-hidden className="size-4 text-warning" />
            {line.text}
          </span>
          <Button asChild variant="outline" size="sm">
            <Link to={line.href}>{line.fix}</Link>
          </Button>
        </div>
      ))}
    </div>
  )
}
