import * as React from "react"
import { Loader2 } from "lucide-react"
import { Link, Navigate, useLocation, useNavigate, type Location } from "react-router-dom"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFooterLink } from "@/components/auth/auth-footer-link"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { LoadingState } from "@/components/common/loading-state"
import { PublicAuthLayout } from "@/components/public/public-auth-layout"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import type { LoginInput } from "@/types/auth"
import { getErrorMessage } from "@/utils/errors"
import { isValidEmail, isValidPassword } from "@/utils/validation"

type LocationState = {
  from?: Location
  passwordReset?: boolean
}

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login, isAuthenticating, status } = useAuth()

  const [formError, setFormError] = React.useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = React.useState<
    Partial<Record<keyof LoginInput, string>>
  >({})
  const [rememberMe, setRememberMe] = React.useState(true)
  const [formValues, setFormValues] = React.useState<LoginInput>({
    email: "",
    password: "",
  })

  const from =
    (location.state as LocationState | null)?.from?.pathname ?? "/app/dashboard"
  const passwordReset = (location.state as LocationState | null)?.passwordReset

  if (status === "loading") {
    return <LoadingState label="Checking your session..." />
  }

  if (status === "authenticated") {
    return <Navigate to="/app/dashboard" replace />
  }

  const validateForm = (values: LoginInput) => {
    const errors: Partial<Record<keyof LoginInput, string>> = {}

    if (!isValidEmail(values.email)) {
      errors.email = "Enter a valid email address."
    }

    if (!isValidPassword(values.password)) {
      errors.password = "Password must be at least 8 characters."
    }

    return errors
  }

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setFormValues((prev) => ({ ...prev, [name]: value }))
    setFieldErrors((prev) => ({ ...prev, [name]: undefined }))
    setFormError(null)
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)
    const validationErrors = validateForm(formValues)

    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors)
      return
    }

    try {
      await login(formValues)
      navigate(from, { replace: true })
    } catch (err) {
      setFormError(getErrorMessage(err, "Unable to sign in right now."))
    }
  }

  return (
    <PublicAuthLayout
      title="Sign in"
      description="Sign in to continue to your marketplace intelligence workspace."
      action={
        <Link
          className="rounded-lg px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          to="/register"
        >
          Create account
        </Link>
      }
      footer={
        <AuthFooterLink
          prompt="New to BazarSync AI?"
          to="/register"
          label="Create an account"
        />
      }
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        {passwordReset ? (
          <div className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-success">
            Password reset successfully. Sign in with your new password.
          </div>
        ) : null}
        <AuthFormAlert message={formError} />
        <AuthField
          id="login-email"
          name="email"
          type="email"
          label="Work email"
          value={formValues.email}
          onChange={handleChange}
          placeholder="seller@company.com"
          autoComplete="email"
          inputMode="email"
          error={fieldErrors.email}
        />
        <AuthField
          id="login-password"
          name="password"
          type="password"
          label="Password"
          value={formValues.password}
          onChange={handleChange}
          placeholder="••••••••"
          autoComplete="current-password"
          error={fieldErrors.password}
        />
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(event) => setRememberMe(event.target.checked)}
              className="size-4 rounded border-border/70 bg-card/60"
            />
            Remember me
          </label>
          <Link className="text-primary hover:underline" to="/forgot-password">
            Forgot password?
          </Link>
        </div>
        <Button
          type="submit"
          className="w-full"
          disabled={isAuthenticating}
        >
          {isAuthenticating ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Signing in...
            </>
          ) : (
            "Sign in"
          )}
        </Button>
      </form>
    </PublicAuthLayout>
  )
}
