import { useEffect, useRef } from "react"
import { Bot } from "lucide-react"

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
    <div className="copilot-scroll flex-1 overflow-y-auto bg-background/35 px-3 py-3">
      <div className="copilot-column space-y-3">
      {messages.map((message) =>
        message.role === "user" ? (
          <article
            key={message.id}
            lang={langAttribute(undefined, message.content)}
            className="ml-auto max-w-[84%] rounded-2xl rounded-br-md bg-primary px-3 py-2 text-sm font-medium leading-5 text-primary-foreground"
          >
            {message.content}
            {message.failed ? (
              <span className="mt-1 block text-[11px] font-normal opacity-80">{t(language, "failedQuestion")}</span>
            ) : null}
          </article>
        ) : (
          <CopilotAssistantMessage
            key={message.id}
            message={message}
            onProposalChange={onProposalChange}
            language={language}
            actions={actions}
            isLatest={message.id === latestAssistant?.id}
          />
        )
      )}
      {isLoading && stage ? <CopilotStageSteps stage={stage} language={language} /> : null}
      {isLoading && !stage ? (
        <div className="flex items-center gap-2 rounded-2xl border border-border/60 bg-card p-3 text-sm text-muted-foreground">
          <Bot className="size-4 animate-pulse text-primary motion-reduce:animate-none" aria-hidden="true" />
          {t(language, "thinking")}
        </div>
      ) : null}
      {/* Announce only the newest answer, not the whole list, to screen readers. */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {isLoading ? "" : latestAssistant ? t(language, "answerReady") : ""}
      </div>
      <div ref={endRef} />
      </div>
    </div>
  )
}
