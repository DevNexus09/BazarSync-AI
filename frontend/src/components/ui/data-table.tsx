import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table"
import { ArrowDown, ArrowUp, ArrowUpDown, Search } from "lucide-react"
import { useState, type KeyboardEvent, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { ui } from "@/lib/ui-i18n"
import { cn } from "@/lib/utils"

const PAGE_SIZES = [10, 25, 50]

/**
 * Sortable, searchable, paginated table. Below the sm breakpoint each row becomes a card
 * with its column labels inline (same DOM, CSS only).
 * shortcut: client-side paging/search only; add manual pagination when a list needs a server page.
 */
export function DataTable<T>({
  columns,
  data,
  getRowId,
  onRowClick,
  searchLabel = ui("search"),
  initialPageSize = 25,
  initialSorting = [],
  empty,
  toolbar,
}: {
  columns: ColumnDef<T, unknown>[]
  data: T[]
  getRowId: (row: T) => string
  onRowClick?: (row: T) => void
  searchLabel?: string
  initialPageSize?: number
  initialSorting?: SortingState
  empty?: ReactNode
  toolbar?: ReactNode
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting)
  const [globalFilter, setGlobalFilter] = useState("")
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: initialPageSize })

  // TanStack returns stable functions here; the React Compiler lint cannot know that.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getRowId: (row) => getRowId(row),
    state: { sorting, globalFilter, pagination },
    onSortingChange: setSorting,
    onGlobalFilterChange: (value) => {
      setGlobalFilter(value)
      setPagination((current) => ({ ...current, pageIndex: 0 }))
    },
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  })

  const rows = table.getRowModel().rows
  const pageCount = Math.max(1, table.getPageCount())

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onRowClick?.(row)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-0 flex-1 sm:max-w-xs">
          <span className="sr-only">{searchLabel}</span>
          <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={globalFilter}
            onChange={(event) => table.setGlobalFilter(event.target.value)}
            placeholder={`${searchLabel}…`}
            className="h-9 w-full rounded-lg border border-border bg-card/60 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        {toolbar}
      </div>

      <div className="max-h-[70vh] overflow-auto rounded-lg border border-border/60">
        <table className="w-full border-collapse text-sm max-sm:block">
          <thead className="sticky top-0 z-10 bg-card max-sm:sr-only">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted()
                  const SortIcon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                      className="border-b border-border/60 px-3 py-2 text-left text-xs font-semibold text-muted-foreground"
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 rounded hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <SortIcon aria-hidden className="size-3.5" />
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody className="max-sm:block max-sm:space-y-2 max-sm:p-2">
            {rows.length === 0 ? (
              <tr className="max-sm:block">
                <td colSpan={columns.length} className="px-3 py-6 text-center text-muted-foreground max-sm:block">
                  {empty ?? ui("noResults")}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={row.id}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  onKeyDown={onRowClick ? (event) => onRowKeyDown(event, row.original) : undefined}
                  className={cn(
                    "border-b border-border/40 last:border-0 max-sm:block max-sm:rounded-lg max-sm:border max-sm:p-2",
                    onRowClick && "cursor-pointer hover:bg-muted/30 focus-visible:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-3 py-2 align-middle max-sm:flex max-sm:justify-between max-sm:gap-3 max-sm:px-1 max-sm:py-1">
                      <span aria-hidden className="text-xs font-medium text-muted-foreground sm:hidden">
                        {typeof cell.column.columnDef.header === "string" ? cell.column.columnDef.header : null}
                      </span>
                      <span className="max-sm:text-right">{flexRender(cell.column.columnDef.cell, cell.getContext())}</span>
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
        <label className="flex items-center gap-2">
          {ui("rowsPerPage")}
          <select
            value={pagination.pageSize}
            onChange={(event) => table.setPageSize(Number(event.target.value))}
            className="h-8 rounded-md border border-border bg-card/60 px-2 text-foreground"
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-2">
          <span aria-live="polite">{ui("pageOf", { page: pagination.pageIndex + 1, pages: pageCount })}</span>
          <Button variant="outline" size="sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
            {ui("previous")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
            {ui("next")}
          </Button>
        </div>
      </div>
    </div>
  )
}
