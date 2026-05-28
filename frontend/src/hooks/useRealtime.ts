import { useEffect, useRef, useState } from "react"

import { getSocket, refreshSocketAuth, setSocketSessionId } from "@/lib/socket"
import { connectRealtime, sendHeartbeat, subscribeRooms } from "@/services/socket-service"
import type { RealtimeStatus } from "@/types/dashboard"
import type {
  ConnectionEstablishedEvent,
  RoomSubscriptionRequest,
  RealtimeErrorEvent,
  RoomsUpdatedEvent,
  ServerPongEvent,
} from "@/types/realtime"
import { RealtimeEventName } from "@/types/realtime"

const initialStatus: RealtimeStatus = {
  connected: false,
  reconnecting: false,
  lastEventAt: null,
}

type UseRealtimeOptions = {
  rooms?: RoomSubscriptionRequest
  autoConnect?: boolean
  heartbeatIntervalMs?: number
}

export function useRealtime(options: UseRealtimeOptions = {}) {
  const { rooms, autoConnect = true, heartbeatIntervalMs = 15_000 } = options
  const [status, setStatus] = useState<RealtimeStatus>(initialStatus)
  const roomsRef = useRef<RoomSubscriptionRequest | undefined>(rooms)

  useEffect(() => {
    roomsRef.current = rooms
    if (!rooms) {
      return
    }
    const socket = getSocket()
    if (socket.connected) {
      subscribeRooms(rooms)
    }
  }, [rooms])

  useEffect(() => {
    if (!autoConnect) {
      return
    }
    const socket = connectRealtime()

    const handleConnect = () => {
      setStatus((previous) => ({
        ...previous,
        connected: true,
        reconnecting: false,
        transport: socket.io.engine?.transport?.name,
      }))
      const payload = roomsRef.current
      if (payload) {
        subscribeRooms(payload)
      }
    }

    const handleDisconnect = () => {
      setStatus((previous) => ({
        ...previous,
        connected: false,
        reconnecting: false,
      }))
    }

    const handleReconnectAttempt = () => {
      setStatus((previous) => ({
        ...previous,
        reconnecting: true,
      }))
    }

    const handleReconnect = () => {
      setStatus((previous) => ({
        ...previous,
        reconnecting: false,
      }))
    }

    const handleConnectError = (error: Error) => {
      setStatus((previous) => ({
        ...previous,
        reconnecting: false,
        lastError: error.message,
      }))
    }

    const handleAny = () => {
      setStatus((previous) => ({
        ...previous,
        lastEventAt: new Date().toISOString(),
      }))
    }

    socket.on("connect", handleConnect)
    socket.on("disconnect", handleDisconnect)
    socket.io.on("reconnect_attempt", handleReconnectAttempt)
    socket.io.on("reconnect", handleReconnect)
    socket.on("connect_error", handleConnectError)
    socket.onAny(handleAny)

    return () => {
      socket.off("connect", handleConnect)
      socket.off("disconnect", handleDisconnect)
      socket.io.off("reconnect_attempt", handleReconnectAttempt)
      socket.io.off("reconnect", handleReconnect)
      socket.off("connect_error", handleConnectError)
      socket.offAny(handleAny)
      socket.disconnect()
    }
  }, [autoConnect])

  useEffect(() => {
    if (!status.connected) {
      return
    }
    sendHeartbeat()
    const interval = window.setInterval(() => {
      sendHeartbeat()
    }, heartbeatIntervalMs)
    return () => window.clearInterval(interval)
  }, [status.connected, heartbeatIntervalMs])

  useEffect(() => {
    const socket = getSocket()

    const handleConnectionEstablished = (event: ConnectionEstablishedEvent) => {
      if (event.payload.sessionId) {
        setSocketSessionId(event.payload.sessionId)
        refreshSocketAuth()
      }
      setStatus((previous) => ({
        ...previous,
        rooms: event.payload.rooms,
        sessionId: event.payload.sessionId,
      }))
    }

    const handleRoomsUpdated = (event: RoomsUpdatedEvent) => {
      setStatus((previous) => ({
        ...previous,
        rooms: event.payload.rooms,
      }))
    }

    const handleServerPong = (event: ServerPongEvent) => {
      setStatus((previous) => ({
        ...previous,
        latencyMs: event.payload.latencyMs ?? null,
      }))
    }

    const handleRealtimeError = (event: RealtimeErrorEvent) => {
      setStatus((previous) => ({
        ...previous,
        lastError: event.payload.message,
      }))
    }

    socket.on(RealtimeEventName.ConnectionEstablished, handleConnectionEstablished)
    socket.on(RealtimeEventName.RoomsUpdated, handleRoomsUpdated)
    socket.on(RealtimeEventName.ServerPong, handleServerPong)
    socket.on(RealtimeEventName.RealtimeError, handleRealtimeError)

    return () => {
      socket.off(RealtimeEventName.ConnectionEstablished, handleConnectionEstablished)
      socket.off(RealtimeEventName.RoomsUpdated, handleRoomsUpdated)
      socket.off(RealtimeEventName.ServerPong, handleServerPong)
      socket.off(RealtimeEventName.RealtimeError, handleRealtimeError)
    }
  }, [])

  return status
}