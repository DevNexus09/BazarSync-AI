import axios from "axios"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { getErrorMessage } from "@/utils/errors"

import {
  generateRecommendation,
  getLatestRecommendation,
  getRecommendationJob,
} from "../services/recommendationApi"
import type { RecommendationQueuedResult } from "../types/recommendation"

type Submission = { requestKey: string; jobId?: string }
type LegacyQueue = { task: RecommendationQueuedResult; queuedAt: number }
const LEGACY_POLL_LIMIT = 15 * 60_000

const sessionRejected = (error: unknown) => axios.isAxiosError(error) && error.response?.status === 401

function readSubmission(key: string): Submission | undefined {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "null") as Submission | null
    return typeof value?.requestKey === "string" ? value : undefined
  } catch {
    return undefined
  }
}

export function useRecommendation(productId: string | null | undefined) {
  const { user } = useAuth()
  const sellerId = user?.id
  const scope = `recommendation-job:${sellerId}:${productId}`
  const queryClient = useQueryClient()
  const [submissions, setSubmissions] = useState<Record<string, Submission>>({})
  const [legacy, setLegacy] = useState<Record<string, LegacyQueue>>({})
  const submitting = useRef(new Set<string>())
  const submission = submissions[scope] ?? (sellerId && productId ? readSubmission(scope) : undefined)
  const legacyQueue = legacy[scope]
  const [expiredQueue, setExpiredQueue] = useState<LegacyQueue>()
  const legacyExpired = legacyQueue !== undefined && expiredQueue === legacyQueue
  useEffect(() => {
    if (!legacyQueue) return
    const timer = window.setTimeout(
      () => setExpiredQueue(legacyQueue),
      Math.max(0, LEGACY_POLL_LIMIT - (Date.now() - legacyQueue.queuedAt)),
    )
    return () => window.clearTimeout(timer)
  }, [legacyQueue])
  const queryKey = ["recommendations", sellerId, productId]
  const jobId = submission?.jobId
  const jobKey = ["recommendation-job", sellerId, productId, jobId]
  const query = useQuery({
    queryKey,
    queryFn: () => getLatestRecommendation(productId ?? ""),
    enabled: Boolean(sellerId && productId),
    staleTime: 30_000,
    retry: (count, error) => count < 1 && !sessionRejected(error),
    refetchInterval: (state) => {
      if (!legacyQueue || legacyExpired || state.state.status === "error" || sessionRejected(queryClient.getQueryState(jobKey)?.error)) return false
      const createdAt = state.state.data?.createdAt
      return createdAt && Date.parse(createdAt) >= legacyQueue.queuedAt ? false : 5000
    },
  })
  const job = useQuery({
    queryKey: jobKey,
    queryFn: () => getRecommendationJob(productId ?? "", jobId),
    enabled: Boolean(sellerId && productId && !legacyQueue && !sessionRejected(query.error)),
    retry: (count, error) => count < 2 && !sessionRejected(error),
    refetchInterval: ({ state }) => {
      return state.data?.status === "PENDING" || state.data?.status === "RUNNING"
        ? state.status === "error" ? false : 2000
        : false
    },
    refetchOnWindowFocus: ({ state }) => !sessionRejected(state.error)
      && state.data?.status !== "COMPLETED" && state.data?.status !== "FAILED",
  })
  const jobActive = !job.isError && (
    Boolean(jobId && job.data === undefined) || job.data?.status === "PENDING" || job.data?.status === "RUNNING"
  )
  const legacyComplete = Boolean(
    legacyQueue && query.data?.createdAt && Date.parse(query.data.createdAt) >= legacyQueue.queuedAt
  )
  const legacyActive = Boolean(legacyQueue && !legacyExpired && !legacyComplete)

  function remember(key: string, value: Submission) {
    setSubmissions((current) => ({ ...current, [key]: value }))
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // The current view still tracks the job if browser storage is unavailable.
    }
  }

  const mutation = useMutation({
    mutationFn: ({ id, requestKey }: { id: string; requestKey: string; scope: string; sellerId: string }) =>
      generateRecommendation(id, requestKey),
    onSuccess: (payload, variables) => {
      const key = ["recommendations", variables.sellerId, variables.id]
      if ("queued" in payload) {
        if (payload.jobId) {
          setLegacy((current) => {
            const next = { ...current }
            delete next[variables.scope]
            return next
          })
          remember(variables.scope, { requestKey: variables.requestKey, jobId: payload.jobId })
        } else {
          setLegacy((current) => ({
            ...current,
            [variables.scope]: { task: payload, queuedAt: Date.now() },
          }))
          queryClient.invalidateQueries({ queryKey: key })
        }
      } else {
        queryClient.setQueryData(key, payload)
      }
    },
    onSettled: (_data, _error, variables) => {
      submitting.current.delete(variables.scope)
    },
  })
  const isQueued = jobActive || legacyActive
  const currentMutation = mutation.variables?.scope === scope
  const isSubmitting = currentMutation && mutation.isPending
  const sessionExpired = sessionRejected(query.error) || sessionRejected(job.error)
    || (currentMutation && sessionRejected(mutation.error))
  const jobResult = job.data && job.data.productId === productId && job.data.result?.productId === productId
    ? job.data.result : null
  const latest = query.data?.productId === productId ? query.data : null
  const jobCreatedAt = Date.parse(jobResult?.createdAt ?? "")
  const latestCreatedAt = Date.parse(latest?.createdAt ?? "")
  const latestIsNewer = latest && (
    !jobResult || latestCreatedAt > jobCreatedAt
    || (latestCreatedAt === jobCreatedAt && query.dataUpdatedAt > job.dataUpdatedAt)
  )
  const data = sessionExpired ? null : latestIsNewer ? latest : jobResult ?? latest
  const errorMessage =
    (currentMutation && mutation.isError
      ? getErrorMessage(mutation.error, "Recommendation generation failed. Please try again.")
      : null) ??
    (job.isError && !legacyQueue ? "Job status is temporarily unavailable. Refresh its status to continue." : null) ??
    (job.data?.status === "FAILED" ? job.data.errorMessage ?? "Recommendation generation failed. Please try again." : null) ??
    (jobId && job.data === null ? "This recommendation job is no longer available." : null) ??
    (legacyExpired && !legacyComplete
      ? "Recommendation generation did not finish in time. Please try again." : null) ??
    (query.isError && !data ? getErrorMessage(query.error, "We couldn't load your latest recommendation.") : null)

  function submit() {
    if (!sellerId || !productId || sessionExpired || isQueued || submitting.current.has(scope)) return
    if (job.isError && !legacyQueue) {
      void job.refetch()
      return
    }
    submitting.current.add(scope)
    const requestKey = !jobId && !legacyQueue && submission?.requestKey
      ? submission.requestKey
      : crypto.randomUUID()
    remember(scope, { requestKey })
    mutation.mutate({ id: productId, requestKey, scope, sellerId })
  }

  return {
    data,
    isLoading: !sessionExpired && (isSubmitting || query.isLoading || job.isLoading),
    isGenerating: !sessionExpired && (isSubmitting || isQueued),
    isFetching: query.isFetching,
    errorMessage: sessionExpired || errorMessage === null ? null : typeof errorMessage === "string" ? errorMessage : "The recommendation request failed.",
    sessionExpired,
    retryStatus: job.isError && !legacyQueue && !sessionExpired ? job.refetch : undefined,
    retryLatest: query.isError && !sessionExpired ? query.refetch : undefined,
    isQueued: !sessionExpired && isQueued,
    jobStatus: currentMutation && mutation.isError ? undefined : job.data?.status,
    generationFailed: (currentMutation && mutation.isError) || (legacyExpired && !legacyComplete),
    generateRecommendation: submit,
  }
}
