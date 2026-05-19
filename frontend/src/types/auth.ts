export type AuthStatus = "authenticated" | "unauthenticated" | "loading"

export type User = {
  id: string
  email: string
  phone: string | null
  fullName: string | null
  businessName: string | null
  industry: string | null
  website: string | null
  addressLine: string | null
  city: string | null
  country: string | null
  createdAt?: string
}

export type LoginInput = {
  email: string
  password: string
}

export type RegisterInput = {
  email: string
  password: string
  phone: string
}

export type AuthResponse = {
  token: string
  user: User
}

export type ProfileInput = {
  fullName: string
  businessName: string
  industry: string
  website: string
  addressLine: string
  city: string
  country: string
  phone: string
}

export type AuthState = {
  status: AuthStatus
  user: User | null
  token: string | null
}

export type AuthContextValue = AuthState & {
  isAuthenticating: boolean
  login: (input: LoginInput) => Promise<void>
  register: (input: RegisterInput) => Promise<void>
  updateProfile: (input: ProfileInput) => Promise<void>
  logout: () => void
}
