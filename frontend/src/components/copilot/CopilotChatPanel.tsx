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
    /** Full-page mode on wider screens; phones always get a full-screen sheet. */
    expanded?: boolean
    onToggleExpanded?: () => void
  }
>(({ open, onClose, children, title, subtitle, actions, expanded = false, onToggleExpanded }, ref) => {
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
      data-expanded={expanded ? "" : undefined}
      className={cn(
        "fixed inset-0 z-[80] h-[100dvh] w-screen origin-bottom-right transition-[opacity,transform,inset,width,height] duration-200 ease-out motion-reduce:transition-none",
        expanded
          ? "sm:inset-4 sm:h-auto sm:w-auto"
          : "sm:inset-auto sm:bottom-6 sm:right-6 sm:h-[640px] sm:max-h-[calc(100dvh-3rem)] sm:w-[440px] sm:max-w-[calc(100vw-2rem)]",
        open ? "pointer-events-auto translate-y-0 scale-100 opacity-100" : "pointer-events-none translate-y-3 scale-95 opacity-0"
      )}
    >
      <CopilotChatShell
        onClose={onClose}
        title={title}
        subtitle={subtitle}
        actions={actions}
        expanded={expanded}
        onToggleExpanded={onToggleExpanded}
      >
        {children}
      </CopilotChatShell>
    </div>
  )
})

CopilotChatPanel.displayName = "CopilotChatPanel"
