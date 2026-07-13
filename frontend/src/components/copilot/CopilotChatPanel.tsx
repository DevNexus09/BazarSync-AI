import { forwardRef } from "react"
import type { ReactNode } from "react"

import { CopilotChatShell } from "@/components/copilot/CopilotChatShell"
import { cn } from "@/lib/utils"

export const CopilotChatPanel = forwardRef<
  HTMLDivElement,
  {
    open: boolean
    onClose: () => void
    children: ReactNode
  }
>(({ open, onClose, children }, ref) => {
  return (
    <div
      ref={ref}
      data-testid="copilot-chat-panel"
      className={cn(
        "fixed bottom-0 left-0 right-0 z-[80] h-[86dvh] w-screen origin-bottom-right transition duration-200 ease-out motion-reduce:transition-none sm:bottom-6 sm:left-auto sm:right-6 sm:h-[620px] sm:max-h-[calc(100dvh-3rem)] sm:w-[420px] sm:max-w-[calc(100vw-2rem)]",
        open
          ? "pointer-events-auto translate-y-0 scale-100 opacity-100"
          : "pointer-events-none translate-y-3 scale-95 opacity-0"
      )}
    >
      <CopilotChatShell onClose={onClose}>{children}</CopilotChatShell>
    </div>
  )
})

CopilotChatPanel.displayName = "CopilotChatPanel"
