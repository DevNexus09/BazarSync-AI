import { Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"

type EmptyRecommendationStateProps = {
  onGenerate?: () => void
  isGenerating?: boolean
}

export function EmptyRecommendationState({
  onGenerate,
  isGenerating,
}: EmptyRecommendationStateProps) {
  return (
    <div className="flex w-full flex-col items-center justify-center gap-4 rounded-xl border border-dashed bg-background p-8 text-center">
      <div className="rounded-full bg-primary/10 p-3 text-primary">
        <Sparkles className="size-5" />
      </div>
      <div>
        <p className="text-sm font-semibold text-foreground">
          No AI recommendation yet
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Generate a fresh recommendation to see pricing, stock risk, and
          opportunity insights.
        </p>
      </div>
      {onGenerate ? (
        <Button onClick={onGenerate} disabled={isGenerating}>
          {isGenerating ? "Generating..." : "Generate AI Recommendation"}
        </Button>
      ) : null}
    </div>
  )
}
