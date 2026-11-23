import { Sparkles } from "lucide-react"

import { t, type CopilotUiLanguage } from "@/components/copilot/copilot-i18n"
import type { CopilotStreamStage } from "@/types/copilot"

function stageLabel(stage: CopilotStreamStage | null | undefined, language: CopilotUiLanguage): string {
  const data = stage?.stage === "tool" ? stage.tool : stage?.stage === "planning" ? stage.tools[0] : undefined
  if (data) {
    return `${t(language, "stepLookup")} ${language === "en" ? data.toLowerCase() : data}`
  }
  if (stage?.stage === "planning") return t(language, "stagePlanning")
  if (stage?.stage === "writing") return t(language, "stageWriting")
  return t(language, "stageUnderstanding")
}

/** One quiet status line (spinning mark + shimmering text) that follows streamed stage events. */
export function CopilotStageSteps({ stage, language }: { stage?: CopilotStreamStage | null; language: CopilotUiLanguage }) {
  const label = stageLabel(stage, language)
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 px-1 py-1.5 text-sm">
      <Sparkles className="copilot-thinking-mark size-4 shrink-0 text-primary" aria-hidden="true" />
      <span key={label} className="copilot-shimmer copilot-fade-in truncate font-medium">
        {label}…
      </span>
    </div>
  )
}
