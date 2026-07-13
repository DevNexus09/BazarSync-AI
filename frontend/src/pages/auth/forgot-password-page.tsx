import * as React from "react"
import { Eye, EyeOff, Loader2 } from "lucide-react"
import { Link, Navigate, useNavigate } from "react-router-dom"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFooterLink } from "@/components/auth/auth-footer-link"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { AuthLayout } from "@/components/auth/auth-layout"
import { LoadingState } from "@/components/common/loading-state"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/use-auth"
import {
  requestPasswordResetCode,
  resendPasswordResetCode,
  resetPassword,
  verifyPasswordResetCode,
} from "@/services/auth-service"
import { getErrorMessage } from "@/utils/errors"
import { isValidEmail, isValidPassword } from "@/utils/validation"

type ResetStep = "email" | "code" | "password" | "success"

const CODE_LENGTH = 6
const RESEND_COOLDOWN_SECONDS = 60

const normalizeEmail = (email: string) => email.trim().toLowerCase()

export default function ForgotPasswordPage() {
  const navigate = useNavigate()
  const { status } = useAuth()
  const [step, setStep] = React.useState<ResetStep>("email")
  const [email, setEmail] = React.useState("")
  const [code, setCode] = React.useState("")
  const [resetAuthorization, setResetAuthorization] = React.useState<string | null>(null)
  const [newPassword, setNewPassword] = React.useState("")
  const [confirmPassword, setConfirmPassword] = React.useState("")
  const [showNewPassword, setShowNewPassword] = React.useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = React.useState(false)
  const [cooldown, setCooldown] = React.useState(0)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [message, setMessage] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (cooldown <= 0) {
      return
    }

    const timer = window.setInterval(() => {
      setCooldown((current) => Math.max(0, current - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [cooldown])

  React.useEffect(() => {
    if (step !== "success") {
      return
    }

    const timer = window.setTimeout(() => {
      navigate("/login", { replace: true, state: { passwordReset: true } })
    }, 1600)
    return () => window.clearTimeout(timer)
  }, [navigate, step])

  if (status === "loading") {
    return <LoadingState label="Checking your session..." />
  }

  if (status === "authenticated") {
    return <Navigate to="/app/dashboard" replace />
  }

  const clearFeedback = () => {
    setError(null)
    setMessage(null)
  }

  const handleRequestCode = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    clearFeedback()
    const normalizedEmail = normalizeEmail(email)
    if (!isValidEmail(normalizedEmail)) {
      setError("Enter a valid email address.")
      return
    }

    setBusy(true)
    try {
      const response = await requestPasswordResetCode(normalizedEmail)
      setEmail(normalizedEmail)
      setCode("")
      setCooldown(RESEND_COOLDOWN_SECONDS)
      setMessage(response)
      setStep("code")
    } catch (err) {
      setError(getErrorMessage(err, "Unable to request a reset code right now."))
    } finally {
      setBusy(false)
    }
  }

  const handleVerifyCode = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    clearFeedback()
    if (code.length !== CODE_LENGTH) {
      setError("Enter the 6-digit code from your email.")
      return
    }

    setBusy(true)
    try {
      const response = await verifyPasswordResetCode(email, code)
      setResetAuthorization(response.resetAuthorization)
      setCode("")
      setMessage(null)
      setStep("password")
    } catch (err) {
      setError(getErrorMessage(err, "The code is invalid or has expired."))
    } finally {
      setBusy(false)
    }
  }

  const handleResendCode = async () => {
    if (busy || cooldown > 0) {
      return
    }
    clearFeedback()
    setBusy(true)
    try {
      const response = await resendPasswordResetCode(email)
      setCode("")
      setCooldown(RESEND_COOLDOWN_SECONDS)
      setMessage(response)
    } catch (err) {
      setError(getErrorMessage(err, "Please wait before requesting another code."))
    } finally {
      setBusy(false)
    }
  }

  const handleChangeEmail = () => {
    setEmail("")
    setCode("")
    setResetAuthorization(null)
    setCooldown(0)
    setStep("email")
    clearFeedback()
  }

  const handleResetPassword = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    clearFeedback()
    if (!resetAuthorization) {
      setError("Your reset session has expired. Start again.")
      setStep("email")
      return
    }
    if (!isValidPassword(newPassword)) {
      setError("Password must be at least 8 characters.")
      return
    }
    if (newPassword !== confirmPassword) {
      setError("The passwords do not match.")
      return
    }

    setBusy(true)
    try {
      await resetPassword({
        resetAuthorization,
        newPassword,
        confirmPassword,
      })
      setResetAuthorization(null)
      setNewPassword("")
      setConfirmPassword("")
      setStep("success")
    } catch (err) {
      const safeMessage = getErrorMessage(err, "Unable to reset your password right now.")
      setError(safeMessage)
      if (safeMessage.toLowerCase().includes("reset session")) {
        setResetAuthorization(null)
        setStep("email")
      }
    } finally {
      setBusy(false)
    }
  }

  const title =
    step === "email"
      ? "Forgot password?"
      : step === "code"
        ? "Check your email"
        : step === "password"
          ? "Create a new password"
          : "Password reset successful"
  const description =
    step === "email"
      ? "Enter your account email and we will send a one-time verification code."
      : step === "code"
        ? `Enter the 6-digit code sent to ${email}.`
        : step === "password"
          ? "Choose a new password for your BazarSync AI account."
          : "Please log in using your new password."

  return (
    <AuthLayout
      title={title}
      description={description}
      footer={
        <AuthFooterLink
          prompt="Remember your password?"
          to="/login"
          label="Back to sign in"
        />
      }
    >
      {step === "email" ? (
        <form onSubmit={handleRequestCode} className="space-y-5" noValidate>
          <AuthFormAlert message={error} />
          <AuthField
            id="forgot-password-email"
            name="email"
            type="email"
            label="Account email"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value)
              clearFeedback()
            }}
            placeholder="seller@company.com"
            autoComplete="email"
            inputMode="email"
            error={undefined}
          />
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {busy ? "Sending code..." : "Send verification code"}
          </Button>
        </form>
      ) : null}

      {step === "code" ? (
        <form onSubmit={handleVerifyCode} className="space-y-5" noValidate>
          <AuthFormAlert message={error} />
          {message ? (
            <div className="rounded-xl border border-primary/30 bg-primary/10 px-3 py-2 text-sm text-primary" aria-live="polite">
              {message}
            </div>
          ) : null}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground" htmlFor="forgot-password-code">
              Verification code
            </label>
            <Input
              id="forgot-password-code"
              name="code"
              value={code}
              onChange={(event) => {
                setCode(event.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH))
                clearFeedback()
              }}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={CODE_LENGTH}
              pattern="[0-9]{6}"
              placeholder="000000"
              aria-describedby="forgot-password-code-help"
              className="text-center text-2xl tracking-[0.4em]"
            />
            <p id="forgot-password-code-help" className="text-xs text-muted-foreground">
              The code expires soon. Never share it with anyone.
            </p>
          </div>
          <Button type="submit" className="w-full" disabled={busy || code.length !== CODE_LENGTH}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {busy ? "Verifying..." : "Verify code"}
          </Button>
          <div className="flex items-center justify-between gap-3 text-xs">
            <Button type="button" variant="ghost" size="sm" onClick={handleChangeEmail} disabled={busy}>
              Change email
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={handleResendCode} disabled={busy || cooldown > 0}>
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
            </Button>
          </div>
        </form>
      ) : null}

      {step === "password" ? (
        <form onSubmit={handleResetPassword} className="space-y-5" noValidate>
          <AuthFormAlert message={error} />
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground" htmlFor="forgot-password-new">
              New password
            </label>
            <div className="relative">
              <Input
                id="forgot-password-new"
                name="newPassword"
                type={showNewPassword ? "text" : "password"}
                value={newPassword}
                onChange={(event) => {
                  setNewPassword(event.target.value)
                  clearFeedback()
                }}
                autoComplete="new-password"
                className="pr-11"
              />
              <button
                type="button"
                aria-label={showNewPassword ? "Hide new password" : "Show new password"}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowNewPassword((visible) => !visible)}
              >
                {showNewPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            <p className="text-xs text-muted-foreground">Use at least 8 characters.</p>
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground" htmlFor="forgot-password-confirm">
              Confirm new password
            </label>
            <div className="relative">
              <Input
                id="forgot-password-confirm"
                name="confirmPassword"
                type={showConfirmPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(event) => {
                  setConfirmPassword(event.target.value)
                  clearFeedback()
                }}
                autoComplete="new-password"
                className="pr-11"
              />
              <button
                type="button"
                aria-label={showConfirmPassword ? "Hide confirmed password" : "Show confirmed password"}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowConfirmPassword((visible) => !visible)}
              >
                {showConfirmPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {busy ? "Resetting password..." : "Reset password"}
          </Button>
        </form>
      ) : null}

      {step === "success" ? (
        <div className="space-y-5 text-center" aria-live="polite">
          <div className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200">
            Password reset successful. Please log in using your new password.
          </div>
          <Button
            type="button"
            className="w-full"
            onClick={() => navigate("/login", { replace: true, state: { passwordReset: true } })}
          >
            Go to sign in
          </Button>
        </div>
      ) : null}

      {step !== "email" && step !== "success" ? (
        <p className="mt-5 text-center text-xs text-muted-foreground">
          <Link className="text-primary hover:underline" to="/login">
            Cancel and return to sign in
          </Link>
        </p>
      ) : null}
    </AuthLayout>
  )
}
