import type { User } from "@/types/auth"

const TOKEN_KEY = "smeboost.auth.token"
const USER_KEY = "smeboost.auth.user"

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setAuthToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)

  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as Partial<Record<string, unknown>>
    const createdAt =
      (parsed.createdAt as string | undefined) ??
      (parsed.created_at as string | undefined)
    const fullName =
      (parsed.fullName as string | null | undefined) ??
      (parsed.full_name as string | null | undefined) ??
      null
    const businessName =
      (parsed.businessName as string | null | undefined) ??
      (parsed.business_name as string | null | undefined) ??
      null
    const industry =
      (parsed.industry as string | null | undefined) ?? null
    const website =
      (parsed.website as string | null | undefined) ?? null
    const addressLine =
      (parsed.addressLine as string | null | undefined) ??
      (parsed.address_line as string | null | undefined) ??
      null
    const city = (parsed.city as string | null | undefined) ?? null
    const country = (parsed.country as string | null | undefined) ?? null

    if (!parsed.id || !parsed.email) {
      return null
    }

    return {
      id: String(parsed.id),
      email: String(parsed.email),
      phone: (parsed.phone as string | null | undefined) ?? null,
      fullName,
      businessName,
      industry,
      website,
      addressLine,
      city,
      country,
      createdAt,
    }
  } catch (error) {
    console.error("Invalid stored user payload.", error)
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export function setStoredUser(user: User) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearStoredUser() {
  localStorage.removeItem(USER_KEY)
}
