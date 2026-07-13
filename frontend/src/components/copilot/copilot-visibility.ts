const hiddenExactRoutes = new Set([
  "/",
  "/login",
  "/register",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/auth/callback",
])

const hiddenPathPrefixes = [
  "/settings",
  "/account",
  "/billing",
  "/app/settings",
  "/app/account",
  "/app/billing",
  "/app/profile",
  "/dashboard/settings",
  "/dashboard/account",
  "/dashboard/billing",
]

export function shouldShowCopilotWidget(pathname: string): boolean {
  const normalized =
    pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname

  if (hiddenExactRoutes.has(normalized)) {
    return false
  }

  if (!normalized.startsWith("/app")) {
    return false
  }

  return !hiddenPathPrefixes.some(
    (prefix) => normalized === prefix || normalized.startsWith(`${prefix}/`)
  )
}

