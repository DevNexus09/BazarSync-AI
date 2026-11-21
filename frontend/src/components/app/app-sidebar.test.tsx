import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import AppSidebar from "@/components/app/app-sidebar"
import { ThemeProvider } from "@/components/theme/theme-provider"
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

  return (
    <ThemeProvider>
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
          onClose={() => setIsExpanded(false)}
        />
      </MemoryRouter>
    </ThemeProvider>
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.localStorage?.clear()
})

describe("AppSidebar", () => {
  it("renders a floating glass icon rail without embedded branding", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    const dashboardLabel = screen.getByTestId("sidebar-label-Dashboard")

    expect(sidebar).toHaveClass("rounded-[24px]", "backdrop-blur-2xl", "lg:w-16")
    expect(dashboardLabel).toHaveClass("max-w-0", "opacity-0")
    expect(dashboardLabel).toHaveAttribute("aria-hidden", "true")
    expect(screen.queryByText("BazarSync AI")).not.toBeInTheDocument()
    expect(screen.queryByText(/^B$/)).not.toBeInTheDocument()
  })

  it("expands labels when the desktop rail is hovered", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    const dashboardLabel = screen.getByTestId("sidebar-label-Dashboard")

    fireEvent.mouseEnter(sidebar)
    expect(sidebar).toHaveClass("lg:w-[248px]")
    expect(dashboardLabel).toHaveClass("max-w-[180px]", "opacity-100")
    expect(dashboardLabel).toHaveAttribute("aria-hidden", "false")

    fireEvent.mouseLeave(sidebar)
    expect(sidebar).not.toHaveClass("lg:w-[248px]")
    expect(dashboardLabel).toHaveClass("max-w-0", "opacity-0")
  })

  it("keeps every existing route and label available", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    for (const item of appNavItems) {
      expect(screen.getByRole("link", { name: item.label })).toHaveAttribute(
        "href",
        item.path
      )
    }
  })

  it("uses a single theme-colored pill for the active route", () => {
    setViewport(1440)
    render(<SidebarHarness initialPath="/app/products" />)

    const activeLink = screen.getByRole("link", { name: "Products" })
    const inactiveLink = screen.getByRole("link", { name: "Dashboard" })

    expect(activeLink).toHaveAttribute("aria-current", "page")
    expect(activeLink).toHaveClass("rounded-full", "bg-primary", "text-primary-foreground")
    expect(inactiveLink).not.toHaveClass("bg-primary")
  })

  it("uses icon glow without adding a hover row color", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const productsLink = screen.getByRole("link", { name: "Products" })
    const icon = productsLink.querySelector("svg")

    expect(productsLink.className).not.toContain("hover:bg-")
    expect(icon).toHaveClass("group-hover:drop-shadow-[0_0_9px_rgb(var(--accent))]")
  })

  it("closes the mobile drawer with Escape", () => {
    setViewport(390)
    render(<SidebarHarness initialExpanded />)

    expect(screen.getByRole("button", { name: "Close navigation" })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument()
  })

  it("closes the mobile drawer from the backdrop and after navigation", async () => {
    setViewport(390)
    const user = userEvent.setup()
    render(<SidebarHarness />)

    await user.click(screen.getByTestId("mobile-open"))
    expect(screen.getByRole("button", { name: "Close navigation" })).toBeInTheDocument()
    expect(screen.getByTestId("sidebar-label-Dashboard")).toHaveClass(
      "max-w-[180px]",
      "opacity-100"
    )

    await user.click(screen.getByRole("link", { name: "Products" }))
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument()

    await user.click(screen.getByTestId("mobile-open"))
    await user.click(screen.getByRole("button", { name: "Close navigation" }))
    expect(screen.queryByRole("button", { name: "Close navigation" })).not.toBeInTheDocument()
  })

  it("keeps navigation items keyboard accessible", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const competitorsLink = screen.getByRole("link", { name: "Competitors" })
    competitorsLink.focus()

    expect(competitorsLink).toHaveFocus()
    expect(competitorsLink).toHaveAttribute("title", "Competitors")
  })

  it("does not render a theme transition control", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    expect(screen.queryByRole("switch")).not.toBeInTheDocument()
  })
})
