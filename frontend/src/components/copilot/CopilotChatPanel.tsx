import { forwardRef, useImperativeHandle, useRef } from "react"
import type { KeyboardEvent, ReactNode } from "react"

import { CopilotChatShell } from "@/components/copilot/CopilotChatShell"
import { cn } from "@/lib/utils"

import "@/components/copilot/copilot.css"

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export const CopilotChatPanel = forwardRef<
  HTMLDivElement,
  {
    open: boolean
    onClose: () => void
    children: ReactNode
    title?: string
    subtitle?: string
    actions?: ReactNode
  }
>(({ open, onClose, children, title, subtitle, actions }, ref) => {
  const panelRef = useRef<HTMLDivElement>(null)
  useImperativeHandle(ref, () => panelRef.current as HTMLDivElement)

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open) {
      return
    }
    // Esc closes from anywhere in the panel, unless an IME is composing text.
    if (event.key === "Escape" && !event.nativeEvent.isComposing) {
      event.preventDefault()
      onClose()
      return
    }
    // Keep Tab focus inside the open panel (it covers the page on mobile).
    if (event.key === "Tab" && panelRef.current) {
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => !element.hasAttribute("disabled")
      )
      if (!focusable.length) {
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  }

  return (
    <div
      ref={panelRef}
      data-testid="copilot-chat-panel"
      onKeyDown={onKeyDown}
      inert={!open}
      className={cn(
        "fixed bottom-0 left-0 right-0 z-[80] h-[86dvh] w-screen origin-bottom-right transition duration-200 ease-out motion-reduce:transition-none sm:bottom-6 sm:left-auto sm:right-6 sm:h-[620px] sm:max-h-[calc(100dvh-3rem)] sm:w-[420px] sm:max-w-[calc(100vw-2rem)]",
        open ? "pointer-events-auto translate-y-0 scale-100 opacity-100" : "pointer-events-none translate-y-3 scale-95 opacity-0"
      )}
    >
      <CopilotChatShell onClose={onClose} title={title} subtitle={subtitle} actions={actions}>
        {children}
      </CopilotChatShell>
    </div>
  )
})

CopilotChatPanel.displayName = "CopilotChatPanel"
