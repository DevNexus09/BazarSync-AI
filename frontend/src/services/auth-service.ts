import apiClient from "@/api/client"
import type {
  AuthResponse,
  DeleteAccountInput,
  LoginInput,
  PasswordResetVerifyResponse,
  ProfileInput,
  RegisterInput,
  User,
} from "@/types/auth"

type ApiAuthResponse = {
  access_token: string
  token_type: string
  seller: ApiSeller
  message?: string
}

type ApiSeller = {
  id: string
  email: string
  phone: string | null
  full_name: string | null
  business_name: string | null
  industry: string | null
  website: string | null
  profile_image_url: string | null
  address_line: string | null
  city: string | null
  country: string | null
  created_at?: string
}

const mapUser = (seller: ApiSeller): User => ({
  id: String(seller.id),
  email: seller.email,
  phone: seller.phone ?? null,
  fullName: seller.full_name ?? null,
  businessName: seller.business_name ?? null,
  industry: seller.industry ?? null,
  website: seller.website ?? null,
  profileImageUrl: seller.profile_image_url ?? null,
  addressLine: seller.address_line ?? null,
  city: seller.city ?? null,
  country: seller.country ?? null,
  createdAt: seller.created_at,
})

export async function login(input: LoginInput): Promise<AuthResponse> {
  const payload = new URLSearchParams({
    username: input.email,
    password: input.password,
  })
  const { data } = await apiClient.post<ApiAuthResponse>("/auth/login", payload, {
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
  })
  return { token: data.access_token, user: mapUser(data.seller) }
}

// The free demo backend may be asleep, so allow time for it to wake up.
const DEMO_WAKE_TIMEOUT_MS = 120_000

export async function startDemo(): Promise<AuthResponse> {
  const { data } = await apiClient.post<ApiAuthResponse>("/auth/demo", undefined, {
    timeout: DEMO_WAKE_TIMEOUT_MS,
  })
  return { token: data.access_token, user: { ...mapUser(data.seller), isDemo: true } }
}

export async function register(input: RegisterInput): Promise<AuthResponse> {
  const { data } = await apiClient.post<ApiAuthResponse>("/auth/register", input)
  return { token: data.access_token, user: mapUser(data.seller) }
}

type ApiProfileUpdate = {
  phone?: string | null
  full_name?: string | null
  business_name?: string | null
  industry?: string | null
  website?: string | null
  profile_image_url?: string | null
  address_line?: string | null
  city?: string | null
  country?: string | null
}

const normalizeOptional = (value: string) => {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

export async function getProfile(): Promise<User> {
  const { data } = await apiClient.get<ApiSeller>("/auth/me")
  return mapUser(data)
}

export async function updateProfile(input: ProfileInput): Promise<User> {
  const payload: ApiProfileUpdate = {
    phone: normalizeOptional(input.phone),
    full_name: normalizeOptional(input.fullName),
    business_name: normalizeOptional(input.businessName),
    industry: normalizeOptional(input.industry),
    website: normalizeOptional(input.website),
    profile_image_url: normalizeOptional(input.profileImageUrl),
    address_line: normalizeOptional(input.addressLine),
    city: normalizeOptional(input.city),
    country: normalizeOptional(input.country),
  }
  const { data } = await apiClient.patch<ApiSeller>("/auth/profile", payload)
  return mapUser(data)
}

type ApiDeleteAccountPayload = {
  password: string
}

export async function deleteAccount(input: DeleteAccountInput): Promise<void> {
  const payload: ApiDeleteAccountPayload = {
    password: input.password,
  }
  await apiClient.post("/auth/delete-account", payload)
}

type ApiPasswordResetVerifyResponse = {
  message: string
  reset_authorization: string
  expires_at: string
}

export async function requestPasswordResetCode(email: string): Promise<string> {
  const { data } = await apiClient.post<{ message: string }>(
    "/auth/forgot-password/request-code",
    { email },
  )
  return data.message
}

export async function resendPasswordResetCode(email: string): Promise<string> {
  const { data } = await apiClient.post<{ message: string }>(
    "/auth/forgot-password/resend-code",
    { email },
  )
  return data.message
}

export async function verifyPasswordResetCode(
  email: string,
  code: string,
): Promise<PasswordResetVerifyResponse> {
  const { data } = await apiClient.post<ApiPasswordResetVerifyResponse>(
    "/auth/forgot-password/verify-code",
    { email, code },
  )
  return {
    message: data.message,
    resetAuthorization: data.reset_authorization,
    expiresAt: data.expires_at,
  }
}

export async function resetPassword(input: {
  resetAuthorization: string
  newPassword: string
  confirmPassword: string
}): Promise<string> {
  const { data } = await apiClient.post<{ message: string }>(
    "/auth/forgot-password/reset",
    {
      new_password: input.newPassword,
      confirm_password: input.confirmPassword,
    },
    {
      headers: {
        "X-Password-Reset-Authorization": input.resetAuthorization,
      },
    },
  )
  return data.message
}
