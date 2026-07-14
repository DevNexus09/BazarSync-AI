import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import LoginPage from "@/pages/auth/login-page"
import RegisterPage from "@/pages/auth/register-page"
import { ThemeProvider } from "@/components/theme/theme-provider"

const authMocks = vi.hoisted(() => ({
  status: "unauthenticated" as "authenticated" | "unauthenticated" | "loading",
  isAuthenticating: false,
  login: vi.fn(),
  register: vi.fn(),
}))

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => authMocks,
}))

function renderPage(page: ReactNode, initialPath: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>{page}</MemoryRouter>
    </ThemeProvider>
  )
}

beforeEach(() => {
  authMocks.status = "unauthenticated"
  authMocks.isAuthenticating = false
  authMocks.login.mockReset().mockResolvedValue(undefined)
  authMocks.register.mockReset().mockResolvedValue(undefined)
  document.documentElement.removeAttribute("data-theme")
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("public authentication pages", () => {
  it("keeps the login fields, forgot-password link, and submit behavior", async () => {
    renderPage(<LoginPage />, "/login")

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument()
    expect(screen.getByLabelText("Work email")).toBeInTheDocument()
    expect(screen.getByLabelText("Password")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute(
      "href",
      "/forgot-password"
    )

    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "seller@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct-password" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }))

    await waitFor(() => {
      expect(authMocks.login).toHaveBeenCalledWith({
        email: "seller@example.com",
        password: "correct-password",
      })
    })
  })

  it("keeps registration fields and submits the existing payload", async () => {
    renderPage(<RegisterPage />, "/register")

    expect(screen.getByRole("heading", { name: "Create your account" })).toBeInTheDocument()
    expect(screen.getByLabelText("Work email")).toBeInTheDocument()
    expect(screen.getByLabelText("Phone number")).toBeInTheDocument()
    expect(screen.getByLabelText("Password")).toBeInTheDocument()
    expect(screen.getAllByRole("link", { name: "Sign in" })).toHaveLength(2)
    for (const signInLink of screen.getAllByRole("link", { name: "Sign in" })) {
      expect(signInLink).toHaveAttribute("href", "/login")
    }

    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "seller@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Phone number"), {
      target: { value: "+8801712345678" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct-password" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Create account" }))

    await waitFor(() => {
      expect(authMocks.register).toHaveBeenCalledWith({
        email: "seller@example.com",
        phone: "+8801712345678",
        password: "correct-password",
      })
    })
  })

  it("renders validation errors without submitting", () => {
    renderPage(<LoginPage />, "/login")

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }))

    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument()
    expect(screen.getByText("Password must be at least 8 characters.")).toBeInTheDocument()
    expect(authMocks.login).not.toHaveBeenCalled()
  })
})
