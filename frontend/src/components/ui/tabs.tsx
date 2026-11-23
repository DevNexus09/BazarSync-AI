import { Tabs as TabsPrimitive } from "radix-ui"
import type { ReactNode } from "react"
import { useSearchParams } from "react-router-dom"

import { cn } from "@/lib/utils"

export type UrlTab = { value: string; label: ReactNode; content: ReactNode }

/** Accessible tabs whose selection lives in the URL (?tab=reorder), so views can be deep-linked. */
export function UrlTabs({
  tabs,
  defaultValue,
  param = "tab",
  label,
  className,
}: {
  tabs: UrlTab[]
  defaultValue: string
  param?: string
  label: string
  className?: string
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get(param)
  const value = tabs.some((tab) => tab.value === requested) ? (requested as string) : defaultValue

  const select = (next: string) =>
    setSearchParams((current) => {
      const params = new URLSearchParams(current)
      params.set(param, next)
      return params
    })

  return (
    <TabsPrimitive.Root value={value} onValueChange={select} className={className}>
      <TabsPrimitive.List
        aria-label={label}
        className="flex gap-1 overflow-x-auto border-b border-border/60"
      >
        {tabs.map((tab) => (
          <TabsPrimitive.Trigger
            key={tab.value}
            value={tab.value}
            className={cn(
              "-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground transition",
              "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "data-[state=active]:border-primary data-[state=active]:text-foreground",
            )}
          >
            {tab.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {tabs.map((tab) => (
        <TabsPrimitive.Content key={tab.value} value={tab.value} className="pt-4 focus-visible:outline-none">
          {tab.content}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  )
}
