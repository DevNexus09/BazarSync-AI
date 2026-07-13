import { Bot } from "lucide-react"

import { CopilotAssistantMessage } from "@/components/copilot/CopilotAssistantMessage"
import type { CopilotActionProposal, CopilotLocalMessage } from "@/types/copilot"

export function CopilotMessageList({
  messages,
  isLoading,
  onProposalChange,
}: {
  messages: CopilotLocalMessage[]
  isLoading: boolean
  onProposalChange?: (proposal: CopilotActionProposal) => void
}) {
  return (
    <div
      className="flex-1 space-y-3 overflow-y-auto bg-background/35 px-3 py-3"
      aria-live="polite"
    >
      {messages.map((message) =>
        message.role === "user" ? (
          <article
            key={message.id}
            className="ml-auto max-w-[84%] rounded-2xl rounded-br-md bg-primary px-3 py-2 text-sm font-medium leading-5 text-primary-foreground"
          >
            {message.content}
          </article>
        ) : (
          <CopilotAssistantMessage
            key={message.id}
            message={message}
            onProposalChange={onProposalChange}
          />
        )
      )}
      {isLoading ? (
        <div className="flex items-center gap-2 rounded-2xl border border-border/60 bg-card p-3 text-sm text-muted-foreground">
          <Bot className="size-4 animate-pulse text-primary" />
          Copilot is checking your business data...
        </div>
      ) : null}
    </div>
  )
}
