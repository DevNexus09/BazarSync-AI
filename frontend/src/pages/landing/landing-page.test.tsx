import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import LandingPage from "@/pages/landing/landing-page"
import { ThemeProvider } from "@/components/theme/theme-provider"

const authState = vi.hoisted(() => ({
  status: "unauthenticated" as "authenticated" | "unauthenticated" | "loading",
  startDemo: vi.fn<() => Promise<void>>(),
}))

const navigateMock = vi.hoisted(() => vi.fn())

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigateMock,
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
  authState.startDemo = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)
  navigateMock.mockReset()
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

  it("opens the demo store without sign-in from Experience BazarSync", async () => {
    renderPage()

    fireEvent.click(screen.getByRole("button", { name: /Experience BazarSync/i }))

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/app/dashboard"))
    expect(authState.startDemo).toHaveBeenCalledTimes(1)
  })

  it("shows a friendly message when the demo cannot be opened", async () => {
    authState.startDemo = vi.fn<() => Promise<void>>().mockRejectedValue(new Error("offline"))
    renderPage()

    fireEvent.click(screen.getByRole("button", { name: /Experience BazarSync/i }))

    expect(await screen.findByText(/demo is not reachable right now/i)).toBeInTheDocument()
    expect(navigateMock).not.toHaveBeenCalled()
  })
})
