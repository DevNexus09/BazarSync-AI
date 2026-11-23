import { useEffect, useRef } from "react"
import { Sparkles } from "lucide-react"

import { CopilotAssistantMessage, type CopilotAssistantActions } from "@/components/copilot/CopilotAssistantMessage"
import { CopilotStageSteps } from "@/components/copilot/CopilotStageSteps"
import { langAttribute, t, type CopilotUiLanguage } from "@/components/copilot/copilot-i18n"
import type { CopilotActionProposal, CopilotLocalMessage, CopilotStreamStage } from "@/types/copilot"

export function CopilotMessageList({
  messages,
  isLoading,
  stage,
  onProposalChange,
  language = "en",
  actions,
}: {
  messages: CopilotLocalMessage[]
  isLoading: boolean
  /** Streamed stage; without one (non-streaming) a single "checking" line shows. */
  stage?: CopilotStreamStage | null
  onProposalChange?: (proposal: CopilotActionProposal) => void
  language?: CopilotUiLanguage
  actions?: CopilotAssistantActions
}) {
  const endRef = useRef<HTMLDivElement>(null)
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant")

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" })
  }, [messages.length, isLoading, stage])

  return (
    <div className="copilot-scroll flex-1 overflow-y-auto bg-background/35 px-3 py-4">
      <div className="copilot-column space-y-5">
      {messages.map((message) =>
        message.role === "user" ? (
          <article
            key={message.id}
            lang={langAttribute(undefined, message.content)}
            className="ml-auto w-fit max-w-[84%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm leading-6 text-primary-foreground shadow-sm"
          >
            {message.content}
            {message.failed ? (
              <span className="mt-1 block text-[11px] font-normal opacity-80">{t(language, "failedQuestion")}</span>
            ) : null}
          </article>
        ) : (
          <div key={message.id} className="flex items-start gap-2.5">
            <span
              aria-hidden="true"
              className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary"
            >
              <Sparkles className="size-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <CopilotAssistantMessage
                message={message}
                onProposalChange={onProposalChange}
                language={language}
                actions={actions}
                isLatest={message.id === latestAssistant?.id}
              />
            </div>
          </div>
        )
      )}
      {isLoading ? <div className="pl-[38px]"><CopilotStageSteps stage={stage} language={language} /></div> : null}
      {/* Announce only the newest answer, not the whole list, to screen readers. */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {isLoading ? "" : latestAssistant ? t(language, "answerReady") : ""}
      </div>
      <div ref={endRef} />
      </div>
    </div>
  )
}
