import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ColumnDef } from "@tanstack/react-table"
import { useState } from "react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { DataTable } from "@/components/ui/data-table"
import { Drawer } from "@/components/ui/drawer"
import { FreshnessPill } from "@/components/ui/freshness-pill"
import { STATUS_MAP } from "@/components/ui/status"
import { StatusBadge } from "@/components/ui/status-badge"
import { UrlTabs } from "@/components/ui/tabs"
import { ui } from "@/lib/ui-i18n"

afterEach(cleanup)

describe("StatusBadge", () => {
  it("maps every known status to an icon and a plain-language label", () => {
    for (const [kind, values] of Object.entries(STATUS_MAP)) {
      for (const [value, style] of Object.entries(values)) {
        const { container, unmount } = render(<StatusBadge kind={kind as keyof typeof STATUS_MAP} value={value} />)
        const badge = container.querySelector("span[data-tone]")!
        expect(badge.getAttribute("data-tone")).toBe(style.tone)
        expect(badge.querySelector("svg")).not.toBeNull()
        expect(badge.textContent).toBe(ui(style.label))
        expect(badge.textContent).not.toMatch(/_/)
        unmount()
      }
    }
  })

  it("shows specific labels for risk, reorder and pricing", () => {
    render(
      <>
        <StatusBadge kind="risk" value="CRITICAL" />
        <StatusBadge kind="reorder" value="URGENT_REORDER" />
        <StatusBadge kind="pricing" value="PRICE_LOWER" />
      </>,
    )
    expect(screen.getByText("Critical")).toBeInTheDocument()
    expect(screen.getByText("Reorder now")).toBeInTheDocument()
    expect(screen.getByText("Lower price")).toBeInTheDocument()
  })

  it("renders unknown values as neutral readable text and nothing for empty", () => {
    const { container } = render(<StatusBadge kind="risk" value="BRAND_NEW_STATE" />)
    expect(screen.getByText("Brand new state")).toBeInTheDocument()
    expect(container.querySelector("[data-tone]")?.getAttribute("data-tone")).toBe("neutral")
    cleanup()
    const empty = render(<StatusBadge kind="risk" value={null} />)
    expect(empty.container).toBeEmptyDOMElement()
  })
})

type Row = { id: string; name: string; stock: number }
const columns: ColumnDef<Row, unknown>[] = [
  { accessorKey: "name", header: "Product" },
  { accessorKey: "stock", header: "Stock" },
]
const rows: Row[] = Array.from({ length: 30 }, (_, index) => ({
  id: String(index),
  name: `Item ${String(index).padStart(2, "0")}`,
  stock: (index * 7) % 30,
}))

function bodyRows() {
  return screen.getAllByRole("row").slice(1)
}

describe("DataTable", () => {
  it("sorts by a column and marks aria-sort", async () => {
    const user = userEvent.setup()
    render(<DataTable columns={columns} data={rows.slice(0, 5)} getRowId={(row) => row.id} />)

    const names = () => bodyRows().map((row) => within(row).getAllByRole("cell")[0].textContent?.replace("Product", ""))
    await user.click(screen.getByRole("button", { name: /Product/ }))
    expect(screen.getByRole("columnheader", { name: /Product/ })).toHaveAttribute("aria-sort", "ascending")
    expect(names()).toEqual(["Item 00", "Item 01", "Item 02", "Item 03", "Item 04"])

    await user.click(screen.getByRole("button", { name: /Product/ }))
    expect(screen.getByRole("columnheader", { name: /Product/ })).toHaveAttribute("aria-sort", "descending")
    expect(names()?.[0]).toBe("Item 04")
  })

  it("searches across rows and resets to the first page", async () => {
    const user = userEvent.setup()
    render(<DataTable columns={columns} data={rows} getRowId={(row) => row.id} initialPageSize={10} />)

    await user.click(screen.getByRole("button", { name: "Next" }))
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument()

    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Item 2")
    expect(bodyRows()).toHaveLength(10)
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument()

    await user.clear(screen.getByRole("searchbox"))
    await user.type(screen.getByRole("searchbox"), "nothing matches")
    expect(screen.getByText("No matching rows")).toBeInTheDocument()
  })

  it("changes page size", async () => {
    const user = userEvent.setup()
    render(<DataTable columns={columns} data={rows} getRowId={(row) => row.id} initialPageSize={10} />)
    expect(bodyRows()).toHaveLength(10)
    await user.selectOptions(screen.getByRole("combobox", { name: "Rows per page" }), "25")
    expect(bodyRows()).toHaveLength(25)
  })

  it("opens a row by click or keyboard", async () => {
    const user = userEvent.setup()
    const onRowClick = vi.fn()
    render(<DataTable columns={columns} data={rows.slice(0, 3)} getRowId={(row) => row.id} onRowClick={onRowClick} />)

    await user.click(bodyRows()[0])
    expect(onRowClick).toHaveBeenLastCalledWith(rows[0])
    bodyRows()[1].focus()
    await user.keyboard("{Enter}")
    expect(onRowClick).toHaveBeenLastCalledWith(rows[1])
  })
})

