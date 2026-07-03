import axios from "axios"
import { ZodError } from "zod"

type ApiErrorPayload = {
  error?: string
  message?: string
  detail?: string
}

export function getErrorMessage(
  error: unknown,
  fallback = "Something went wrong."
) {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as ApiErrorPayload | undefined
    return payload?.error ?? payload?.message ?? payload?.detail ?? error.message ?? fallback
  }

  if (error instanceof ZodError) {
    return error.issues[0]?.message ?? fallback
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}
