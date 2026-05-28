import { io, type Socket } from "socket.io-client"

import { getAuthToken } from "@/services/auth-storage"
import { env } from "@/utils/env"
import type {
  RealtimeClientEvents,
  RealtimeServerEvents,
} from "@/types/realtime"

let socketInstance:
  | Socket<RealtimeServerEvents, RealtimeClientEvents>
  | null = null
const SOCKET_SESSION_KEY = "bazarsync.socket.session"

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "")

const normalizeSocketBaseUrl = (value: string, socketPath: string) => {
  try {
    const url = new URL(value)
    const normalizedPath = trimTrailingSlash(url.pathname)
    const normalizedSocketPath = trimTrailingSlash(socketPath)
    const mountPath = normalizedSocketPath.replace(/\/socket\.io$/, "")
    if (normalizedSocketPath && normalizedPath.endsWith(normalizedSocketPath)) {
      url.pathname =
        normalizedPath.slice(0, -normalizedSocketPath.length) || "/"
    } else if (mountPath && normalizedPath.endsWith(mountPath)) {
      url.pathname = normalizedPath.slice(0, -mountPath.length) || "/"
    }
    return trimTrailingSlash(url.toString())
  } catch {
    return value
  }
}

const resolveSocketUrl = () => {
  const configured =
    import.meta.env.VITE_SOCKET_URL ?? import.meta.env.VITE_SOCKET_BASE_URL
  const socketPath = resolveSocketPath()
  if (configured) {
    return normalizeSocketBaseUrl(configured, socketPath)
  }
  const normalizedApiBase = trimTrailingSlash(env.apiBaseUrl)
  return normalizedApiBase.replace(/\/api\/v\d+$/, "")
}

const resolveSocketPath = () => {
  return import.meta.env.VITE_SOCKET_PATH ?? "/ws/socket.io"
}

const getSocketSessionId = () => {
  if (typeof window === "undefined") {
    return undefined
  }
  const existing = window.localStorage.getItem(SOCKET_SESSION_KEY)
  if (existing) {
    return existing
  }
  const generated = crypto.randomUUID()
  window.localStorage.setItem(SOCKET_SESSION_KEY, generated)
  return generated
}

export const setSocketSessionId = (sessionId: string) => {
  if (typeof window === "undefined") {
    return
  }
  window.localStorage.setItem(SOCKET_SESSION_KEY, sessionId)
}

export const getSocket = () => {
  if (!socketInstance) {
    socketInstance = io(resolveSocketUrl(), {
      autoConnect: false,
      transports: ["websocket", "polling"],
      path: resolveSocketPath(),
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      randomizationFactor: 0.5,
      timeout: 8000,
      auth: {
        token: getAuthToken(),
        session_id: getSocketSessionId(),
      },
    })
  }

  return socketInstance
}

export const refreshSocketAuth = () => {
  if (!socketInstance) {
    return
  }
  socketInstance.auth = {
    token: getAuthToken(),
    session_id: getSocketSessionId(),
  }
}
