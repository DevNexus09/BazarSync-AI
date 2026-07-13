import type { CopilotSourceMode } from "@/types/copilot"
import {
  copilotSourceModes,
  resolveDateRange,
  type CopilotDateRangeKey,
  type CopilotDateRangeValue,
} from "@/components/copilot/copilot-filter-utils"

const dateRangeOptions: Array<{ key: CopilotDateRangeKey; label: string }> = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last_7_days", label: "Last 7 days" },
  { key: "last_30_days", label: "Last 30 days" },
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "custom", label: "Custom range" },
]

const copilotDomainOptions = [
  { value: "products", label: "Products" },
  { value: "revenue", label: "Revenue" },
  { value: "profit", label: "Profit" },
  { value: "inventory", label: "Inventory" },
  { value: "competitors", label: "Competitors" },
  { value: "pricing", label: "Pricing" },
  { value: "promotions", label: "Promotions" },
  { value: "dead_stock", label: "Dead Stock" },
  { value: "seo", label: "SEO" },
  { value: "alerts", label: "Alerts" },
  { value: "recommendations", label: "Recommendations" },
  { value: "memory", label: "Memory" },
]

export function CopilotFilterControls({
  dateRange,
  selectedDomains,
  sourceMode,
  onDateRangeChange,
  onDomainsChange,
  onSourceModeChange,
}: {
  dateRange: CopilotDateRangeValue
  selectedDomains: string[]
  sourceMode: CopilotSourceMode
  onDateRangeChange: (value: CopilotDateRangeValue) => void
  onDomainsChange: (value: string[]) => void
  onSourceModeChange: (value: CopilotSourceMode) => void
}) {
  const allDomainsSelected = selectedDomains.length === 0

  const handleDateKeyChange = (key: CopilotDateRangeKey) => {
    onDateRangeChange(resolveDateRange(key, dateRange))
  }

  const toggleDomain = (domain: string) => {
    if (domain === "all") {
      onDomainsChange([])
      return
    }

    onDomainsChange(
      selectedDomains.includes(domain)
        ? selectedDomains.filter((item) => item !== domain)
        : [...selectedDomains, domain]
    )
  }

  return (
    <div className="space-y-3 border-b border-border/60 bg-card px-3 py-3 text-xs">
      <div className="space-y-1.5">
        <label className="font-semibold text-foreground" htmlFor="copilot-date-range">
          Date range
        </label>
        <select
          id="copilot-date-range"
          value={dateRange.key}
          onChange={(event) =>
            handleDateKeyChange(event.target.value as CopilotDateRangeKey)
          }
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
        >
          {dateRangeOptions.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
        {dateRange.key === "custom" ? (
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1 text-muted-foreground">
              <span>From</span>
              <input
                aria-label="Custom from date"
                type="date"
                value={dateRange.fromDate}
                onChange={(event) =>
                  onDateRangeChange({ ...dateRange, fromDate: event.target.value })
                }
                className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <label className="space-y-1 text-muted-foreground">
              <span>To</span>
              <input
                aria-label="Custom to date"
                type="date"
                value={dateRange.toDate}
                onChange={(event) =>
                  onDateRangeChange({ ...dateRange, toDate: event.target.value })
                }
                className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
              />
            </label>
          </div>
        ) : null}
      </div>

      <fieldset className="space-y-1.5">
        <legend className="font-semibold text-foreground">Domains</legend>
        <div className="flex flex-wrap gap-1.5">
          <DomainChip
            label="All"
            selected={allDomainsSelected}
            onClick={() => toggleDomain("all")}
          />
          {copilotDomainOptions.map((domain) => (
            <DomainChip
              key={domain.value}
              label={domain.label}
              selected={selectedDomains.includes(domain.value)}
              onClick={() => toggleDomain(domain.value)}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-1.5">
        <legend className="font-semibold text-foreground">Sources</legend>
        <div className="grid gap-1 sm:grid-cols-3">
          {copilotSourceModes.map((mode) => (
            <label
              key={mode.value}
              className="flex items-center gap-1.5 rounded-md border border-border/70 bg-background px-2 py-1.5 text-muted-foreground"
            >
              <input
                type="radio"
                name="copilot-source-mode"
                checked={sourceMode === mode.value}
                onChange={() => onSourceModeChange(mode.value)}
              />
              <span>{mode.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  )
}

function DomainChip({
  label,
  selected,
  onClick,
}: {
  label: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={
        selected
          ? "rounded-full border border-primary/50 bg-primary/15 px-2 py-1 font-medium text-primary"
          : "rounded-full border border-border/70 bg-background px-2 py-1 font-medium text-muted-foreground hover:border-primary/40 hover:text-foreground"
      }
    >
      {label}
    </button>
  )
}
