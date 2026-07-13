import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import ForgotPasswordPage from "@/pages/auth/forgot-password-page"
import * as authService from "@/services/auth-service"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ status: "unauthenticated" }),
}))

vi.mock("@/services/auth-service", () => ({
  requestPasswordResetCode: vi.fn(),
  resendPasswordResetCode: vi.fn(),
  resetPassword: vi.fn(),
  verifyPasswordResetCode: vi.fn(),
}))

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/forgot-password"]}>
      <ForgotPasswordPage />
    </MemoryRouter>,
  )

describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.mocked(authService.requestPasswordResetCode).mockResolvedValue(
      "If an account exists for this email, a verification code has been sent.",
    )
    vi.mocked(authService.resendPasswordResetCode).mockResolvedValue(
      "If an account exists for this email, a verification code has been sent.",
    )
    vi.mocked(authService.verifyPasswordResetCode).mockResolvedValue({
      message: "Code verified.",
      resetAuthorization: "memory-only-reset-authorization",
      expiresAt: "2026-07-13T12:00:00Z",
    })
    vi.mocked(authService.resetPassword).mockResolvedValue("Password reset.")
  })

  afterEach(() => {
    cleanup()
  })

  it("renders the email step and shows the generic request response", async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText("Account email"), {
      target: { value: "Seller@Example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Send verification code" }))

    await waitFor(() => {
      expect(authService.requestPasswordResetCode).toHaveBeenCalledWith(
        "seller@example.com",
      )
    })
    expect(
      screen.getByText("If an account exists for this email, a verification code has been sent."),
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Verification code")).toBeInTheDocument()
  })

  it("accepts six digits, verifies the code, and renders the password step", async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText("Account email"), {
      target: { value: "seller@example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Send verification code" }))
    await screen.findByLabelText("Verification code")

    const verifyButton = screen.getByRole("button", { name: "Verify code" })
    expect(verifyButton).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Verification code"), {
      target: { value: "12a345678" },
    })
    expect(screen.getByLabelText("Verification code")).toHaveValue("123456")
    expect(verifyButton).toBeEnabled()
    fireEvent.click(verifyButton)

    await waitFor(() => {
      expect(authService.verifyPasswordResetCode).toHaveBeenCalledWith(
        "seller@example.com",
        "123456",
      )
    })
    expect(screen.getByLabelText("New password")).toBeInTheDocument()
  })

  it("shows password mismatch and never stores reset secrets in localStorage", async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText("Account email"), {
      target: { value: "seller@example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Send verification code" }))
    await screen.findByLabelText("Verification code")
    fireEvent.change(screen.getByLabelText("Verification code"), {
      target: { value: "123456" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }))
    await screen.findByLabelText("New password")

    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "new-secure-password" },
    })
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "different-password" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }))

    expect(await screen.findByText("The passwords do not match.")).toBeInTheDocument()
    expect(authService.resetPassword).not.toHaveBeenCalled()
    expect(window.localStorage?.length ?? 0).toBe(0)
  })

  it("resends only after the cooldown and prevents duplicate reset submissions", async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText("Account email"), {
      target: { value: "seller@example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Send verification code" }))
    await screen.findByLabelText("Verification code")

    expect(screen.getByRole("button", { name: /Resend in/ })).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Verification code"), {
      target: { value: "123456" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }))
    await screen.findByLabelText("New password")
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "new-secure-password" },
    })
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "new-secure-password" },
    })
    const resetButton = screen.getByRole("button", { name: "Reset password" })
    fireEvent.click(resetButton)
    fireEvent.click(resetButton)

    await waitFor(() => {
      expect(authService.resetPassword).toHaveBeenCalledTimes(1)
    })
  })
})
