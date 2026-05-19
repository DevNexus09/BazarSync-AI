import axios, { AxiosHeaders } from "axios"

import { getAuthToken } from "@/services/auth-storage"
import { env } from "@/utils/env"

const apiClient = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: 15000,
})

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken()

  if (token) {
    const headers = AxiosHeaders.from(config.headers)
    headers.set("Authorization", `Bearer ${token}`)
    config.headers = headers
  }

  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
)

export default apiClient
