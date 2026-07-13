import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useRef, useState } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import AppSidebar from "@/components/app/app-sidebar"
import { appNavItems } from "@/routes/nav-config"

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: width,
  })
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("min-width") ? width >= 1024 : width < 1024,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    onchange: null,
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

function SidebarHarness({
  initialPath = "/app/dashboard",
  initialExpanded = false,
}: {
  initialPath?: string
  initialExpanded?: boolean
}) {
  const [isExpanded, setIsExpanded] = useState(initialExpanded)
  const desktopToggleRef = useRef<HTMLButtonElement>(null)

  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <button
        type="button"
        data-testid="mobile-open"
        onClick={() => setIsExpanded(true)}
      >
        Open mobile navigation
      </button>
      <AppSidebar
        isExpanded={isExpanded}
        onToggle={() => setIsExpanded((current) => !current)}
        onClose={() => setIsExpanded(false)}
        desktopToggleRef={desktopToggleRef}
      />
    </MemoryRouter>
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.localStorage?.clear()
})

describe("AppSidebar", () => {
  it("renders a collapsed icon rail with accessible page tooltips", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeInTheDocument()
    expect(screen.getByTestId("sidebar-label-Dashboard")).toHaveClass("max-w-0")
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
      "title",
      "Dashboard"
    )
  })

  it("expands on toggle and reveals the existing English labels", async () => {
    setViewport(1440)
    const user = userEvent.setup()
    render(<SidebarHarness />)

    await user.click(screen.getByRole("button", { name: "Expand navigation" }))

    expect(screen.getByRole("button", { name: "Collapse navigation" })).toHaveAttribute(
      "aria-expanded",
      "true"
    )
    expect(screen.getByTestId("sidebar-label-Dashboard")).toHaveClass("max-w-[190px]")
  })

  it("marks the active route without changing the configured routes", () => {
    setViewport(1440)
    render(<SidebarHarness initialPath="/app/products" />)

    expect(screen.getByRole("link", { name: "Products" })).toHaveAttribute(
      "aria-current",
      "page"
    )
    for (const item of appNavItems) {
      expect(screen.getByRole("link", { name: item.label })).toHaveAttribute(
        "href",
        item.path
      )
    }
  })

  it("closes with Escape and returns focus to the desktop toggle", async () => {
    setViewport(1440)
    const user = userEvent.setup()
    render(<SidebarHarness />)

    await user.click(screen.getByRole("button", { name: "Expand navigation" }))
    fireEvent.keyDown(window, { key: "Escape" })

    expect(screen.getByRole("button", { name: "Expand navigation" })).toHaveFocus()
  })

  it("closes the mobile drawer from the backdrop and after navigation", async () => {
    setViewport(390)
    const user = userEvent.setup()
    render(<SidebarHarness />)

    await user.click(screen.getByTestId("mobile-open"))
    expect(screen.getByRole("button", { name: "Close navigation" })).toBeInTheDocument()

    await user.click(screen.getByRole("link", { name: "Products" }))
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument()

    await user.click(screen.getByTestId("mobile-open"))
    await user.click(screen.getByRole("button", { name: "Close navigation" }))
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument()
  })

  it("keeps navigation items keyboard accessible in collapsed mode", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const competitorsLink = screen.getByRole("link", { name: "Competitors" })
    competitorsLink.focus()

    expect(competitorsLink).toHaveFocus()
    expect(competitorsLink).toHaveAttribute("title", "Competitors")
  })
})
