import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import LandingPage from "@/pages/landing/landing-page"
import { ThemeProvider } from "@/components/theme/theme-provider"

const authState = vi.hoisted(() => ({
  status: "unauthenticated" as "authenticated" | "unauthenticated" | "loading",
}))

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => authState,
}))

function renderPage() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <LandingPage />
      </MemoryRouter>
    </ThemeProvider>
  )
}

beforeEach(() => {
  authState.status = "unauthenticated"
  document.documentElement.removeAttribute("data-theme")
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("LandingPage", () => {
  it("renders a compact hero and feature previews", () => {
    renderPage()

    expect(screen.getByRole("heading", { name: /BazarSync AI/i })).toBeInTheDocument()
    expect(
      screen.getByText("AI-powered marketplace intelligence for smarter selling.")
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Get Started/i })).toHaveAttribute(
      "href",
      "/login"
    )
    expect(screen.getByText("Products")).toBeInTheDocument()
    expect(screen.getByText("AI Copilot")).toBeInTheDocument()
    expect(screen.queryByText("Telegram alert preview")).not.toBeInTheDocument()
  })

  it("routes authenticated sellers to the dashboard from Get Started", () => {
    authState.status = "authenticated"
    renderPage()

    expect(screen.getByRole("link", { name: /Get Started/i })).toHaveAttribute(
      "href",
      "/app/dashboard"
    )
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute(
      "href",
      "/app/dashboard"
    )
  })

  it("does not expose a theme transition control", () => {
    renderPage()
    expect(
      screen.queryByRole("button", { name: /Switch to light mode|Switch to dark mode/i })
    ).not.toBeInTheDocument()
  })
})
