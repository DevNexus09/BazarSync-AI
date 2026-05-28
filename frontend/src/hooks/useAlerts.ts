import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getActiveAlerts,
  getAlertHistory,
  getAlertSummary,
  resolveAlert,
} from "@/services/alert-service"
import { AlertStatus, type Alert } from "@/types/alert"

export const activeAlertsQueryKey = ["war-room", "alerts", "active"]
export const alertHistoryQueryKey = ["war-room", "alerts", "history"]
export const alertSummaryQueryKey = ["war-room", "alerts", "summary"]

export function useAlerts() {
  const activeAlerts = useQuery({
    queryKey: activeAlertsQueryKey,
    queryFn: ({ signal }) => getActiveAlerts(signal),
    staleTime: 10_000,
    retry: 2,
  })

  const alertHistory = useQuery({
    queryKey: alertHistoryQueryKey,
    queryFn: ({ signal }) => getAlertHistory(signal),
    staleTime: 30_000,
    retry: 2,
  })

  const alertSummary = useQuery({
    queryKey: alertSummaryQueryKey,
    queryFn: ({ signal }) => getAlertSummary(signal),
    staleTime: 20_000,
    retry: 2,
  })

  return {
    activeAlerts,
    alertHistory,
    alertSummary,
  }
}

export function useResolveAlert() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (alertId: string) => resolveAlert(alertId),
    onMutate: async (alertId) => {
      await queryClient.cancelQueries({ queryKey: alertHistoryQueryKey })
      await queryClient.cancelQueries({ queryKey: activeAlertsQueryKey })

      const previousHistory =
        queryClient.getQueryData<Alert[]>(alertHistoryQueryKey)
      const previousActive =
        queryClient.getQueryData<Alert[]>(activeAlertsQueryKey)

      const updateAlertList = (alerts?: Alert[]) =>
        alerts?.map((alert) =>
          alert.id === alertId
            ? { ...alert, status: AlertStatus.Resolved }
            : alert
        )

      if (previousHistory) {
        queryClient.setQueryData(
          alertHistoryQueryKey,
          updateAlertList(previousHistory)
        )
      }
      if (previousActive) {
        queryClient.setQueryData(
          activeAlertsQueryKey,
          updateAlertList(previousActive)
        )
      }

      return { previousHistory, previousActive }
    },
    onError: (_error, _alertId, context) => {
      if (context?.previousHistory) {
        queryClient.setQueryData(alertHistoryQueryKey, context.previousHistory)
      }
      if (context?.previousActive) {
        queryClient.setQueryData(activeAlertsQueryKey, context.previousActive)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: alertHistoryQueryKey })
      queryClient.invalidateQueries({ queryKey: activeAlertsQueryKey })
      queryClient.invalidateQueries({ queryKey: alertSummaryQueryKey })
    },
  })
}
