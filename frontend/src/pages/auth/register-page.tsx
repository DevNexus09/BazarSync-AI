import * as React from "react"
import { Navigate, useNavigate } from "react-router-dom"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFooterLink } from "@/components/auth/auth-footer-link"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { AuthHighlights } from "@/components/auth/auth-highlights"
import { AuthLayout } from "@/components/auth/auth-layout"
import { LoadingState } from "@/components/common/loading-state"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import type { RegisterInput } from "@/types/auth"
import { getErrorMessage } from "@/utils/errors"
import {
  isValidEmail,
  isValidPassword,
  isValidPhone,
} from "@/utils/validation"

export default function RegisterPage() {
  const navigate = useNavigate()
  const { register, isAuthenticating, status } = useAuth()

  const [formError, setFormError] = React.useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = React.useState<
    Partial<Record<keyof RegisterInput, string>>
  >({})
  const [formValues, setFormValues] = React.useState<RegisterInput>({
    email: "",
    password: "",
    phone: "",
  })

  if (status === "loading") {
    return <LoadingState label="Checking your session..." />
  }

  if (status === "authenticated") {
    return <Navigate to="/app/dashboard" replace />
  }

  const validateForm = (values: RegisterInput) => {
    const errors: Partial<Record<keyof RegisterInput, string>> = {}

    if (!isValidEmail(values.email)) {
      errors.email = "Enter a valid email address."
    }

    if (!isValidPhone(values.phone)) {
      errors.phone = "Enter a valid phone number with country code."
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
      await register(formValues)
      navigate("/app/dashboard", { replace: true })
    } catch (err) {
      setFormError(getErrorMessage(err, "Unable to create your account."))
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      description="Start tracking competitors, pricing, and AI recommendations today."
      footer={
        <AuthFooterLink
          prompt="Already have an account?"
          to="/login"
          label="Sign in"
        />
      }
      sideContent={
        <AuthHighlights
          title="Launch BazarSync AI"
          description="Get the signals you need to act faster in the Bangladeshi ecommerce market."
          highlights={[
            {
              title: "Realtime monitoring",
              description: "Stay ahead of sudden demand spikes and price moves.",
            },
            {
              title: "AI recommendations",
              description: "Turn insights into measurable revenue improvements.",
            },
            {
              title: "Team-ready alerts",
              description: "Keep ops and sales aligned with Telegram notifications.",
            },
          ]}
        />
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <AuthFormAlert message={formError} />
        <AuthField
          id="register-email"
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
          id="register-phone"
          name="phone"
          type="tel"
          label="Phone number"
          value={formValues.phone}
          onChange={handleChange}
          placeholder="+8801XXXXXXXXX"
          autoComplete="tel"
          inputMode="tel"
          error={fieldErrors.phone}
        />
        <AuthField
          id="register-password"
          name="password"
          type="password"
          label="Password"
          value={formValues.password}
          onChange={handleChange}
          placeholder="Minimum 8 characters"
          autoComplete="new-password"
          error={fieldErrors.password}
        />
        <Button
          type="submit"
          className="w-full"
          disabled={isAuthenticating}
        >
          {isAuthenticating ? "Creating account..." : "Create account"}
        </Button>
        <p className="text-xs text-muted-foreground">
          By signing up, you agree to BazarSync AI’s terms of service and privacy
          policy.
        </p>
      </form>
    </AuthLayout>
  )
}
