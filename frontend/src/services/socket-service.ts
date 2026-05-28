import type { Socket } from "socket.io-client"

import { getSocket, refreshSocketAuth } from "@/lib/socket"
import type {
  RoomSubscriptionRequest,
  RealtimeClientEvents,
  RealtimeServerEvents,
} from "@/types/realtime"

export type RealtimeHandlers = Partial<RealtimeServerEvents>

export const connectRealtime = (): Socket<
  RealtimeServerEvents,
  RealtimeClientEvents
> => {
  const socket = getSocket()
  refreshSocketAuth()

  if (!socket.connected) {
    socket.connect()
  }

  return socket
}

export const disconnectRealtime = () => {
  const socket = getSocket()
  if (socket.connected) {
    socket.disconnect()
  }
}

export const subscribeRooms = (payload: RoomSubscriptionRequest) => {
  const socket = getSocket()
  socket.emit("subscribe_rooms", payload)
}

export const unsubscribeRooms = (payload: RoomSubscriptionRequest) => {
  const socket = getSocket()
  socket.emit("unsubscribe_rooms", payload)
}

export const sendHeartbeat = () => {
  const socket = getSocket()
  socket.emit("client_ping", { timestamp: Date.now() })
}

export const registerRealtimeHandlers = (handlers: RealtimeHandlers) => {
  const socket = getSocket()
  const entries = Object.entries(handlers) as Array<
    [keyof RealtimeServerEvents, RealtimeHandlers[keyof RealtimeServerEvents]]
  >

  entries.forEach(([event, handler]) => {
    if (handler) {
      socket.on(event, handler)
    }
  })

  return () => {
    entries.forEach(([event, handler]) => {
      if (handler) {
        socket.off(event, handler)
      }
    })
  }
}