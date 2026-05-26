import { Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"

type GenerateRecommendationButtonProps = {
  onGenerate: () => void
  isLoading?: boolean
  disabled?: boolean
}

export function GenerateRecommendationButton({
  onGenerate,
  isLoading = false,
  disabled = false,
}: GenerateRecommendationButtonProps) {
  return (
    <Button onClick={onGenerate} disabled={disabled || isLoading} size="sm">
      {isLoading ? (
        <span className="flex items-center gap-2">
          <span className="size-3 animate-spin rounded-full border border-primary/30 border-t-primary" />
          Generating
        </span>
      ) : (
        <span className="flex items-center gap-2">
          <Sparkles className="size-4" />
          Generate AI Recommendation
        </span>
      )}
    </Button>
  )
}
