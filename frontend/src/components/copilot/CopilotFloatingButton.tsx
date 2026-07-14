import { forwardRef } from "react"
import { BotMessageSquare } from "lucide-react"

import { cn } from "@/lib/utils"

export const CopilotFloatingButton = forwardRef<
  HTMLButtonElement,
  {
    open: boolean
    onClick: () => void
  }
>(({ open, onClick }, ref) => {
  return (
    <button
      ref={ref}
      type="button"
      aria-label="Open AI Business Copilot"
      aria-expanded={open}
      onClick={onClick}
      className={cn(
        "fixed bottom-5 right-5 z-[70] flex size-[60px] items-center justify-center rounded-full border border-primary/40 bg-primary text-primary-foreground shadow-[0_18px_50px_rgb(var(--primary)/.35)] transition duration-200 hover:scale-105 hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/30 sm:bottom-6 sm:right-6",
        open ? "pointer-events-none scale-95 opacity-0" : "opacity-100"
      )}
    >
      <BotMessageSquare className="size-6" aria-hidden="true" />
    </button>
  )
})

CopilotFloatingButton.displayName = "CopilotFloatingButton"