function DrawerHarness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open details
      </button>
      <Drawer open={open} onOpenChange={setOpen} title="Oil 1L">
        <button type="button">Mark ordered</button>
      </Drawer>
    </>
  )
}

describe("Drawer", () => {
  it("moves focus inside, closes on Esc and returns focus to the trigger", async () => {
    const user = userEvent.setup()
    render(<DrawerHarness />)
    const trigger = screen.getByRole("button", { name: "Open details" })

    await user.click(trigger)
    const dialog = screen.getByRole("dialog", { name: "Oil 1L" })
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("closes from the close button", async () => {
    const user = userEvent.setup()
    render(<DrawerHarness />)
    await user.click(screen.getByRole("button", { name: "Open details" }))
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })
})

function LocationProbe() {
  return <output data-testid="search">{useLocation().search}</output>
}

describe("UrlTabs", () => {
  const tabs = [
    { value: "today", label: "Today", content: <p>Today content</p> },
    { value: "reorder", label: "Reorder", content: <p>Reorder content</p> },
  ]

  it("opens the tab named in the URL and keeps other params when switching", async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={["/x?tab=reorder&product=p1"]}>
        <UrlTabs tabs={tabs} defaultValue="today" label="Inventory views" />
        <LocationProbe />
      </MemoryRouter>,
    )
    expect(screen.getByText("Reorder content")).toBeInTheDocument()

    await user.click(screen.getByRole("tab", { name: "Today" }))
    expect(screen.getByText("Today content")).toBeInTheDocument()
    expect(screen.getByTestId("search").textContent).toBe("?tab=today&product=p1")
  })

  it("falls back to the default for an unknown tab", () => {
    render(
      <MemoryRouter initialEntries={["/x?tab=bogus"]}>
        <UrlTabs tabs={tabs} defaultValue="today" label="Inventory views" />
      </MemoryRouter>,
    )
    expect(screen.getByRole("tab", { name: "Today" })).toHaveAttribute("aria-selected", "true")
  })
})

describe("FreshnessPill", () => {
  const now = new Date("2026-11-23T12:00:00Z")

  it("shows age when fresh and a stale warning with refresh when old", async () => {
    const user = userEvent.setup()
    const onRefresh = vi.fn()
    render(<FreshnessPill updatedAt="2026-11-23T10:00:00Z" now={now} />)
    expect(screen.getByText("Updated 2 hours ago")).toBeInTheDocument()
    cleanup()

    render(<FreshnessPill updatedAt="2026-11-20T12:00:00Z" now={now} onRefresh={onRefresh} />)
    expect(screen.getByText("Stale · Updated 3 days ago")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Refresh" }))
    expect(onRefresh).toHaveBeenCalled()
    cleanup()

    render(<FreshnessPill updatedAt={null} now={now} />)
    expect(screen.getByText("Not calculated yet")).toBeInTheDocument()
  })
})
