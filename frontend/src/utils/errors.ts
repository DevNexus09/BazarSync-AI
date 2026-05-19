import axios from "axios"

type ApiErrorPayload = {
  message?: string
  detail?: string
}

export function getErrorMessage(
  error: unknown,
  fallback = "Something went wrong."
) {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as ApiErrorPayload | undefined
    return payload?.message ?? payload?.detail ?? error.message ?? fallback
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}
