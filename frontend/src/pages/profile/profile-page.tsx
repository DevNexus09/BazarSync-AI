import * as React from "react"

import { AuthField } from "@/components/auth/auth-field"
import { AuthFormAlert } from "@/components/auth/auth-form-alert"
import { PageHeader } from "@/components/common/page-header"
import { TelegramStatusBadge } from "@/components/telegram/telegram-status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardBody, CardHeader } from "@/components/ui/card"
import { UrlTabs } from "@/components/ui/tabs"
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

  const initials =
    (formValues.fullName || user?.email || "U")
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((chunk) => chunk[0]?.toUpperCase())
      .join("") || "U"
  const photoUrl = formValues.profileImageUrl.trim()
  const avatar = (size: string) =>
    photoUrl ? (
      <img src={photoUrl} alt="" className={`${size} shrink-0 rounded-full object-cover`} />
    ) : (
      <div className={`${size} flex shrink-0 items-center justify-center rounded-full bg-primary/15 font-semibold text-primary`}>
        {initials}
      </div>
    )

  const profileTab = (
    <Card>
      <form onSubmit={handleSubmit}>
        <div className="grid gap-6 p-6 lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)] lg:gap-10">
          {sectionIntro(
            "Profile details",
            "Update seller and business information for tailored intelligence."
          )}
          <div className="space-y-6">
            <AuthFormAlert message={formError} />
            {successMessage ? (
              <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
                {successMessage}
              </div>
            ) : null}
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
              {avatar("size-20 text-xl ring-4 ring-primary/10")}
              <div className="min-w-0 flex-1 space-y-3">
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-muted-foreground">
                    Upload profile photo
                  </span>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    onChange={handleProfilePhotoChange}
                    className="block w-full text-sm text-muted-foreground file:mr-3 file:cursor-pointer file:rounded-lg file:border file:border-border/60 file:bg-muted/40 file:px-3 file:py-2 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted/70"
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
                <p className="text-xs text-muted-foreground">
                  Paste an image URL to show your photo in the top-right account
                  circle.
                </p>
              </div>
            </div>
            <div className="border-t border-border/60" />
            <div className="grid gap-x-4 gap-y-5 md:grid-cols-2">
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
          </div>
        </div>
        <div className="flex justify-end border-t border-border/60 bg-muted/10 px-6 py-4">
          <Button type="submit" disabled={isAuthenticating} className="min-w-32">
            {isSaving ? "Saving..." : "Save profile"}
          </Button>
        </div>
      </form>
    </Card>
  )

  const notificationsTab = (
    <div className="grid items-start gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader
          title="Telegram connection"
          description="Bot: @bazarsync_bot"
          actions={<TelegramStatusBadge state={telegramState} />}
        />
        <CardBody>
          <dl className="divide-y divide-border/60 text-sm">
            <div className="flex items-center justify-between gap-3 pb-3">
              <dt className="text-muted-foreground">Connected account</dt>
              <dd className="truncate font-medium text-foreground">
                {telegram.status.data?.telegramUsername
                  ? `@${telegram.status.data.telegramUsername}`
                  : "Not connected"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 pt-3">
              <dt className="text-muted-foreground">Last alert</dt>
              <dd className="text-right font-medium text-foreground">
                {telegram.status.data?.lastAlertSentAt
                  ? new Date(telegram.status.data.lastAlertSentAt).toLocaleString()
                  : "No alerts sent"}
              </dd>
            </div>
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Notification preferences"
          description="Configure how your team receives intelligence updates."
        />
        <CardBody>
          <ul className="divide-y divide-border/60 text-sm">
            {[
              "Realtime competitor alerts",
              "Stock risk notifications",
              "Weekly intelligence summary",
            ].map((label) => (
              <li
                key={label}
                className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
              >
                <span className="text-foreground">{label}</span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-300">
                  <span aria-hidden className="size-1.5 rounded-full bg-emerald-400" />
                  Enabled
                </span>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader
          title="Activity history"
          actions={
            <span className="rounded-full border border-border/60 px-2.5 py-0.5 text-xs text-muted-foreground">
              {formatNumber(alerts.alertHistory.data?.length ?? 0)} alerts
            </span>
          }
        />
        <CardBody>
          {activity.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border/60 px-4 py-8 text-center text-sm text-muted-foreground">
              Activity will appear once alerts are delivered.
            </div>
          ) : (
            <ol className="space-y-5 border-l border-border/60 pl-5">
              {activity.map((alert) => (
                <li key={alert.id} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[25px] top-1.5 size-2.5 rounded-full border-2 border-background bg-primary"
                  />
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p className="text-sm font-medium text-foreground">{alert.title}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {new Date(alert.createdAt).toLocaleString()}
                    </p>
                  </div>
                  <p className="mt-0.5 text-sm text-muted-foreground">{alert.message}</p>
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>
    </div>
  )

  const accountTab = (
    <Card className="border-rose-500/30">
      <div className="grid gap-6 p-6 lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)] lg:gap-10">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-rose-300">Delete account</h2>
          <p className="text-sm text-muted-foreground">
            Permanently removes your seller profile, products, alerts, and history.
          </p>
        </div>
        <form onSubmit={handleDeleteSubmit} className="max-w-md space-y-4">
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
          <Button type="submit" variant="destructive" disabled={isAuthenticating}>
            {isDeleting ? "Deleting..." : "Delete account"}
          </Button>
        </form>
      </div>
    </Card>
  )

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title="Settings"
        description="Manage account profile, Telegram status, and alert preferences."
      />

      <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex min-w-0 items-center gap-4">
          {avatar("size-14 text-base ring-4 ring-primary/10")}
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-foreground">
              {formValues.fullName || user?.email || "seller"}
            </p>
            <p className="truncate text-sm text-muted-foreground">
              Signed in as {user?.email ?? "seller"}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Keep your details updated for accurate alerts and recommendations.
            </p>
          </div>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300">
          <span aria-hidden className="size-1.5 rounded-full bg-emerald-400" />
          Account status: Active
        </span>
      </Card>

      <UrlTabs
        label="Settings sections"
        defaultValue="profile"
        tabs={[
          { value: "profile", label: "Profile", content: profileTab },
          { value: "notifications", label: "Notifications", content: notificationsTab },
          { value: "account", label: "Account", content: accountTab },
        ]}
      />
    </div>
  )
}

const sectionIntro = (title: string, description: string) => (
  <div className="space-y-1">
    <h2 className="text-base font-semibold text-foreground">{title}</h2>
    <p className="text-sm text-muted-foreground">{description}</p>
  </div>
)
