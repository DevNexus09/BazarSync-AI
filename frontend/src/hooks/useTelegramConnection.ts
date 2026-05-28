import { useCallback } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useAuth } from "@/hooks/use-auth"
import {
  createTelegramConnectToken,
  disconnectTelegram,
  getTelegramHealth,
  getTelegramStatus,
} from "@/services/telegram-service"
import type { TelegramConnectionStatus } from "@/types/telegram"
import {
  RealtimeEventName,
  type AlertSentEvent,
  type TelegramConnectedEvent,
  type TelegramDisconnectedEvent,
} from "@/types/realtime"
import { useSocketEvent } from "@/hooks/useSocketEvent"

export const telegramStatusQueryKey = ["telegram", "status"]
export const telegramHealthQueryKey = ["telegram", "health"]

const mapSnapshotToStatus = (
  snapshot: TelegramConnectedEvent["payload"]["connection"],
  current?: TelegramConnectionStatus
): TelegramConnectionStatus => ({
  isConnected: snapshot.isConnected,
  connectedAt: snapshot.connectedAt ?? null,
  telegramUsername: snapshot.telegramUsername ?? null,
  telegramFirstName: snapshot.telegramFirstName ?? null,
  telegramLastName: snapshot.telegramLastName ?? null,
  lastAlertSentAt: snapshot.lastAlertSentAt ?? current?.lastAlertSentAt ?? null,
  botUsername: current?.botUsername ?? null,
})

export function useTelegramConnection() {
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const status = useQuery({
    queryKey: telegramStatusQueryKey,
    queryFn: ({ signal }) => getTelegramStatus(signal),
    staleTime: 20_000,
    retry: 2,
  })

  const health = useQuery({
    queryKey: telegramHealthQueryKey,
    queryFn: ({ signal }) => getTelegramHealth(signal),
    staleTime: 30_000,
    retry: 1,
  })

  const connectToken = useMutation({
    mutationFn: createTelegramConnectToken,
  })

  const disconnect = useMutation({
    mutationFn: disconnectTelegram,
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: telegramStatusQueryKey })
      const previous =
        queryClient.getQueryData<TelegramConnectionStatus>(telegramStatusQueryKey)
      if (previous) {
        queryClient.setQueryData<TelegramConnectionStatus>(telegramStatusQueryKey, {
          ...previous,
          isConnected: false,
          connectedAt: null,
          telegramUsername: null,
          telegramFirstName: null,
          telegramLastName: null,
        })
      }
      return { previous }
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(telegramStatusQueryKey, context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: telegramStatusQueryKey })
    },
  })

  const handleConnected = useCallback(
    (event: TelegramConnectedEvent) => {
      queryClient.setQueryData<TelegramConnectionStatus>(
        telegramStatusQueryKey,
        (current) => mapSnapshotToStatus(event.payload.connection, current)
      )
    },
    [queryClient]
  )

  const handleDisconnected = useCallback(
    (event: TelegramDisconnectedEvent) => {
      queryClient.setQueryData<TelegramConnectionStatus>(
        telegramStatusQueryKey,
        (current) => mapSnapshotToStatus(event.payload.connection, current)
      )
    },
    [queryClient]
  )

  const handleAlertSent = useCallback(
    (event: AlertSentEvent) => {
      if (user?.id && event.sellerId && event.sellerId !== user.id) {
        return
      }
      queryClient.setQueryData<TelegramConnectionStatus>(
        telegramStatusQueryKey,
        (current) =>
          current
            ? {
                ...current,
                lastAlertSentAt: event.timestamp,
              }
            : current
      )
    },
    [queryClient, user]
  )

  useSocketEvent(RealtimeEventName.TelegramConnected, handleConnected)
  useSocketEvent(RealtimeEventName.TelegramDisconnected, handleDisconnected)
  useSocketEvent(RealtimeEventName.AlertSent, handleAlertSent)

  return {
    status,
    health,
    connectToken,
    disconnect,
  }
}
