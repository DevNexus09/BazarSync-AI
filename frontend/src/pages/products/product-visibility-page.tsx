import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { PageHeader } from "@/components/common/page-header"
import { Button } from "@/components/ui/button"
import { deadStockKeys } from "@/hooks/useDeadStock"
import { createVisibilityMetric } from "@/services/phase9-setup-service"

export default function ProductVisibilityPage() {
  const { productId = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [marketplace, setMarketplace] = useState("DARAZ")
  const [metricDate, setMetricDate] = useState(new Date().toISOString().slice(0, 10))
  const [impressions, setImpressions] = useState("0")
  const [views, setViews] = useState("0")
  const [clicks, setClicks] = useState("0")
  const [searchRank, setSearchRank] = useState("")
  const [listingQualityScore, setListingQualityScore] = useState("")
  const [conversionRate, setConversionRate] = useState("")
  const [source, setSource] = useState("manual")
  const mutation = useMutation({
    mutationFn: () =>
      createVisibilityMetric({
        productId,
        marketplace,
        metricDate,
        impressions: Number(impressions),
        views: Number(views),
        clicks: Number(clicks),
        searchRank: searchRank ? Number(searchRank) : null,
        listingQualityScore: listingQualityScore ? Number(listingQualityScore) : null,
        conversionRate: conversionRate ? Number(conversionRate) : null,
        source,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: deadStockKeys.all })
    },
  })
  const invalid = [impressions, views, clicks].some((value) => Number(value) < 0)
  return (
    <div className="space-y-6">
      <PageHeader title="Add visibility metrics" description="Visibility data is optional for dead-stock classification, but it is required before SEO recovery recommendations can be evaluated." />
      <div className="glass-panel max-w-2xl space-y-4 p-4">
        {mutation.isSuccess ? <p className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 p-3 text-sm text-emerald-100">Visibility metrics saved. SEO recovery can be evaluated after Phase 9 analysis runs.</p> : null}
        {mutation.isError ? <p className="rounded-lg border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-100">Could not save visibility metrics. Check nonnegative values and date.</p> : null}
        <Field label="Marketplace" value={marketplace} onChange={setMarketplace} />
        <Field label="Metric date" type="date" value={metricDate} onChange={setMetricDate} />
        <Field label="Impressions" type="number" value={impressions} onChange={setImpressions} />
        <Field label="Views" type="number" value={views} onChange={setViews} />
        <Field label="Clicks" type="number" value={clicks} onChange={setClicks} />
        <Field label="Search rank" type="number" value={searchRank} onChange={setSearchRank} />
        <Field label="Listing quality score" type="number" value={listingQualityScore} onChange={setListingQualityScore} />
        <Field label="Conversion rate" type="number" value={conversionRate} onChange={setConversionRate} />
        <Field label="Source" value={source} onChange={setSource} />
        {invalid ? <p className="text-sm text-red-200">Visibility metrics cannot be negative.</p> : null}
        <div className="flex gap-2">
          <Button disabled={!productId || invalid || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "Saving..." : "Save visibility metrics"}</Button>
          <Button variant="outline" onClick={() => navigate("/app/inventory-intelligence")}>Back to dashboard</Button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return <label className="flex flex-col gap-1 text-sm text-muted-foreground">{label}<input className="h-10 rounded-lg border border-border bg-background px-3 text-foreground" type={type} value={value} onChange={(event) => onChange(event.target.value)} /></label>
}
