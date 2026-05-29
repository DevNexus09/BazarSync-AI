import { useMemo, useState } from "react"
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import type { ColumnDef, SortingState } from "@tanstack/react-table"
import { ArrowDown, ArrowUp, Search } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ErrorState } from "@/components/common/error-state"
import { cn } from "@/lib/utils"
import {
  CompetitorTrend,
  StockStatus,
  type Competitor,
} from "@/types/competitor"
import { formatCurrency, formatNumber } from "@/utils/formatters"

type CompetitorTableProps = {
  competitors?: Competitor[]
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

const stockTone: Record<StockStatus, string> = {
<<<<<<< HEAD
  [StockStatus.InStock]: "bg-emerald-500/15 text-emerald-300",
  [StockStatus.LowStock]: "bg-amber-500/15 text-amber-300",
  [StockStatus.OutOfStock]: "bg-rose-500/15 text-rose-300",
}

const trendTone: Record<CompetitorTrend, string> = {
  [CompetitorTrend.Up]: "text-rose-300",
  [CompetitorTrend.Down]: "text-emerald-300",
=======
  [StockStatus.InStock]: "bg-emerald-100 text-emerald-700",
  [StockStatus.LowStock]: "bg-amber-100 text-amber-700",
  [StockStatus.OutOfStock]: "bg-rose-100 text-rose-700",
}

const trendTone: Record<CompetitorTrend, string> = {
  [CompetitorTrend.Up]: "text-rose-600",
  [CompetitorTrend.Down]: "text-emerald-600",
>>>>>>> develop
  [CompetitorTrend.Flat]: "text-muted-foreground",
}

export function CompetitorTable({
  competitors,
  isLoading,
  isError,
  onRetry,
}: CompetitorTableProps) {
  const [globalFilter, setGlobalFilter] = useState("")
  const [sorting, setSorting] = useState<SortingState>([
    { id: "urgencyScore", desc: true },
  ])

  const data = competitors ?? []

  const columns = useMemo<ColumnDef<Competitor>[]>(
    () => [
      {
        accessorKey: "product",
        header: "Product",
        cell: ({ row }) => (
          <div>
            <div className="text-sm font-semibold text-foreground">
              {row.original.product}
            </div>
            <div className="text-xs text-muted-foreground">
              {row.original.status.replace("_", " ")}
            </div>
          </div>
        ),
      },
      {
        accessorKey: "competitor",
        header: "Competitor",
        cell: ({ row }) => (
          <div className="text-sm text-foreground">
            {row.original.competitor}
          </div>
        ),
      },
      {
        accessorKey: "competitorPrice",
        header: "Competitor price",
        cell: ({ row }) => (
          <div className="text-sm font-semibold text-foreground">
            {formatCurrency(row.original.competitorPrice)}
          </div>
        ),
      },
      {
        accessorKey: "sellerPrice",
        header: "Seller price",
        cell: ({ row }) => (
          <div className="text-sm text-foreground">
            {formatCurrency(row.original.sellerPrice)}
          </div>
        ),
      },
      {
        accessorKey: "priceGap",
        header: "Price gap",
        cell: ({ row }) => {
          const gap = row.original.priceGap
          const tone = gap >= 0 ? "text-rose-600" : "text-emerald-600"
          return (
            <div className={cn("text-sm font-semibold", tone)}>
              {gap >= 0 ? "+" : ""}
              {formatCurrency(gap)}
            </div>
          )
        },
      },
      {
        accessorKey: "stockStatus",
        header: "Stock",
        cell: ({ row }) => (
          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-semibold",
              stockTone[row.original.stockStatus]
            )}
          >
            {row.original.stockStatus.replace("_", " ")}
          </span>
        ),
      },
      {
        accessorKey: "urgencyScore",
        header: "Urgency",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <div className="h-2 w-20 rounded-full bg-muted">
              <div
                className="h-2 rounded-full bg-rose-500"
                style={{ width: `${row.original.urgencyScore}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-foreground">
              {formatNumber(row.original.urgencyScore)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "recommendationAction",
        header: "Recommendation",
        cell: ({ row }) => (
          <div className="text-xs font-semibold text-foreground">
            {row.original.recommendationAction}
          </div>
        ),
      },
      {
        accessorKey: "trend",
        header: "Trend",
        cell: ({ row }) => (
          <div className={cn("text-xs font-semibold", trendTone[row.original.trend])}>
            {row.original.trend.toUpperCase()}
          </div>
        ),
      },
    ],
    []
  )

  const table = useReactTable({
    data,
    columns,
    state: {
      globalFilter,
      sorting,
    },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    globalFilterFn: (row, _columnId, filterValue) => {
      const search = String(filterValue).toLowerCase()
      return (
        row.original.product.toLowerCase().includes(search) ||
        row.original.competitor.toLowerCase().includes(search)
      )
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  })

  if (isLoading) {
    return (
<<<<<<< HEAD
      <div className="glass-panel p-4">
=======
      <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
        <div className="h-5 w-40 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={`table-skeleton-${index}`}
              className="h-10 rounded-lg bg-muted/30"
            />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorState
        title="Competitor table unavailable"
        message="We couldn't load the competitor table."
        action={
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        }
      />
    )
  }

  return (
<<<<<<< HEAD
    <div className="glass-panel p-4">
=======
    <div className="rounded-xl border bg-background p-4 shadow-sm">
>>>>>>> develop
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Competitor monitoring
          </h3>
          <p className="text-xs text-muted-foreground">
            {formatNumber(data.length)} competitor listings tracked
          </p>
        </div>
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={globalFilter ?? ""}
            onChange={(event) => setGlobalFilter(event.target.value)}
            placeholder="Search product or competitor"
            className="pl-9"
            aria-label="Search competitors"
          />
        </div>
      </div>

<<<<<<< HEAD
      <div className="mt-4 overflow-hidden rounded-lg border border-border/60">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-muted/30 text-xs uppercase text-muted-foreground">
=======
      <div className="mt-4 overflow-hidden rounded-lg border">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
>>>>>>> develop
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort()
                  const sort = header.column.getIsSorted()
                  return (
                    <th
                      key={header.id}
                      className={cn(
                        "px-3 py-2",
                        canSort ? "cursor-pointer select-none" : ""
                      )}
                      onClick={canSort ? header.column.getToggleSortingHandler() : undefined}
                    >
                      <div className="flex items-center gap-2">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                        {sort === "asc" ? (
                          <ArrowUp className="size-3" />
                        ) : sort === "desc" ? (
                          <ArrowDown className="size-3" />
                        ) : null}
                      </div>
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3 py-6 text-center text-xs text-muted-foreground"
                >
                  No competitors found for this search.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => {
                const isCritical =
                  row.original.urgencyScore >= 80 ||
                  row.original.stockStatus === StockStatus.OutOfStock
                return (
                  <tr
                    key={row.id}
                    className={cn(
<<<<<<< HEAD
                      "border-t border-border/60",
                      isCritical ? "bg-rose-500/10" : "bg-transparent"
=======
                      "border-t",
                      isCritical ? "bg-rose-50/60" : "bg-background"
>>>>>>> develop
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-3 align-top">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </td>
                    ))}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Page {table.getState().pagination.pageIndex + 1} of{" "}
          {table.getPageCount()}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="xs"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  )
}