import { useEffect } from "react"

import { getSocket } from "@/lib/socket"
import type { RealtimeServerEvents } from "@/types/realtime"

type SocketEventKey = keyof RealtimeServerEvents

type UseSocketEventOptions = {
  enabled?: boolean
}

export function useSocketEvent<E extends SocketEventKey>(
  event: E,
  handler: RealtimeServerEvents[E],
  options: UseSocketEventOptions = {}
) {
  useEffect(() => {
    if (options.enabled === false) {
      return
    }
    const socket = getSocket()
    const listener = handler as RealtimeServerEvents[keyof RealtimeServerEvents]
    socket.on(event as keyof RealtimeServerEvents, listener)
    return () => {
      socket.off(event as keyof RealtimeServerEvents, listener)
    }
  }, [event, handler, options.enabled])
}
