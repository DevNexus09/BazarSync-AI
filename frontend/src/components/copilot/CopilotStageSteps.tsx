import { Check } from "lucide-react"

import { stageText, t, type CopilotUiLanguage } from "@/components/copilot/copilot-i18n"
import { cn } from "@/lib/utils"
import type { CopilotStreamStage } from "@/types/copilot"

const STEP_INDEX: Record<CopilotStreamStage["stage"], number> = { understanding: 0, planning: 1, tool: 1, writing: 2 }

/** Understanding → Looking up <data> → Writing, driven by streamed stage events. */
export function CopilotStageSteps({ stage, language }: { stage: CopilotStreamStage; language: CopilotUiLanguage }) {
  const current = STEP_INDEX[stage.stage]
  const data =
    stage.stage === "tool" ? stage.tool : stage.stage === "planning" && stage.tools[0] ? stage.tools[0] : t(language, "stepLookupData")
  const labels = [t(language, "stepUnderstand"), `${t(language, "stepLookup")} ${language === "en" ? data.toLowerCase() : data}`, t(language, "stepWrite")]

  return (
    <div className="rounded-2xl border border-border/60 bg-card px-3 py-2.5">
      <ol aria-label={t(language, "progress")} className="flex flex-wrap items-center gap-1.5 text-xs">
        {labels.map((label, index) => {
          const state = index < current ? "done" : index === current ? "active" : "todo"
          return (
            <li
              key={index}
              data-state={state}
              aria-current={state === "active" ? "step" : undefined}
              className={cn(
                "inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors duration-200 motion-reduce:transition-none",
                state === "done" && "border-border/60 text-muted-foreground",
                state === "active" && "border-primary/40 bg-primary/10 font-medium text-foreground",
                state === "todo" && "border-dashed border-border/60 text-muted-foreground/80"
              )}
            >
              {state === "done" ? (
                <Check className="size-3 shrink-0" aria-hidden="true" />
              ) : (
                <span
                  aria-hidden="true"
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    state === "active" ? "animate-pulse bg-primary motion-reduce:animate-none" : "bg-muted-foreground/40"
                  )}
                />
              )}
              <span className="truncate">{label}</span>
            </li>
          )
        })}
      </ol>
      {/* The precise stage ("Checked: Revenue summary") for screen readers. */}
      <p className="sr-only" aria-live="polite">
        {stageText(stage, language)}
      </p>
    </div>
  )
}
