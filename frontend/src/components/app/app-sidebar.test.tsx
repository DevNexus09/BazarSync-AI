import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useRef, useState } from "react"
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
  const desktopToggleRef = useRef<HTMLButtonElement>(null)

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
          onToggle={() => setIsExpanded((current) => !current)}
          onClose={() => setIsExpanded(false)}
          desktopToggleRef={desktopToggleRef}
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

  it("temporarily expands the desktop rail while the pointer is over it", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    const dashboardLabel = screen.getByTestId("sidebar-label-Dashboard")

    expect(dashboardLabel).toHaveClass("max-w-0")

    fireEvent.mouseEnter(sidebar)
    expect(dashboardLabel).toHaveClass("max-w-[190px]")

    fireEvent.mouseLeave(sidebar)
    expect(dashboardLabel).toHaveClass("max-w-0")
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

  it("collapses a desktop expansion when the pointer leaves the rail", async () => {
    setViewport(1440)
    const user = userEvent.setup()
    render(<SidebarHarness />)

    const sidebar = screen.getByTestId("app-sidebar")
    await user.click(screen.getByRole("button", { name: "Expand navigation" }))
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toBeInTheDocument()

    fireEvent.mouseLeave(sidebar)

    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeInTheDocument()
    expect(screen.getByTestId("sidebar-label-Dashboard")).toHaveClass("max-w-0")
  })

  it("marks the active route without changing the configured routes", () => {
    setViewport(1440)
    render(<SidebarHarness initialPath="/app/products" />)

    const activeLink = screen.getByRole("link", { name: "Products" })
    expect(activeLink).toHaveAttribute("aria-current", "page")
    expect(activeLink).not.toHaveClass("bg-primary/10")
    expect(activeLink).not.toHaveClass("border-primary/20")
    expect(activeLink).not.toHaveClass("shadow-[inset_3px_0_0_rgb(var(--primary))]")
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

  it("reveals the theme toggle on hover or focus in the collapsed rail", () => {
    setViewport(1440)
    render(<SidebarHarness />)

    expect(screen.queryByRole("switch")).not.toBeInTheDocument()

    fireEvent.mouseEnter(screen.getByTestId("app-sidebar"))
    expect(screen.getByRole("switch")).toBeVisible()

    fireEvent.mouseLeave(screen.getByTestId("app-sidebar"))
    fireEvent.focus(screen.getByRole("button", { name: "Expand navigation" }))
    expect(screen.getByRole("switch")).toBeVisible()
  })

  it("keeps the theme toggle visible in the open mobile drawer", async () => {
    setViewport(390)
    const user = userEvent.setup()
    render(<SidebarHarness />)

    await user.click(screen.getByTestId("mobile-open"))

    expect(screen.getByRole("switch")).toBeVisible()
  })

  it("changes the root theme without changing navigation", async () => {
    setViewport(1440)
    const user = userEvent.setup()
    render(<SidebarHarness initialExpanded />)

    const themeSwitch = screen.getByRole("switch")
    const initialTheme = themeSwitch.getAttribute("aria-checked") === "true" ? "dark" : "light"
    await user.click(themeSwitch)

    expect(document.documentElement).toHaveAttribute(
      "data-theme",
      initialTheme === "dark" ? "light" : "dark"
    )
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument()
    expect(screen.getByRole("switch")).toBeInTheDocument()
  })
})
