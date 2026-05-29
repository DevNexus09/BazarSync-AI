import { useEffect, useMemo, useState } from "react"
import { CheckCircle2, ShieldAlert, Sparkles, XCircle } from "lucide-react"

import { ProductSelector } from "@/components/telegram/product-selector"
import { SendSnapshotButton } from "@/components/telegram/send-snapshot-button"
import { useProductSnapshot } from "@/hooks/useProductSnapshot"
import { cn } from "@/lib/utils"
import type { ProductSnapshotSendResponse } from "@/types/product-snapshot"
import { getErrorMessage } from "@/utils/errors"
import { formatCurrency, formatNumber } from "@/utils/formatters"

type ProductSnapshotCardProps = {
  isConnected: boolean
}

type ToastState = {
  message: string
  tone: "success" | "error"
}

type SnapshotStatus = {
  message: string
  tone: "success" | "error"
  sentAt?: string | null
  deliveryStatus?: string | null
}

export function ProductSnapshotCard({ isConnected }: ProductSnapshotCardProps) {
  const { productsQuery, sendSnapshot } = useProductSnapshot()
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [lastSnapshot, setLastSnapshot] = useState<SnapshotStatus | null>(null)

  const products = useMemo(
    () => productsQuery.data ?? [],
    [productsQuery.data]
  )
  const selectedProduct = useMemo(
    () => products.find((item) => item.id === selectedProductId) ?? null,
    [products, selectedProductId]
  )

  const isDisabled =
    !isConnected || productsQuery.isLoading || productsQuery.isError
  const canSend = Boolean(selectedProduct) && !isDisabled

  useEffect(() => {
    if (!toast) {
      return
    }
    const timer = window.setTimeout(() => setToast(null), 3500)
    return () => window.clearTimeout(timer)
  }, [toast])


  const handleSuccess = (data: ProductSnapshotSendResponse) => {
    setToast({
      message: data.message ?? "Snapshot sent successfully.",
      tone: "success",
    })
    setLastSnapshot({
      message: data.message ?? "Snapshot delivered to Telegram.",
      tone: "success",
      sentAt: data.sentAt,
      deliveryStatus: data.deliveryStatus,
    })
  }

  const handleError = (error: unknown) => {
    const message = getErrorMessage(
      error,
      "Unable to send the product snapshot."
    )
    setToast({ message, tone: "error" })
    setLastSnapshot({ message, tone: "error" })
  }

  const handleSend = () => {
    if (!selectedProduct || sendSnapshot.isPending) {
      return
    }
    sendSnapshot.mutate(selectedProduct.id, {
      onSuccess: handleSuccess,
      onError: handleError,
    })
  }

  return (
<<<<<<< HEAD
    <div className="glass-panel p-5">
      <div className="flex items-start gap-3">
        <div className="flex size-9 items-center justify-center rounded-full bg-primary/15 text-primary shadow-[0_0_12px_rgba(59,130,246,0.4)]">
=======
    <div className="rounded-xl border bg-background p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="flex size-9 items-center justify-center rounded-full bg-sky-100 text-sky-600">
>>>>>>> develop
          <Sparkles className="size-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground">
<<<<<<< HEAD
            Manual product alert
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Send a fresh intelligence snapshot directly to Telegram.
=======
            Product Intelligence Snapshot
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Send an instant intelligence summary to your Telegram inbox.
>>>>>>> develop
          </p>
        </div>
      </div>

      {!isConnected ? (
<<<<<<< HEAD
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <ShieldAlert className="mt-0.5 size-4" />
          Connect your Telegram account first to send product alerts.
=======
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <ShieldAlert className="mt-0.5 size-4" />
          Connect your Telegram account first to send product snapshots.
>>>>>>> develop
        </div>
      ) : null}

      {toast ? (
        <div
          className={cn(
            "mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold",
            toast.tone === "success"
<<<<<<< HEAD
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
              : "border-rose-500/30 bg-rose-500/10 text-rose-200"
=======
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-rose-200 bg-rose-50 text-rose-700"
>>>>>>> develop
          )}
          role="status"
          aria-live="polite"
        >
          {toast.tone === "success" ? (
            <CheckCircle2 className="size-4" />
          ) : (
            <XCircle className="size-4" />
          )}
          {toast.message}
        </div>
      ) : null}

      <div className="mt-4 space-y-4">
        <ProductSelector
          products={products}
          value={selectedProductId}
          onChange={setSelectedProductId}
          isLoading={productsQuery.isLoading}
          isError={productsQuery.isError}
          disabled={isDisabled}
        />

<<<<<<< HEAD
        <div className="rounded-lg border border-border/60 bg-card/60 p-3">
          <p className="text-xs font-semibold text-muted-foreground">
            Alert payload preview
=======
        <div className="rounded-lg border bg-muted/20 p-3">
          <p className="text-xs font-semibold text-muted-foreground">
            Product quick preview
>>>>>>> develop
          </p>
          {productsQuery.isLoading ? (
            <div className="mt-3 space-y-2">
              <div className="h-4 w-2/3 animate-pulse rounded bg-muted/40" />
              <div className="h-3 w-1/2 animate-pulse rounded bg-muted/40" />
              <div className="h-3 w-1/3 animate-pulse rounded bg-muted/40" />
            </div>
          ) : selectedProduct ? (
            <div className="mt-3 space-y-2 text-xs text-muted-foreground">
              <p className="text-sm font-semibold text-foreground">
                {selectedProduct.title}
              </p>
              <div className="flex items-center justify-between">
                <span>Current price</span>
                <span className="font-semibold text-foreground">
                  {formatCurrency(selectedProduct.sellingPrice)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Stock</span>
                <span className="font-semibold text-foreground">
                  {formatNumber(selectedProduct.stockQuantity)} units
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Lead time</span>
                <span className="font-semibold text-foreground">
                  {selectedProduct.supplierLeadTime} days
                </span>
              </div>
<<<<<<< HEAD
              <div className="flex items-center justify-between">
                <span>Competitor median</span>
                <span className="font-semibold text-foreground">Calculated on send</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Price gap</span>
                <span className="font-semibold text-foreground">Calculated on send</span>
              </div>
              <div className="flex items-center justify-between">
                <span>AI recommendation</span>
                <span className="font-semibold text-foreground">Generated on send</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Confidence</span>
                <span className="font-semibold text-foreground">Generated on send</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Opportunity score</span>
                <span className="font-semibold text-foreground">Generated on send</span>
              </div>
=======
>>>>>>> develop
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              Select a product to preview the latest intelligence snapshot.
            </p>
          )}
        </div>

        <SendSnapshotButton
          onClick={handleSend}
          disabled={!canSend}
          isLoading={sendSnapshot.isPending}
        />

<<<<<<< HEAD
        <div className="rounded-lg border border-border/60 px-3 py-3 text-xs text-muted-foreground">
=======
        <div className="rounded-lg border px-3 py-3 text-xs text-muted-foreground">
>>>>>>> develop
          <p className="font-semibold text-foreground">Last snapshot status</p>
          {lastSnapshot ? (
            <div className="mt-2 space-y-1">
              <p
                className={cn(
                  "font-semibold",
                  lastSnapshot.tone === "success"
<<<<<<< HEAD
                    ? "text-emerald-300"
                    : "text-rose-300"
=======
                    ? "text-emerald-600"
                    : "text-rose-600"
>>>>>>> develop
                )}
              >
                {lastSnapshot.message}
              </p>
              {lastSnapshot.sentAt ? (
                <p>
                  Sent at{" "}
                  <span className="font-semibold text-foreground">
                    {new Date(lastSnapshot.sentAt).toLocaleString()}
                  </span>
                </p>
              ) : null}
              {lastSnapshot.deliveryStatus ? (
                <p>
                  Delivery status{" "}
                  <span className="font-semibold text-foreground">
                    {lastSnapshot.deliveryStatus}
                  </span>
                </p>
              ) : null}
            </div>
          ) : (
            <p className="mt-2">No snapshots sent yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}
