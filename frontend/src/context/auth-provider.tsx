import * as React from "react"

import type {
  AuthContextValue,
  AuthResponse,
  AuthState,
  LoginInput,
  ProfileInput,
  RegisterInput,
} from "@/types/auth"
import {
  login as loginService,
  register as registerService,
  updateProfile as updateProfileService,
} from "@/services/auth-service"
import {
  clearAuthToken,
  clearStoredUser,
  getAuthToken,
  getStoredUser,
  setAuthToken,
  setStoredUser,
} from "@/services/auth-storage"
import { AuthContext } from "@/context/auth-context"

const initialState: AuthState = (() => {
  const token = getAuthToken()
  const user = getStoredUser()

  if (token && user) {
    return { status: "authenticated", token, user }
  }

  return { status: "unauthenticated", token: null, user: null }
})()

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AuthState>(initialState)
  const [isAuthenticating, setIsAuthenticating] = React.useState(false)

  const applyAuthSuccess = React.useCallback((response: AuthResponse) => {
    setAuthToken(response.token)
    setStoredUser(response.user)
    setState({
      status: "authenticated",
      token: response.token,
      user: response.user,
    })
  }, [])

  const login = React.useCallback(
    async (input: LoginInput) => {
      setIsAuthenticating(true)

      try {
        const response = await loginService(input)
        applyAuthSuccess(response)
      } finally {
        setIsAuthenticating(false)
      }
    },
    [applyAuthSuccess]
  )

  const register = React.useCallback(
    async (input: RegisterInput) => {
      setIsAuthenticating(true)

      try {
        const response = await registerService(input)
        applyAuthSuccess(response)
      } finally {
        setIsAuthenticating(false)
      }
    },
    [applyAuthSuccess]
  )

  const updateProfile = React.useCallback(
    async (input: ProfileInput) => {
      setIsAuthenticating(true)

      try {
        const updatedUser = await updateProfileService(input)
        setStoredUser(updatedUser)
        setState((prev) => ({
          ...prev,
          user: updatedUser,
        }))
      } finally {
        setIsAuthenticating(false)
      }
    },
    []
  )

  const logout = React.useCallback(() => {
    clearAuthToken()
    clearStoredUser()
    setState({ status: "unauthenticated", token: null, user: null })
  }, [])

  const value = React.useMemo<AuthContextValue>(
    () => ({
      ...state,
      isAuthenticating,
      login,
      register,
      updateProfile,
      logout,
    }),
    [state, isAuthenticating, login, register, updateProfile, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
