import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import AppSidebar, { SIDEBAR_COLLAPSE_DELAY_MS } from "@/components/app/app-sidebar"
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
  vi.useRealTimers()
  cleanup()
  vi.restoreAllMocks()
  window.localStorage?.clear()
})

describe("AppSidebar", () => {
  it("renders a collapsed floating glass capsule without embedded branding", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    const dashboardLabel = screen.getByTestId("sidebar-label-Dashboard")

    expect(sidebar).toHaveClass("glass-surface", "lg:w-16", "lg:rounded-[32px]")
    expect(sidebar).toHaveAttribute("data-expanded", "false")
    expect(dashboardLabel).toHaveClass("opacity-0")
    expect(dashboardLabel).toHaveAttribute("aria-hidden", "true")
    expect(screen.queryByRole("button", { name: /expand|collapse/i })).not.toBeInTheDocument()
    expect(screen.queryByText("BazarSync AI")).not.toBeInTheDocument()
    expect(screen.queryByText(/^B$/)).not.toBeInTheDocument()
  })

  it("expands on pointer enter and collapses only after the leave delay", () => {
    vi.useFakeTimers()
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    const dashboardLabel = screen.getByTestId("sidebar-label-Dashboard")

    fireEvent.pointerEnter(sidebar)
    expect(sidebar).toHaveClass("lg:w-[288px]")
    expect(dashboardLabel).toHaveClass("opacity-100")
    expect(dashboardLabel).toHaveAttribute("aria-hidden", "false")

    fireEvent.pointerLeave(sidebar)
    act(() => vi.advanceTimersByTime(SIDEBAR_COLLAPSE_DELAY_MS - 1))
    expect(sidebar).toHaveClass("lg:w-[288px]")

    act(() => vi.advanceTimersByTime(1))
    expect(sidebar).not.toHaveClass("lg:w-[288px]")
    expect(dashboardLabel).toHaveClass("opacity-0")
  })

  it("cancels a pending collapse when the pointer returns", () => {
    vi.useFakeTimers()
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    fireEvent.pointerEnter(sidebar)
    fireEvent.pointerLeave(sidebar)
    act(() => vi.advanceTimersByTime(SIDEBAR_COLLAPSE_DELAY_MS / 2))
    fireEvent.pointerEnter(sidebar)
    act(() => vi.advanceTimersByTime(SIDEBAR_COLLAPSE_DELAY_MS * 2))

    expect(sidebar).toHaveAttribute("data-expanded", "true")
  })

  it("stays expanded while moving between navigation items", () => {
    vi.useFakeTimers()
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    fireEvent.pointerEnter(sidebar)
    fireEvent.pointerOver(screen.getByRole("link", { name: "Products" }))
    fireEvent.pointerOver(screen.getByRole("link", { name: "Dashboard" }))
    act(() => vi.advanceTimersByTime(SIDEBAR_COLLAPSE_DELAY_MS * 2))

    expect(sidebar).toHaveAttribute("data-expanded", "true")
  })

  it("ignores touch pointers so the mobile drawer controls expansion", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    fireEvent.pointerEnter(sidebar, { pointerType: "touch" })

    expect(sidebar).toHaveAttribute("data-expanded", "false")
  })

  it("stays expanded while keyboard focus is inside", async () => {
    setViewport(1440)
    const user = userEvent.setup()
    // jsdom never matches :focus-visible; treat tab focus as keyboard focus.
    const nativeMatches = Element.prototype.matches
    vi.spyOn(Element.prototype, "matches").mockImplementation(function (
      this: Element,
      selector: string
    ) {
      return selector === ":focus-visible" || nativeMatches.call(this, selector)
    })
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")

    await user.tab() // mobile-open button
    await user.tab()
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveFocus()
    expect(sidebar).toHaveAttribute("data-expanded", "true")

    await user.tab()
    expect(sidebar).toHaveAttribute("data-expanded", "true")

    act(() => (document.activeElement as HTMLElement).blur())
    expect(sidebar).toHaveAttribute("data-expanded", "false")
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

  it("renders one shared liquid-glass indicator on the active route", () => {
    setViewport(1440)
    render(<SidebarHarness initialPath="/app/products" />)

    const activeLink = screen.getByRole("link", { name: "Products" })
    const inactiveLink = screen.getByRole("link", { name: "Dashboard" })

    expect(activeLink).toHaveAttribute("aria-current", "page")
    expect(document.querySelectorAll(".glass-pill")).toHaveLength(1)
    expect(activeLink.querySelector(".glass-pill")).not.toBeNull()
    expect(inactiveLink.querySelector(".glass-pill")).toBeNull()
    expect(inactiveLink.querySelector(".glass-hover")).toHaveClass("group-hover:opacity-100")
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
    expect(screen.getByTestId("sidebar-label-Dashboard")).toHaveClass("opacity-100")

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
    expect(competitorsLink).not.toHaveAttribute("title")
  })

  it("does not render a theme transition control", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    expect(screen.queryByRole("switch")).not.toBeInTheDocument()
  })
})
