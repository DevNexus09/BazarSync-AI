import * as React from "react"
import { Navigate, useLocation, useNavigate, type Location } from "react-router-dom"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFooterLink } from "@/components/auth/auth-footer-link"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { AuthHighlights } from "@/components/auth/auth-highlights"
import { AuthLayout } from "@/components/auth/auth-layout"
import { LoadingState } from "@/components/common/loading-state"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import type { LoginInput } from "@/types/auth"
import { getErrorMessage } from "@/utils/errors"
import { isValidEmail, isValidPassword } from "@/utils/validation"

type LocationState = {
  from?: Location
}

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login, isAuthenticating, status } = useAuth()

  const [formError, setFormError] = React.useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = React.useState<
    Partial<Record<keyof LoginInput, string>>
  >({})
  const [formValues, setFormValues] = React.useState<LoginInput>({
    email: "",
    password: "",
  })

  const from =
    (location.state as LocationState | null)?.from?.pathname ?? "/app/dashboard"

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
    <AuthLayout
      title="Sign in"
      description="Access your AI-powered ecommerce intelligence dashboard."
      footer={
        <AuthFooterLink
          prompt="New to BazarSync AI?"
          to="/register"
          label="Create an account"
        />
      }
      sideContent={
        <AuthHighlights
          title="Stay ahead of the marketplace"
          description="Surface competitor moves, pricing shifts, and AI recommendations built for Bangladeshi sellers."
          highlights={[
            {
              title: "Competitor intelligence",
              description: "Monitor price drops and promotion cycles in real time.",
            },
            {
              title: "AI-powered recommendations",
              description: "Convert insights into next-best actions instantly.",
            },
            {
              title: "Telegram alerts",
              description: "Keep the team aligned with instant Telegram updates.",
            },
          ]}
        />
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
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
        <Button
          type="submit"
          className="w-full"
          disabled={isAuthenticating}
        >
          {isAuthenticating ? "Signing in..." : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  )
}
