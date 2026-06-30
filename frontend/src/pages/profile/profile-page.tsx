import * as React from "react"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { PageHeader } from "@/components/common/page-header"
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import { Button } from "@/components/ui/button"
import { useAlerts } from "@/hooks/useAlerts"
import { useAuth } from "@/hooks/use-auth"
import { useTelegramConnection } from "@/hooks/useTelegramConnection"
import type { ProfileInput } from "@/types/auth"
import type { TelegramConnectionState } from "@/types/telegram"
import { getErrorMessage } from "@/utils/errors"
import { formatNumber } from "@/utils/formatters"
import { isValidPhone } from "@/utils/validation"

export default function ProfilePage() {
  const { user, updateProfile, isAuthenticating, deleteAccount } = useAuth()
  const telegram = useTelegramConnection()
  const alerts = useAlerts()
  const [formValues, setFormValues] = React.useState<ProfileInput>(() => ({
    fullName: user?.fullName ?? "",
    businessName: user?.businessName ?? "",
    profileImageUrl: user?.profileImageUrl ?? "",
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
  const [deletePassword, setDeletePassword] = React.useState("")
  const [deleteFieldError, setDeleteFieldError] = React.useState<string | undefined>(
    undefined
  )
  const [deleteError, setDeleteError] = React.useState<string | null>(null)
  const [isDeleting, setIsDeleting] = React.useState(false)
  const isSaving = isAuthenticating && !isDeleting

  const telegramState: TelegramConnectionState = telegram.status.isError
    ? "error"
    : telegram.status.isLoading
      ? "connecting"
      : telegram.status.data?.isConnected
        ? "connected"
        : "not_connected"

  const activity = (alerts.alertHistory.data ?? []).slice(0, 4)

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
    if (
      values.profileImageUrl.trim() &&
      !/^https?:\/\//i.test(values.profileImageUrl.trim()) &&
      !/^data:image\/(png|jpe?g|webp|gif);base64,/i.test(values.profileImageUrl.trim())
    ) {
      errors.profileImageUrl = "Use an image URL or upload a PNG, JPG, WEBP, or GIF."
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

  const handleProfilePhotoChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    setFieldErrors((prev) => ({ ...prev, profileImageUrl: undefined }))
    setFormError(null)
    setSuccessMessage(null)

    if (!file) {
      return
    }
    if (!file.type.startsWith("image/")) {
      setFieldErrors((prev) => ({
        ...prev,
        profileImageUrl: "Choose an image file.",
      }))
      return
    }
    if (file.size > 750_000) {
      setFieldErrors((prev) => ({
        ...prev,
        profileImageUrl: "Choose an image smaller than 750 KB.",
      }))
      return
    }

    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : ""
      setFormValues((prev) => ({ ...prev, profileImageUrl: result }))
    }
    reader.onerror = () => {
      setFieldErrors((prev) => ({
        ...prev,
        profileImageUrl: "Could not read this image.",
      }))
    }
    reader.readAsDataURL(file)
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

  const handleDeleteChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setDeletePassword(event.target.value)
    setDeleteFieldError(undefined)
    setDeleteError(null)
  }

  const handleDeleteSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setDeleteError(null)
    setDeleteFieldError(undefined)

    if (!deletePassword.trim()) {
      setDeleteFieldError("Password is required.")
      return
    }

    const confirmed = window.confirm(
      "This will permanently delete your account and all data. This cannot be undone. Continue?"
    )
    if (!confirmed) {
      return
    }

    setIsDeleting(true)
    try {
      await deleteAccount({ password: deletePassword })
    } catch (error) {
      setDeleteError(getErrorMessage(error, "Unable to delete your account."))
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Manage account profile, Telegram status, and alert preferences."
      />

      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-6">
          <div className="glass-panel p-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">
                  Signed in as {user?.email ?? "seller"}
                </p>
                <p className="text-xs text-muted-foreground">
                  Keep your details updated for accurate alerts and recommendations.
                </p>
              </div>
              <span className="rounded-full border border-border/60 px-3 py-1 text-xs text-muted-foreground">
                Account status: Active
              </span>
            </div>
          </div>

          <div className="glass-panel p-6">
            <div className="mb-6 space-y-1">
              <h2 className="text-base font-semibold text-foreground">
                Profile details
              </h2>
              <p className="text-xs text-muted-foreground">
                Update seller and business information for tailored intelligence.
              </p>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <AuthFormAlert message={formError} />
              {successMessage ? (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
                  {successMessage}
                </div>
              ) : null}
              <div className="flex flex-col gap-4 rounded-xl border border-border/60 bg-muted/20 p-4 sm:flex-row sm:items-center">
                {formValues.profileImageUrl.trim() ? (
                  <img
                    src={formValues.profileImageUrl.trim()}
                    alt=""
                    className="size-20 rounded-full object-cover"
                  />
                ) : (
                  <div className="flex size-20 items-center justify-center rounded-full bg-muted/60 text-lg font-semibold text-foreground">
                    {(formValues.fullName || user?.email || "U")
                      .split(" ")
                      .filter(Boolean)
                      .slice(0, 2)
                      .map((chunk) => chunk[0]?.toUpperCase())
                      .join("") || "U"}
                  </div>
                )}
                <div className="flex-1">
                  <label className="mb-3 block">
                    <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                      Upload profile photo
                    </span>
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      onChange={handleProfilePhotoChange}
                      className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-lg file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-semibold file:text-primary-foreground"
                    />
                  </label>
                  <AuthField
                    id="profile-image-url"
                    name="profileImageUrl"
                    label="Or paste image URL"
                    value={formValues.profileImageUrl}
                    onChange={handleChange}
                    placeholder="https://example.com/profile-photo.jpg"
                    error={fieldErrors.profileImageUrl}
                  />
                  <p className="mt-2 text-xs text-muted-foreground">
                    Paste an image URL to show your photo in the top-right account
                    circle.
                  </p>
                </div>
              </div>
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
                  {isSaving ? "Saving..." : "Save profile"}
                </Button>
              </div>
            </form>
          </div>
        </div>

        <div className="space-y-6">
          <div className="glass-panel p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  Telegram connection
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Bot: @bazarsync_bot
                </p>
              </div>
              <TelegramStatusBadge state={telegramState} />
            </div>
            <div className="mt-4 space-y-2 text-xs text-muted-foreground">
              <div className="flex items-center justify-between">
                <span>Connected account</span>
                <span className="font-semibold text-foreground">
                  {telegram.status.data?.telegramUsername
                    ? `@${telegram.status.data.telegramUsername}`
                    : "Not connected"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Last alert</span>
                <span className="font-semibold text-foreground">
                  {telegram.status.data?.lastAlertSentAt
                    ? new Date(telegram.status.data.lastAlertSentAt).toLocaleString()
                    : "No alerts sent"}
                </span>
              </div>
            </div>
          </div>

          <div className="glass-panel p-5">
            <h3 className="text-sm font-semibold text-foreground">
              Notification preferences
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Configure how your team receives intelligence updates.
            </p>
            <div className="mt-4 space-y-3 text-xs text-muted-foreground">
              {[
                "Realtime competitor alerts",
                "Stock risk notifications",
                "Weekly intelligence summary",
              ].map((label) => (
                <label
                  key={label}
                  className="flex items-center justify-between rounded-lg border border-border/60 bg-card/60 px-3 py-2"
                >
                  <span>{label}</span>
                  <span className="text-emerald-300">Enabled</span>
                </label>
              ))}
            </div>
          </div>

          <div className="glass-panel p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">
                Activity history
              </h3>
              <span className="text-xs text-muted-foreground">
                {formatNumber(alerts.alertHistory.data?.length ?? 0)} alerts
              </span>
            </div>
            <div className="mt-4 space-y-3">
              {activity.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
                  Activity will appear once alerts are delivered.
                </div>
              ) : (
                activity.map((alert) => (
                  <div
                    key={alert.id}
                    className="rounded-lg border border-border/60 bg-card/60 px-3 py-2 text-xs text-muted-foreground"
                  >
                    <p className="text-sm font-semibold text-foreground">
                      {alert.title}
                    </p>
                    <p className="mt-1">{alert.message}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {new Date(alert.createdAt).toLocaleString()}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="glass-panel border border-rose-500/30 bg-rose-500/5 p-6">
        <div className="mb-4 space-y-1">
          <h2 className="text-base font-semibold text-foreground">Delete account</h2>
          <p className="text-xs text-muted-foreground">
            Permanently removes your seller profile, products, alerts, and history.
          </p>
        </div>
        <form onSubmit={handleDeleteSubmit} className="space-y-4">
          <AuthFormAlert message={deleteError} />
          <AuthField
            id="delete-account-password"
            name="deletePassword"
            type="password"
            label="Confirm password"
            value={deletePassword}
            onChange={handleDeleteChange}
            placeholder="••••••••"
            autoComplete="current-password"
            error={deleteFieldError}
          />
          <div className="flex items-center justify-end">
            <Button type="submit" variant="destructive" disabled={isAuthenticating}>
              {isDeleting ? "Deleting..." : "Delete account"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
