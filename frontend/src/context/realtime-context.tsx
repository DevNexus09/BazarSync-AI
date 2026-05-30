/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from "react"

import { useLiveDashboard } from "@/hooks/useLiveDashboard"
import type { RealtimeStatus } from "@/types/dashboard"

const fallbackStatus: RealtimeStatus = {
  connected: false,
  reconnecting: false,
  lastEventAt: null,
}

const RealtimeContext = createContext<RealtimeStatus | null>(null)

type RealtimeProviderProps = {
  sellerId?: string
  children: ReactNode
}

export function RealtimeProvider({ sellerId, children }: RealtimeProviderProps) {
  const status = useLiveDashboard({ sellerId, enabled: Boolean(sellerId) })

  return <RealtimeContext.Provider value={status}>{children}</RealtimeContext.Provider>
}

export function useRealtimeStatus() {
  return useContext(RealtimeContext) ?? fallbackStatus
}
