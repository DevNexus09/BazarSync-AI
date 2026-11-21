import { useState } from "react"
import type { ReactNode } from "react"
import { Check, Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react"

import { CopilotActionProposalCard } from "@/components/copilot/CopilotActionProposalCard"
import { CopilotMarkdown } from "@/components/copilot/CopilotMarkdown"
import { langAttribute, t, type CopilotUiLanguage } from "@/components/copilot/copilot-i18n"
import { cn } from "@/lib/utils"
import type { CopilotActionProposal, CopilotFeedbackRating, CopilotLocalMessage } from "@/types/copilot"

export type CopilotAssistantActions = {
  onRegenerate?: (messageId: string) => void
  onFeedback?: (messageId: string, rating: CopilotFeedbackRating) => void
  onFollowUp?: (question: string) => void
  disabled?: boolean
}

export function CopilotAssistantMessage({
  message,
  onProposalChange,
  language = "en",
  actions,
  isLatest = false,
}: {
  message: Extract<CopilotLocalMessage, { role: "assistant" }>
  onProposalChange?: (proposal: CopilotActionProposal) => void
  language?: CopilotUiLanguage
  actions?: CopilotAssistantActions
  isLatest?: boolean
}) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(message.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard can be blocked (permissions, insecure context); nothing else to do.
    }
  }

  return (
    <article className="rounded-2xl rounded-bl-md border border-border/60 bg-card p-3 text-sm text-foreground shadow-sm">
      <div lang={langAttribute(message.replyLanguage, message.content)}>
        <CopilotMarkdown text={message.content} />
      </div>
      {message.actionProposal ? (
        <div className="mt-3">
          <CopilotActionProposalCard proposal={message.actionProposal} onStatusChange={onProposalChange} />
        </div>
      ) : null}
      {isLatest && message.followUps?.length && actions?.onFollowUp ? (
        <div className="mt-3" lang={langAttribute(message.replyLanguage, message.followUps.join(" "))}>
          <p className="mb-1.5 text-xs font-semibold text-muted-foreground">{t(language, "followUps")}</p>
          <div className="flex flex-wrap gap-1.5">
            {message.followUps.map((question) => (
              <button
                key={question}
                type="button"
                disabled={actions.disabled}
                onClick={() => actions.onFollowUp?.(question)}
                className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-left text-xs font-medium transition hover:border-primary/40 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {actions ? (
        <div className="mt-3 flex items-center gap-1 border-t border-border/50 pt-2 text-muted-foreground">
          <IconAction label={copied ? t(language, "copied") : t(language, "copy")} onClick={copy}>
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          </IconAction>
          {actions.onRegenerate ? (
            <IconAction label={t(language, "regenerate")} disabled={actions.disabled} onClick={() => actions.onRegenerate?.(message.id)}>
              <RotateCcw className="size-3.5" />
            </IconAction>
          ) : null}
          {actions.onFeedback ? (
            <>
              <IconAction
                label={t(language, "helpful")}
                pressed={message.feedback === "up"}
                onClick={() => actions.onFeedback?.(message.id, "up")}
              >
                <ThumbsUp className="size-3.5" />
              </IconAction>
              <IconAction
                label={t(language, "notHelpful")}
                pressed={message.feedback === "down"}
                onClick={() => actions.onFeedback?.(message.id, "down")}
              >
                <ThumbsDown className="size-3.5" />
              </IconAction>
              {message.feedback ? <span className="ml-1 text-[11px]">{t(language, "thanks")}</span> : null}
            </>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

function IconAction({
  label,
  onClick,
  disabled,
  pressed,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  pressed?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex size-7 items-center justify-center rounded-md transition hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-40",
        pressed ? "bg-primary/10 text-primary" : ""
      )}
    >
      {children}
    </button>
  )
}
