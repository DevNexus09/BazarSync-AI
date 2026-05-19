import * as React from "react"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import type { ProfileInput } from "@/types/auth"
import { getErrorMessage } from "@/utils/errors"
import { isValidPhone } from "@/utils/validation"

export default function ProfilePage() {
  const { user, updateProfile, isAuthenticating } = useAuth()
  const [formValues, setFormValues] = React.useState<ProfileInput>(() => ({
    fullName: user?.fullName ?? "",
    businessName: user?.businessName ?? "",
    industry: user?.industry ?? "",
    website: user?.website ?? "",
    addressLine: user?.addressLine ?? "",
    city: user?.city ?? "",
    country: user?.country ?? "",
    phone: user?.phone ?? "",
  }))
  const [fieldErrors, setFieldErrors] = React.useState<
    Partial<Record<keyof ProfileInput, string>>
  >({})
  const [formError, setFormError] = React.useState<string | null>(null)
  const [successMessage, setSuccessMessage] = React.useState<string | null>(null)

  const validateForm = (values: ProfileInput) => {
    const errors: Partial<Record<keyof ProfileInput, string>> = {}

    if (!values.fullName.trim()) {
      errors.fullName = "Full name is required."
    }
    if (!values.businessName.trim()) {
      errors.businessName = "Business name is required."
    }
    if (!values.industry.trim()) {
      errors.industry = "Industry is required."
    }
    if (!values.addressLine.trim()) {
      errors.addressLine = "Address is required."
    }
    if (!values.city.trim()) {
      errors.city = "City is required."
    }
    if (!values.country.trim()) {
      errors.country = "Country is required."
    }
    if (!values.phone.trim()) {
      errors.phone = "Phone number is required."
    } else if (!isValidPhone(values.phone)) {
      errors.phone = "Enter a valid phone number with country code."
    }
    if (values.website.trim() && !/^https?:\/\//i.test(values.website.trim())) {
      errors.website = "Website must start with http:// or https://."
    }

    return errors
  }

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setFormValues((prev) => ({ ...prev, [name]: value }))
    setFieldErrors((prev) => ({ ...prev, [name]: undefined }))
    setFormError(null)
    setSuccessMessage(null)
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)
    setSuccessMessage(null)

    const errors = validateForm(formValues)
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      return
    }

    try {
      await updateProfile(formValues)
      setSuccessMessage("Profile updated successfully.")
    } catch (error) {
      setFormError(getErrorMessage(error, "Unable to update your profile."))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        description="Complete your profile to personalize the BazarSync AI experience."
      />
      <div className="rounded-xl border bg-background p-6 shadow-sm">
        <div className="mb-6 space-y-1">
          <p className="text-sm font-medium text-foreground">
            Signed in as {user?.email ?? "seller"}
          </p>
          <p className="text-xs text-muted-foreground">
            Keep your details updated for accurate alerts and reports.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <AuthFormAlert message={formError} />
          {successMessage ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {successMessage}
            </div>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            <AuthField
              id="profile-full-name"
              name="fullName"
              label="Full name"
              value={formValues.fullName}
              onChange={handleChange}
              placeholder="e.g. Ayesha Rahman"
              error={fieldErrors.fullName}
            />
            <AuthField
              id="profile-business-name"
              name="businessName"
              label="Business name"
              value={formValues.businessName}
              onChange={handleChange}
              placeholder="e.g. Dhaka Gadgets"
              error={fieldErrors.businessName}
            />
            <AuthField
              id="profile-industry"
              name="industry"
              label="Industry"
              value={formValues.industry}
              onChange={handleChange}
              placeholder="e.g. Consumer electronics"
              error={fieldErrors.industry}
            />
            <AuthField
              id="profile-website"
              name="website"
              label="Website"
              value={formValues.website}
              onChange={handleChange}
              placeholder="https://example.com"
              error={fieldErrors.website}
            />
            <div className="md:col-span-2">
              <AuthField
                id="profile-address"
                name="addressLine"
                label="Business address"
                value={formValues.addressLine}
                onChange={handleChange}
                placeholder="Street address"
                error={fieldErrors.addressLine}
              />
            </div>
            <AuthField
              id="profile-city"
              name="city"
              label="City"
              value={formValues.city}
              onChange={handleChange}
              placeholder="e.g. Dhaka"
              error={fieldErrors.city}
            />
            <AuthField
              id="profile-country"
              name="country"
              label="Country"
              value={formValues.country}
              onChange={handleChange}
              placeholder="e.g. Bangladesh"
              error={fieldErrors.country}
            />
            <AuthField
              id="profile-phone"
              name="phone"
              type="tel"
              label="Phone number"
              value={formValues.phone}
              onChange={handleChange}
              placeholder="+8801XXXXXXXXX"
              error={fieldErrors.phone}
            />
          </div>
          <div className="flex justify-end">
            <Button type="submit" disabled={isAuthenticating}>
              {isAuthenticating ? "Saving..." : "Save profile"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
